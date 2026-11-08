"""Herzstück: Modelle trainieren, Tipps berechnen, Bilanz, Rückblick und Spielgeld."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import config as C
from markets import all_markets, outcome_hit
from model import score_matrix
from predictor import NATION_SLUGS, Params, Predictor, outcome_probs
from sources.espn import DEAD, FINAL_90, FINAL_ET, parse_date
from tuning import sim_row, targets

ROOT = Path(__file__).resolve().parent
DEFAULT_GROUPS = {"1x2", "dc", "ou", "btts", "team", "combo"}
SIM_VERSION = 3


# ---------------- Hilfen ----------------
def group_of(key: str) -> str:
    if "+" in key:
        return "combo"
    if key in ("1", "X", "2"):
        return "1x2"
    if key in ("1X", "X2", "12"):
        return "dc"
    if key.startswith("CS"):
        return "cs"
    if key[0] == "C":
        return "corners"
    if key[0] == "K":
        return "cards"
    if key in ("BTTS", "NOBTTS"):
        return "btts"
    if key[0] in "OU":
        return "ou"
    return "team"


def pick_best(markets: dict, odds: dict, risk: str = "ausgewogen", groups=DEFAULT_GROUPS) -> dict | None:
    """Bester Tipp eines Spiels: mit Quote nach Value, sonst nach Wahrscheinlichkeit."""
    R = C.RISK[risk]
    value, safe = [], []
    for k, p in markets.items():
        if group_of(k) not in groups or p <= 0:
            continue
        o = odds.get(k)
        if o:
            eff = o
            ev = p * eff - 1
            if R["min_odds"] <= eff <= R["max_odds"] and ev >= R["min_ev"]:
                value.append({"key": k, "p": round(p, 3), "odds": round(eff, 2), "ev": round(ev, 3)})
        fair = 1 / p
        if R["min_odds"] <= fair <= R["max_odds"]:
            safe.append({"key": k, "p": round(p, 3), "odds": round(o, 2) if o else None,
                         "fair": round(fair, 2)})
    if value:
        return max(value, key=lambda x: x["ev"])
    if safe:
        return max(safe, key=lambda x: x["p"])
    return None


def top_options(markets: dict, odds: dict, risk: str = "ausgewogen", n_single: int = 5, n_combo: int = 3):
    """Wie die Web-App mit Standard-Einstellungen: beste Einzeltipps und Kombis im Spiel."""
    R = C.RISK[risk]
    rows = []
    for k, p in markets.items():
        g = group_of(k)
        if g not in DEFAULT_GROUPS or p <= 0.001:
            continue
        o = odds.get(k)
        q = o or 1 / p
        in_win = R["min_odds"] <= q <= R["max_odds"]
        ev = p * o - 1 if o else None
        rows.append({"key": k, "p": round(p, 3), "odds": round(o, 2) if o else None,
                     "ev": round(ev, 3) if ev is not None else None,
                     "value": ev is not None and ev >= R["min_ev"] and in_win, "in": in_win, "g": g})

    def ranked(rs):
        val = sorted([r for r in rs if r["value"]], key=lambda r: -r["ev"])
        safe = sorted([r for r in rs if not r["value"] and r["in"]], key=lambda r: -r["p"])
        return [{k: v for k, v in r.items() if k in ("key", "p", "odds", "ev")} for r in val + safe]

    singles = ranked([r for r in rows if r["g"] != "combo"])[:n_single]
    combos = ranked([r for r in rows if r["g"] == "combo"])[:n_combo]
    return singles, combos


def team_info(events):
    info = {}
    for e in sorted(events, key=lambda e: e["date"]):
        for side in ("home", "away"):
            t = e[side]
            old = info.get(t["id"], {})
            logo = t.get("logo") or old.get("logo") or \
                (f"https://a.espncdn.com/i/teamlogos/soccer/500/{t['id']}.png" if e["slug"] not in NATION_SLUGS else "")
            info[t["id"]] = {"id": t["id"], "name": t["name"], "tla": t["tla"] or t["name"][:3].upper(), "logo": logo}
    return info


def form_details(events) -> dict[str, list]:
    """Letzte 10 Spiele je Team: [Ergebnis, Gegner-ID, Tore, Gegentore, Heim 1/0, Datum, Wettbewerb, Verl. 1/0, Spiel-ID]."""
    res = defaultdict(list)
    for e in sorted(events, key=lambda e: e["date"]):
        if e["completed"] and e["hs"] is not None and e["status"] in FINAL_90 | FINAL_ET:
            h, a, hs, as_ = e["home"]["id"], e["away"]["id"], e["hs"], e["as"]
            et = 0 if e["status"] in FINAL_90 else 1
            r = "U" if hs == as_ else ("S" if hs > as_ else "N")
            day = e["date"][:10]
            res[h].append([r, a, hs, as_, 1, day, e["slug"], et, e["id"]])
            res[a].append([{"S": "N", "N": "S", "U": "U"}[r], h, as_, hs, 0, day, e["slug"], et, e["id"]])
    return {k: v[-10:] for k, v in res.items()}


def form_of(events, now, details=None):
    details = details or form_details(events)
    return {k: "".join(x[0] for x in v[-5:]) for k, v in details.items()}


def r(x, d=4):
    return round(float(x), d)


# ---------------- Tipps für kommende Spiele ----------------
def build_upcoming(pr: Predictor, events, info, form, odds, now):
    up = []
    for e in events:
        if e["slug"] not in C.DISPLAY or e["completed"] or e["status"] in DEAD:
            continue
        dt = parse_date(e["date"])
        if not (now - timedelta(hours=2) <= dt <= now + timedelta(days=C.DAYS_AHEAD)):
            continue
        o = odds.get(e["id"], {})
        res = pr.predict(e, o)
        if not res:
            continue
        p = res["pred"]
        mk = all_markets(p.matrix, res["corners"], res["cards"])
        hs, as_, ps = p.best_score()
        up.append({
            "id": e["id"], "kickoff": dt.isoformat(), "comp": e["slug"],
            "home": {**info[e["home"]["id"]], "form": form.get(e["home"]["id"], "")},
            "away": {**info[e["away"]["id"]], "form": form.get(e["away"]["id"], "")},
            "neutral": e["neutral"], "known": res["known"],
            "xg": [r(p.xg_home, 2), r(p.xg_away, 2)],
            "xc": [r(x, 2) for x in res["corners"]] if res["corners"] else None,
            "xk": [r(x, 2) for x in res["cards"]] if res["cards"] else None,
            "p": [r(p.p_home, 3), r(p.p_draw, 3), r(p.p_away, 3)],
            "p_model": [r(x, 3) for x in res["p_model"]],
            "p_market": [r(x, 3) for x in res["p_market"]] if res["p_market"] else None,
            "sot": res["sot"],
            "tip": p.tip, "score": [hs, as_, r(ps, 3)],
            "m": {k: r(v) for k, v in mk.items()},
            "odds": o,
            "grid": [[r(v) for v in row] for row in p.matrix[:7, :7]],
            "pick": pick_best(mk, o if res["known"] else {}),
        })
    up.sort(key=lambda x: (x["kickoff"], x["comp"]))
    return up


# ---------------- Bilanz ----------------
def update_history(prev: list[dict], upcoming: list[dict], events_by_id: dict, now) -> list[dict]:
    hist = {h["id"]: h for h in prev}
    for u in upcoming:
        if parse_date(u["kickoff"]) > now:  # letzter Stand vor Anpfiff zählt
            hist[u["id"]] = {"id": u["id"], "kickoff": u["kickoff"], "comp": u["comp"],
                             "home": {k: u["home"].get(k, "") for k in ("id", "name", "tla", "logo")},
                             "away": {k: u["away"].get(k, "") for k in ("id", "name", "tla", "logo")},
                             "p": u["p"], "tip": u["tip"], "score": u["score"][:2], "xg": u["xg"],
                             "pick": u["pick"], "result": None}
            singles, combos = top_options(u["m"], u["odds"] if u["known"] else {})
            hist[u["id"]]["tips"], hist[u["id"]]["combos"] = singles, combos
    for h in hist.values():
        if h.get("result") is not None:
            continue
        e = events_by_id.get(h["id"])
        if not e:
            continue
        if e["status"] in DEAD:
            h["result"] = "void"
        elif e["completed"] and e["hs"] is not None:
            h["result"] = [e["hs"], e["as"]] if e["status"] in FINAL_90 else "et"
            if h["result"] not in ("et", "void"):
                if h.get("pick"):
                    h["pick"]["hit"] = outcome_hit(h["pick"]["key"], e["hs"], e["as"], e.get("fd"))
                for t in h.get("tips", []) + h.get("combos", []):
                    t["hit"] = outcome_hit(t["key"], e["hs"], e["as"], e.get("fd"))
    keep = [h for h in hist.values()
            if h.get("result") is not None or parse_date(h["kickoff"]) > now - timedelta(days=4)]
    keep.sort(key=lambda h: h["kickoff"], reverse=True)
    return keep[:4000]


def backfill_history(history: list[dict], events: list[dict], params: Params, info: dict, now: datetime,
                     since: datetime, extra_ids: set | None = None, extra_since: datetime | None = None,
                     log=print) -> list[dict]:
    """Nachträgliche Tipps für bereits gespielte Partien: pro Spielwoche nur mit Daten davor trainiert,
    mit den damaligen Quoten (falls vorhanden). Einträge bekommen retro=True."""
    have = {h["id"] for h in history}
    extra_ids = extra_ids or set()
    extra_since = extra_since or since

    def wanted(e):
        d = parse_date(e["date"])
        if d >= now - timedelta(hours=3):
            return False
        if e["slug"] in C.DISPLAY and d >= since:
            return True
        return e["id"] in extra_ids and d >= extra_since

    todo = [e for e in events if e["completed"] and e["hs"] is not None and e["id"] not in have
            and e["home"]["id"] in info and e["away"]["id"] in info and wanted(e)]
    if not todo:
        return history
    weeks = defaultdict(list)
    for e in todo:
        d = parse_date(e["date"])
        weeks[(d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)].append(e)
    warm, added = None, []
    for monday in sorted(weeks):
        try:
            pr = Predictor(params).fit(events, monday, warm=warm)
        except ValueError:
            continue
        warm = pr
        for e in weeks[monday]:
            fd = e.get("fd") or {}
            odds = {k: fd[f] for k, f in (("1", "o1"), ("X", "oX"), ("2", "o2"), ("O2.5", "oO25"), ("U2.5", "oU25"))
                    if fd.get(f)}
            res = pr.predict(e, odds)
            if not res:
                continue
            p = res["pred"]
            mk = all_markets(p.matrix, res["corners"], res["cards"])
            use_odds = odds if res["known"] else {}
            hs, as_, _ = p.best_score()
            entry = {"id": e["id"], "kickoff": parse_date(e["date"]).isoformat(), "comp": e["slug"], "retro": True,
                     "home": {k: info[e["home"]["id"]].get(k, "") for k in ("id", "name", "tla", "logo")},
                     "away": {k: info[e["away"]["id"]].get(k, "") for k in ("id", "name", "tla", "logo")},
                     "p": [r(p.p_home, 3), r(p.p_draw, 3), r(p.p_away, 3)], "tip": p.tip, "score": [hs, as_],
                     "xg": [r(p.xg_home, 2), r(p.xg_away, 2)], "pick": pick_best(mk, use_odds), "result": None}
            entry["tips"], entry["combos"] = top_options(mk, use_odds)
            added.append(entry)
    log(f"Nachträgliche Tipps: {len(added)} Spiele in {len(weeks)} Wochen")
    return history + added


def history_summary(history: list[dict]) -> dict:
    """Kurzfassung der Bilanz für den Start der App (live getippt und nachträglich zusammen)."""
    done = [h for h in history if isinstance(h.get("result"), list)]
    out = lambda a, b: "1" if a > b else "X" if a == b else "2"
    picks = [h for h in done if h.get("pick") and isinstance(h["pick"].get("hit"), bool)]
    return {"done": len(done), "open": sum(1 for h in history if h.get("result") is None),
            "hits_1x2": sum(1 for h in done if h["tip"] == out(*h["result"])),
            "exact": sum(1 for h in done if h["score"] == h["result"]),
            "picks": len(picks), "pick_hits": sum(1 for h in picks if h["pick"]["hit"]),
            "tips": sum(1 for h in done for t in h.get("tips", []) if isinstance(t.get("hit"), bool)),
            "tip_hits": sum(1 for h in done for t in h.get("tips", []) if t.get("hit") is True),
            "retro": sum(1 for h in history if h.get("retro"))}


# ---------------- Rückblick (Simulation mit historischen Quoten) ----------------
def load_sim_cache(params: Params) -> dict:
    f = ROOT / "cache" / "sim.json"
    try:
        c = json.loads(f.read_text())
        if c.get("v") == SIM_VERSION and c.get("key") == [params.xi, params.beta]:
            return c["rows"]
    except (OSError, ValueError, KeyError):
        pass
    return {}


def save_sim_cache(params: Params, rows: dict):
    f = ROOT / "cache" / "sim.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": SIM_VERSION, "key": [params.xi, params.beta], "rows": rows}, separators=(",", ":")))


def build_sim(events: list[dict], now: datetime, params: Params, tuned_rows: list | None = None, log=print) -> list[list]:
    """Rückblick-Daten: Prognose jedes Top-5-Ligaspiels nur mit Daten vor seiner Spielwoche."""
    cache = {} if tuned_rows else load_sim_cache(params)
    if tuned_rows:   # frisch aus dem Feintuning
        by_key = {(e["date"][:10], e["slug"], e["home"]["tla"] or e["home"]["name"][:3]): e["id"]
                  for e in targets(events, now - timedelta(days=500))}
        for row in tuned_rows:
            eid = by_key.get((row[0], row[1], row[2]))
            if eid:
                cache[eid] = row
    start = now - timedelta(days=455)
    new = [e for e in targets(events, start) if e["id"] not in cache]
    weeks = defaultdict(list)
    for e in new:
        d = parse_date(e["date"])
        weeks[(d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)].append(e)
    warm = None
    for monday in sorted(weeks):
        try:
            pr = Predictor(params).fit(events, monday, warm=warm, with_nations=False, with_counts=False)
        except ValueError:
            continue
        warm = pr
        for e in weeks[monday]:
            mr = pr.model_rates(e)
            if mr:
                p1, px, p2, po = outcome_probs(score_matrix(mr[0], mr[1], pr.goals.rho))
                cache[e["id"]] = sim_row(e, p1, px, p2, po)
    save_sim_cache(params, cache)
    rows = sorted(cache.values(), key=lambda x: x[0])
    log(f"Rückblick: {len(rows)} Spiele mit historischen Quoten ({len(weeks)} neue Wochen gerechnet)")
    return rows


# ---------------- Spielgeld-Konto ----------------
def run_paper(state: dict | None, upcoming: list[dict], events_by_id: dict, now: datetime) -> dict:
    cfg = C.PAPER
    R = C.RISK[cfg["risk"]]
    if not state:
        state = {"start": cfg["start_budget"], "balance": cfg["start_budget"], "since": now.isoformat(),
                 "config": cfg, "bets": [], "curve": [[now.date().isoformat(), cfg["start_budget"]]]}
    # 1. offene Wetten abrechnen
    for b in state["bets"]:
        if b["status"] != "open":
            continue
        e = events_by_id.get(b["id"])
        if not e:
            continue
        if e["status"] in DEAD or (e["completed"] and e["status"] not in FINAL_90):
            b["status"], b["payout"] = "void", b["stake"]  # Abbruch/Verlängerung: Einsatz zurück
        elif e["completed"] and e["hs"] is not None:
            hit = outcome_hit(b["key"], e["hs"], e["as"])
            b["status"] = "won" if hit else "lost"
            b["payout"] = round(b["stake"] * b["odds"], 2) if hit else 0.0
            b["result"] = [e["hs"], e["as"]]
        if b["status"] != "open":
            state["balance"] = round(state["balance"] + b["payout"], 2)
    # 2. neue Wetten für Spiele der nächsten 24 Stunden
    placed = {b["id"] for b in state["bets"]}
    allowed = set()
    if "1X2" in cfg["markets"]:
        allowed |= {"1", "X", "2"}
    # Strategie: pro Spiel der beste Tipp der App, der eine echte Marktquote hat.
    # Value-Tipps zuerst, sonst der wahrscheinlichste Tipp im Quotenbereich des Risikoprofils.
    cands = []
    for u in upcoming:
        if u["id"] in placed or not u["odds"] or not u["known"]:
            continue
        ko = parse_date(u["kickoff"])
        if not (now < ko <= now + timedelta(hours=24)):
            continue
        best = None
        for k, o in u["odds"].items():
            if not (k in allowed or ("OU" in cfg["markets"] and k[0] in "OU")):
                continue
            p = u["m"].get(k)
            if p is None or not (R["min_odds"] <= o <= R["max_odds"]):
                continue
            ev = p * o - 1
            score = (1, ev) if ev >= R["min_ev"] else (0, p)
            if best is None or score > best[0]:
                best = (score, ev, u, k, p, o)
        if best:
            cands.append(best)
    cands.sort(key=lambda x: x[0], reverse=True)
    cands = [c[1:] for c in cands]
    used = set()
    n = 0
    for ev, u, k, p, eff in cands:
        if u["id"] in used or n >= cfg["max_bets_per_day"]:
            continue
        stake = cfg["stake"] if cfg["stake_mode"] == "fix" else state["balance"] * cfg["stake"] / 100
        stake = round(min(stake, state["balance"]), 2)
        if stake < 0.5:
            break
        state["balance"] = round(state["balance"] - stake, 2)
        state["bets"].append({"id": u["id"], "placed": now.isoformat(), "kickoff": u["kickoff"],
                              "comp": u["comp"], "match": f"{u['home']['name']} – {u['away']['name']}",
                              "key": k, "p": round(p, 3), "odds": round(eff, 2), "ev": round(ev, 3),
                              "stake": stake, "status": "open", "payout": None})
        used.add(u["id"])
        n += 1
    open_stakes = sum(b["stake"] for b in state["bets"] if b["status"] == "open")
    today = now.date().isoformat()
    total = round(state["balance"] + open_stakes, 2)
    if state["curve"] and state["curve"][-1][0] == today:
        state["curve"][-1][1] = total
    else:
        state["curve"].append([today, total])
    return state


# ---------------- Ranking ----------------
def build_rankings(pr: Predictor, events, info, form, now) -> dict:
    goals = pr.goals
    season_start = datetime(now.year if now.month >= 7 else now.year - 1, 7, 1, tzinfo=timezone.utc)
    by_league = defaultdict(set)
    for e in events:
        if e["slug"] in C.TOP5 and parse_date(e["date"]) >= season_start:
            by_league[e["slug"]] |= {e["home"]["id"], e["away"]["id"]}
    ref = [t for s in by_league.values() for t in s if goals.knows(t)]
    if not ref:
        return {}
    mean_att = np.mean([goals.att[t] for t in ref])
    mean_dfn = np.mean([goals.dfn[t] for t in ref])
    ha = goals.home_adv / 2

    def row(t, slug=None):
        gf = math.exp(goals.att[t] + mean_dfn + ha)
        ga = math.exp(mean_att + goals.dfn[t] + ha)
        out = {"team": info[t], "gf": round(gf, 2), "ga": round(ga, 2), "form": form.get(t, "")}
        if slug:
            out["comp"] = slug
        return out

    out = {}
    for slug, teams in by_league.items():
        rows = [row(t) for t in teams if goals.knows(t)]
        out[slug] = sorted(rows, key=lambda x: x["gf"] - x["ga"], reverse=True)
    europe = [row(t, s) for s, teams in by_league.items() for t in teams if goals.knows(t)]
    out["europa"] = sorted(europe, key=lambda x: x["gf"] - x["ga"], reverse=True)[:30]
    return out


def team_ratings(pr: Predictor, rankings: dict, teams: set[str], events, now) -> dict:
    """Stärke je Team (erwartete Tore für/gegen gegen ein Durchschnittsteam) und Ranking-Plätze."""
    out = {}
    rank_eu = {r["team"]["id"]: i + 1 for i, r in enumerate(rankings.get("europa", []))}
    rank_lg = {}
    for slug, rows in rankings.items():
        if slug != "europa":
            for i, r in enumerate(rows):
                rank_lg[r["team"]["id"]] = (slug, i + 1, len(rows))
    since = now - timedelta(days=400)
    league_of = defaultdict(lambda: defaultdict(int))
    for e in events:
        if e["completed"] and (e["slug"] in C.LEAGUE_SLUGS or e["slug"] in NATION_SLUGS) and parse_date(e["date"]) >= since:
            league_of[e["home"]["id"]][e["slug"]] += 1
            league_of[e["away"]["id"]][e["slug"]] += 1
    for kind, m in (("club", pr.goals), ("nation", pr.nation)):
        if not m:
            continue
        ref = list(m.att) if kind == "nation" else [r["team"]["id"] for rows in rankings.values() for r in rows if r["team"]["id"] in m.att]
        if not ref:
            continue
        ma, md = np.mean([m.att[t] for t in ref]), np.mean([m.dfn[t] for t in ref])
        for t in teams:
            if t in m.att and t not in out:
                gf = math.exp(m.att[t] + md + m.home_adv / 2)
                ga = math.exp(ma + m.dfn[t] + m.home_adv / 2)
                lg = max(league_of[t].items(), key=lambda x: x[1])[0] if league_of.get(t) else None
                o = {"gf": round(gf, 2), "ga": round(ga, 2), "kind": kind, "league": lg, "games": m.games.get(t, 0)}
                if t in rank_eu:
                    o["rank_eu"] = rank_eu[t]
                if t in rank_lg:
                    o["rank_lg"] = list(rank_lg[t])
                out[t] = o
    return out


# ---------------- Top-Tipps (Telegram) ----------------
def top_tips(upcoming, now, hours=36, n=8):
    soon = [u for u in upcoming if now < parse_date(u["kickoff"]) <= now + timedelta(hours=hours)
            and u["pick"] and u["known"]]
    with_val = sorted([u for u in soon if u["pick"].get("ev") is not None], key=lambda u: -u["pick"]["ev"])
    by_p = sorted([u for u in soon if u["pick"].get("ev") is None], key=lambda u: -u["pick"]["p"])
    singles = (with_val + by_p)[:n]
    # Kombi: die 3 sichersten Tipps mit fairer Quote 1.3 bis 1.9 aus verschiedenen Spielen
    legs = []
    for u in sorted(soon, key=lambda u: -u["p"][["1", "X", "2"].index(u["tip"])]):
        best = None
        for k, p in u["m"].items():
            if group_of(k) in DEFAULT_GROUPS - {"combo"} and 1.3 <= 1 / p <= 1.9:
                if best is None or p > best[1]:
                    best = (k, p)
        if best:
            legs.append((u, *best))
        if len(legs) == 3:
            break
    return singles, legs

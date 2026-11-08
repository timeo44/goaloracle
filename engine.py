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
from model import DixonColes, Match, RateModel
from sources.espn import DEAD, FINAL_90, FINAL_ET, parse_date

ROOT = Path(__file__).resolve().parent
NATION_SLUGS = {s for s, v in C.DISPLAY.items() if v[2] == "nation"} | set(C.TRAIN_NATION)
DEFAULT_GROUPS = {"1x2", "dc", "ou", "btts", "team", "combo"}
SIM_VERSION = 2


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


def to_matches(events: list[dict]) -> list[Match]:
    out = []
    for e in events:
        if not e["completed"] or e["hs"] is None or e["status"] not in FINAL_90:
            continue
        extra = {}
        fd = e.get("fd") or {}
        for k in ("hc", "ac", "hy", "ay"):
            if fd.get(k) is not None:
                extra[k] = int(fd[k])
        out.append(Match(parse_date(e["date"]), e["home"]["id"], e["away"]["id"], e["hs"], e["as"],
                         neutral=e["neutral"], comp=e["slug"], id=e["id"], extra=extra))
    return out


class Models:
    def __init__(self, club, nation, corners, cards):
        self.club, self.nation, self.corners, self.cards = club, nation, corners, cards

    def for_slug(self, slug):
        return self.nation if slug in NATION_SLUGS else self.club


def fit_models(events: list[dict], ref: datetime, warm: Models | None = None, log=print) -> Models:
    club_ev = [e for e in events if e["slug"] not in NATION_SLUGS]
    nat_ev = [e for e in events if e["slug"] in NATION_SLUGS]
    league_teams = {t for e in club_ev if e["slug"] in C.LEAGUE_SLUGS for t in (e["home"]["id"], e["away"]["id"])}
    cm = to_matches(club_ev)
    club = DixonColes().fit(cm, ref, league_teams=league_teams, warm=warm.club if warm else None)
    try:
        nation = DixonColes(weak_prior=0.3).fit(to_matches(nat_ev), ref, warm=warm.nation if warm else None)
    except ValueError:
        nation = None
    corners = cards = None
    try:
        corners = RateModel().fit([m for m in cm if "hc" in m.extra], ref, key=("hc", "ac"))
        cards = RateModel().fit([m for m in cm if "hy" in m.extra], ref, key=("hy", "ay"))
    except ValueError:
        pass
    log(f"Modelle: Clubs {len(club.teams)} Teams/{club.n_matches} Spiele, "
        f"Nationen {len(nation.teams) if nation else 0} Teams, "
        f"Ecken {corners.n_matches if corners else 0} Spiele")
    return Models(club, nation, corners, cards)


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
    """Letzte 5 Spiele je Team: [Ergebnis, Gegner-ID, Tore, Gegentore, Heim 1/0, Datum, Wettbewerb, Verl. 1/0]."""
    res = defaultdict(list)
    for e in sorted(events, key=lambda e: e["date"]):
        if e["completed"] and e["hs"] is not None and e["status"] in FINAL_90 | FINAL_ET:
            h, a, hs, as_ = e["home"]["id"], e["away"]["id"], e["hs"], e["as"]
            et = 0 if e["status"] in FINAL_90 else 1
            r = "U" if hs == as_ else ("S" if hs > as_ else "N")
            day = e["date"][:10]
            res[h].append([r, a, hs, as_, 1, day, e["slug"], et])
            res[a].append([{"S": "N", "N": "S", "U": "U"}[r], h, as_, hs, 0, day, e["slug"], et])
    return {k: v[-5:] for k, v in res.items()}


def form_of(events, now, details=None):
    details = details or form_details(events)
    return {k: "".join(x[0] for x in v) for k, v in details.items()}


def r(x, d=4):
    return round(float(x), d)


# ---------------- Tipps für kommende Spiele ----------------
def predict_event(models: Models, e: dict) -> dict | None:
    m = models.for_slug(e["slug"])
    if m is None:
        return None
    h, a = e["home"]["id"], e["away"]["id"]
    pred = m.predict(h, a, neutral=e["neutral"])
    corners = cards = None
    if m is models.club:
        if models.corners and models.corners.knows(h) and models.corners.knows(a):
            corners = models.corners.rates(h, a, e["neutral"])
        if models.cards and models.cards.knows(h) and models.cards.knows(a):
            cards = models.cards.rates(h, a, e["neutral"])
    mk = all_markets(pred.matrix, corners, cards)
    reliable = m.knows(h, C.MIN_GAMES) and m.knows(a, C.MIN_GAMES)
    return {"pred": pred, "markets": mk, "corners": corners, "cards": cards, "known": reliable}


def build_upcoming(models, events, info, form, odds, now):
    up = []
    for e in events:
        if e["slug"] not in C.DISPLAY or e["completed"] or e["status"] in DEAD:
            continue
        dt = parse_date(e["date"])
        if not (now - timedelta(hours=2) <= dt <= now + timedelta(days=C.DAYS_AHEAD)):
            continue
        res = predict_event(models, e)
        if not res:
            continue
        p = res["pred"]
        o = odds.get(e["id"], {})
        hs, as_, ps = p.best_score()
        mat = p.matrix[:7, :7]
        up.append({
            "id": e["id"], "kickoff": dt.isoformat(), "comp": e["slug"],
            "home": {**info[e["home"]["id"]], "form": form.get(e["home"]["id"], "")},
            "away": {**info[e["away"]["id"]], "form": form.get(e["away"]["id"], "")},
            "neutral": e["neutral"], "known": res["known"],
            "xg": [r(p.xg_home, 2), r(p.xg_away, 2)],
            "xc": [r(x, 2) for x in res["corners"]] if res["corners"] else None,
            "xk": [r(x, 2) for x in res["cards"]] if res["cards"] else None,
            "p": [r(p.p_home, 3), r(p.p_draw, 3), r(p.p_away, 3)],
            "tip": p.tip, "score": [hs, as_, r(ps, 3)],
            "m": {k: r(v) for k, v in res["markets"].items()},
            "odds": o,
            "grid": [[r(v) for v in row] for row in mat],
            "pick": pick_best(res["markets"], o if res["known"] else {}),
        })
    up.sort(key=lambda x: (x["kickoff"], x["comp"]))
    return up


# ---------------- Bilanz ----------------
def update_history(prev: list[dict], upcoming: list[dict], events_by_id: dict, now) -> list[dict]:
    hist = {h["id"]: h for h in prev}
    for u in upcoming:
        if parse_date(u["kickoff"]) > now:  # letzter Stand vor Anpfiff zählt
            hist[u["id"]] = {"id": u["id"], "kickoff": u["kickoff"], "comp": u["comp"],
                             "home": {k: u["home"].get(k, "") for k in ("name", "tla", "logo")},
                             "away": {k: u["away"].get(k, "") for k in ("name", "tla", "logo")},
                             "p": u["p"], "tip": u["tip"], "score": u["score"][:2],
                             "pick": u["pick"], "result": None}
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
            if h.get("pick") and h["result"] not in ("et", "void"):
                h["pick"]["hit"] = outcome_hit(h["pick"]["key"], e["hs"], e["as"], e.get("fd"))
    keep = [h for h in hist.values()
            if h.get("result") is not None or parse_date(h["kickoff"]) > now - timedelta(days=4)]
    keep.sort(key=lambda h: h["kickoff"], reverse=True)
    return keep[:1500]


# ---------------- Rückblick (Simulation mit historischen Quoten) ----------------
def build_sim(events: list[dict], now: datetime, log=print) -> list[list]:
    """Für jedes Top-5-Ligaspiel mit Quoten: Prognose nur mit Daten vor der Spielwoche."""
    cache_f = ROOT / "cache" / "sim.json"
    cache = {}
    if cache_f.exists():
        try:
            c = json.loads(cache_f.read_text())
            if c.get("v") == SIM_VERSION:
                cache = c["rows"]
        except (ValueError, KeyError):
            cache = {}
    start = datetime(now.year - 1, 8, 1, tzinfo=timezone.utc)  # letzte und laufende Saison
    targets = [e for e in events if e["slug"] in C.TOP5 and e.get("fd") and e["status"] in FINAL_90
               and e["fd"].get("o1") and parse_date(e["date"]) >= start and e["id"] not in cache]
    weeks = defaultdict(list)
    for e in targets:
        d = parse_date(e["date"])
        monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        weeks[monday].append(e)
    warm = None
    for monday in sorted(weeks):
        try:
            mdl = DixonColes().fit(to_matches([e for e in events if e["slug"] not in NATION_SLUGS]),
                                   monday, warm=warm)
        except ValueError:
            continue
        warm = mdl
        for e in weeks[monday]:
            p = mdl.predict(e["home"]["id"], e["away"]["id"], e["neutral"])
            fd = e["fd"]
            cache[e["id"]] = [e["date"][:10], e["slug"], e["home"]["tla"] or e["home"]["name"][:3],
                              e["away"]["tla"] or e["away"]["name"][:3],
                              r(p.p_home, 3), r(p.p_draw, 3), r(p.p_away, 3),
                              r(p.p_over25, 3), r(1 - p.p_over25, 3),
                              fd["o1"], fd["oX"], fd["o2"], fd.get("oO25"), fd.get("oU25"),
                              e["hs"], e["as"]]
    cache_f.parent.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps({"v": SIM_VERSION, "rows": cache}, separators=(",", ":")))
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
    cands = []
    for u in upcoming:
        if u["id"] in placed or not u["odds"] or not u["known"]:
            continue
        ko = parse_date(u["kickoff"])
        if not (now < ko <= now + timedelta(hours=24)):
            continue
        for k, o in u["odds"].items():
            if not (k in allowed or ("OU" in cfg["markets"] and k[0] in "OU")):
                continue
            p = u["m"].get(k)
            if p is None:
                continue
            eff = o
            ev = p * eff - 1
            if R["min_odds"] <= eff <= R["max_odds"] and ev >= R["min_ev"]:
                cands.append((ev, u, k, p, eff))
    cands.sort(key=lambda x: -x[0])
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
def build_rankings(models: Models, events, info, form, now) -> dict:
    season_start = datetime(now.year if now.month >= 7 else now.year - 1, 7, 1, tzinfo=timezone.utc)
    by_league = defaultdict(set)
    for e in events:
        if e["slug"] in C.TOP5 and parse_date(e["date"]) >= season_start:
            by_league[e["slug"]] |= {e["home"]["id"], e["away"]["id"]}
    ref = [t for s in by_league.values() for t in s if models.club.knows(t)]
    if not ref:
        return {}
    mean_att = np.mean([models.club.att[t] for t in ref])
    mean_dfn = np.mean([models.club.dfn[t] for t in ref])
    ha = models.club.home_adv / 2

    def row(t, slug=None):
        gf = math.exp(models.club.att[t] + mean_dfn + ha)
        ga = math.exp(mean_att + models.club.dfn[t] + ha)
        out = {"team": info[t], "gf": round(gf, 2), "ga": round(ga, 2), "form": form.get(t, "")}
        if slug:
            out["comp"] = slug
        return out

    out = {}
    for slug, teams in by_league.items():
        rows = [row(t) for t in teams if models.club.knows(t)]
        out[slug] = sorted(rows, key=lambda x: x["gf"] - x["ga"], reverse=True)
    europe = [row(t, s) for s, teams in by_league.items() for t in teams if models.club.knows(t)]
    out["europa"] = sorted(europe, key=lambda x: x["gf"] - x["ga"], reverse=True)[:30]
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

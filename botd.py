"""Bets des Tages: jeden Tag um 10 Uhr fünf Tipps festlegen, auswerten und Bilanz führen.

- Auswahl: pro Spiel der beste Tipp (Value zuerst, sonst höchste Chance im Quotenbereich
  "ausgewogen"), nur Spiele mit verlässlicher Prognose, höchstens 2 pro Wettbewerb.
  Reicht der Zeitraum von 36 Stunden nicht für 5 Tipps, wird er schrittweise verlängert.
- Einmal festgelegt, ändern sich die 5 Tipps des Tages nicht mehr.
- Jeder Lauf wertet offene Tipps aus. Bilanz in Einheiten: Einsatz 1 pro Tipp.
- Nachträgliche Tage (vor dem Start) werden aus der Bilanz der nachträglichen Tipps gebildet.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config as C
from engine import top_options
from markets import outcome_hit
from sources.espn import DEAD, FINAL_90, parse_date

TZ = ZoneInfo("Europe/Zurich")
N_BETS = 5
MAX_PER_COMP = 2
WINDOWS = [36, 60, 96, 168]


def local_day(dt: datetime) -> str:
    return dt.astimezone(TZ).date().isoformat()


def _team(t: dict) -> dict:
    return {k: t.get(k, "") for k in ("id", "name", "tla", "logo")}


def _rank_key(o: dict):
    R = C.RISK["ausgewogen"]
    is_value = o.get("ev") is not None and o["ev"] >= R["min_ev"]
    return (1 if is_value else 0, o["ev"] if is_value else o["p"])


def select(upcoming: list[dict], now: datetime) -> list[dict]:
    """Fünf Tipps für heute aus den kommenden Spielen."""
    for hours in WINDOWS:
        cands = []
        for u in upcoming:
            ko = parse_date(u["kickoff"])
            if not u.get("known") or not (now + timedelta(minutes=30) < ko <= now + timedelta(hours=hours)):
                continue
            singles, _ = top_options(u["m"], u.get("odds") or {})
            with_odds = [s for s in singles if s.get("odds")]
            best = (with_odds or singles)[:1]
            if best:
                cands.append((u, best[0]))
        cands.sort(key=lambda x: _rank_key(x[1]), reverse=True)
        picked, per_comp = [], defaultdict(int)
        for u, o in cands:
            if per_comp[u["comp"]] >= MAX_PER_COMP:
                continue
            picked.append((u, o))
            per_comp[u["comp"]] += 1
            if len(picked) == N_BETS:
                break
        if len(picked) == N_BETS:
            break
        if hours == WINDOWS[-1]:   # auch 7 Tage reichen nicht: Wettbewerbs-Grenze lockern
            ids = {u["id"] for u, _ in picked}
            for u, o in cands:
                if u["id"] not in ids and len(picked) < N_BETS:
                    picked.append((u, o))
    picked.sort(key=lambda x: _rank_key(x[1]), reverse=True)
    return [{"id": u["id"], "kickoff": u["kickoff"], "comp": u["comp"],
             "home": _team(u["home"]), "away": _team(u["away"]),
             "key": o["key"], "p": o["p"], "odds": o.get("odds"),
             "fair": round(1 / o["p"], 2), "ev": o.get("ev"), "hit": None, "result": None}
            for u, o in picked]


def settle(days: list[dict], by_id: dict) -> None:
    for d in days:
        for b in d["bets"]:
            if b.get("hit") is not None or b.get("result") in ("void", "et"):
                continue
            e = by_id.get(b["id"])
            if not e:
                continue
            if e["status"] in DEAD:
                b["result"] = "void"
            elif e["completed"] and e["hs"] is not None:
                if e["status"] in FINAL_90:
                    b["result"] = [e["hs"], e["as"]]
                    b["hit"] = outcome_hit(b["key"], e["hs"], e["as"], e.get("fd"))
                else:
                    b["result"] = "et"   # Verlängerung: Wetten auf 90 Minuten nicht sicher auswertbar


def retro_days(history: list[dict], before: str, max_days: int = 150) -> list[dict]:
    """Nachträgliche Bets des Tages aus den nachträglichen Tipps (je Tag die 5 besten)."""
    by_day = defaultdict(list)
    for h in history:
        pk = h.get("pick")
        if not pk or not isinstance(h.get("result"), list) or not isinstance(pk.get("hit"), bool):
            continue
        day = local_day(parse_date(h["kickoff"]))
        if day >= before:
            continue
        by_day[day].append(h)
    out = []
    for day in sorted(by_day, reverse=True)[:max_days]:
        hs = sorted(by_day[day], key=lambda h: _rank_key(h["pick"]), reverse=True)
        picked, per_comp = [], defaultdict(int)
        for h in hs:
            if per_comp[h["comp"]] < MAX_PER_COMP:
                picked.append(h)
                per_comp[h["comp"]] += 1
            if len(picked) == N_BETS:
                break
        if len(picked) < 3:
            continue
        out.append({"day": day, "retro": True, "bets": [
            {"id": h["id"], "kickoff": h["kickoff"], "comp": h["comp"],
             "home": _team(h["home"]), "away": _team(h["away"]),
             "key": h["pick"]["key"], "p": h["pick"]["p"], "odds": h["pick"].get("odds"),
             "fair": round(1 / h["pick"]["p"], 2), "ev": h["pick"].get("ev"),
             "hit": h["pick"]["hit"], "result": h["result"]} for h in picked]})
    return out


def stats(days: list[dict]) -> dict:
    """Trefferquote über alle Tipps; Gewinn nur über Tipps mit echter Marktquote (Einsatz 1)."""
    n = hits = 0
    staked = ret = 0.0
    all_five = days_done = 0
    for d in days:
        done = [b for b in d["bets"] if isinstance(b.get("hit"), bool)]
        for b in done:
            n += 1
            hits += b["hit"]
            if b.get("odds"):
                staked += 1
                ret += b["odds"] if b["hit"] else 0
        if done and len(done) == len(d["bets"]):
            days_done += 1
            all_five += all(b["hit"] for b in done)
    profit = ret - staked
    return {"bets": n, "hits": hits, "with_odds": int(staked), "profit": round(profit, 2),
            "roi": round(profit / staked, 4) if staked else None,
            "days": days_done, "perfect_days": all_five}


def update(state: dict | None, upcoming: list[dict], history: list[dict], by_id: dict,
           now: datetime, create: bool) -> tuple[dict, dict | None]:
    """Gibt (Zustand, heutiger Tag falls neu erstellt) zurück."""
    state = state or {"days": []}
    live = [d for d in state.get("days", []) if not d.get("retro")]
    today = local_day(now)
    new_day = None
    if create and not any(d["day"] == today for d in live):
        bets = select(upcoming, now)
        if bets:
            new_day = {"day": today, "created": now.isoformat(), "bets": bets}
            live.append(new_day)
    settle(live, by_id)
    live.sort(key=lambda d: d["day"], reverse=True)
    first_live = live[-1]["day"] if live else today
    retro = retro_days(history, before=first_live)
    days = live + retro
    return {"days": days, "stats_live": stats(live), "stats_retro": stats(retro),
            "stats_all": stats(days), "updated": now.isoformat()}, new_day

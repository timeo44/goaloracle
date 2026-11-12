"""Challenge: von 100 CHF auf 100'000 CHF.

- Immer genau eine Wette offen, nie mehrere gleichzeitig. Ist eine Wette abgerechnet,
  darf am selben Tag die nächste folgen.
- Gewinn wird komplett weiter eingesetzt (100 → 140 → 196 …).
- Eine verlorene Wette beendet den Versuch. Der nächste Versuch startet wieder mit 100 CHF.
- Jede Wette soll den Betrag etwa verdoppeln: Gesamtquote 1.85 bis 2.30. Gewählt wird
  die sicherste solche Wette (höchste Chance): Einzeltipp, 2er- oder 3er-Kombi mit echter Marktquote.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from itertools import combinations

from markets import outcome_hit
from sources.espn import DEAD, FINAL_90, parse_date

START = 100.0
GOAL = 100_000.0
MIN_ODDS = 1.85          # etwa verdoppeln: rund 10 Siege bis zum Ziel
MAX_ODDS = 2.30
MIN_P = 0.40
HOURS = 30               # nur Spiele, die bald abgerechnet sind


def _ok_key(k: str) -> bool:
    return k in ("1", "X", "2") or (k[0] in "OU" and k.endswith(".5"))


def _legs(upcoming, now):
    out = []
    for u in upcoming:
        if not u.get("odds") or not u.get("known"):
            continue
        ko = parse_date(u["kickoff"])
        if not (now + timedelta(minutes=20) < ko <= now + timedelta(hours=HOURS)):
            continue
        for k, o in u["odds"].items():
            p = u["m"].get(k)
            if p is None or not _ok_key(k) or o < 1.03 or p * o < 0.9:
                continue
            out.append({"id": u["id"], "kickoff": u["kickoff"], "comp": u["comp"],
                        "home": u["home"]["name"], "away": u["away"]["name"],
                        "key": k, "p": round(p, 3), "odds": round(o, 2)})
    return out


def pick(upcoming, now) -> dict | None:
    """Sicherste Wette: höchste Chance bei Gesamtquote 1.25–1.60."""
    legs = _legs(upcoming, now)
    cands = [[l] for l in legs if MIN_ODDS <= l["odds"] <= MAX_ODDS]
    strong = sorted([l for l in legs if l["p"] >= 0.60], key=lambda l: -l["p"])[:14]
    for n in (2, 3):
        for c in combinations(strong, n):
            if len({l["id"] for l in c}) == n and MIN_ODDS <= math.prod(l["odds"] for l in c) <= MAX_ODDS:
                cands.append(list(c))
    best = None
    for c in cands:
        p = math.prod(l["p"] for l in c)
        o = math.prod(l["odds"] for l in c)
        if p < MIN_P:
            continue
        key = (round(p, 3), o)
        if best is None or key > best[0]:
            best = (key, c, p, o)
    if not best:
        return None
    _, legs, p, o = best
    return {"legs": [dict(l, status="open") for l in legs], "p": round(p, 3), "odds": round(o, 2)}


def _settle_leg(leg, e):
    if not e:
        return
    if e["status"] in DEAD or (e["completed"] and e["status"] not in FINAL_90):
        leg["status"] = "void"
    elif e["completed"] and e["hs"] is not None:
        leg["status"] = "won" if outcome_hit(leg["key"], e["hs"], e["as"]) else "lost"
        leg["result"] = [e["hs"], e["as"]]


def _new_attempt(state, now):
    state["attempts"].append({"n": len(state["attempts"]) + 1, "started": now.isoformat(), "ended": None,
                              "result": "open", "bank": START, "peak": START, "bets": []})


def update(state: dict | None, upcoming, by_id, now: datetime) -> tuple[dict, list[str]]:
    """Wertet die offene Wette aus und setzt bei Bedarf die nächste. Gibt (Zustand, Ereignisse) zurück."""
    state = state or {"start": START, "goal": GOAL, "since": now.isoformat(), "attempts": []}
    events = []
    if not state["attempts"]:
        _new_attempt(state, now)
    for _ in range(3):   # pro Lauf: abrechnen, dann ggf. neue Wette
        att = state["attempts"][-1]
        bet = att["bets"][-1] if att["bets"] else None
        if bet and bet["status"] == "open":
            for leg in bet["legs"]:
                if leg["status"] == "open":
                    _settle_leg(leg, by_id.get(leg["id"]))
            st = [l["status"] for l in bet["legs"]]
            if "lost" in st:
                bet["status"], bet["payout"] = "lost", 0.0
            elif "open" not in st:
                q = math.prod(l["odds"] for l in bet["legs"] if l["status"] == "won")
                bet["status"] = "void" if all(s == "void" for s in st) else "won"
                bet["payout"] = round(bet["stake"] * q, 2)
            else:
                break   # läuft noch: nichts Neues setzen
            bet["settled"] = now.isoformat()
            if bet["status"] == "lost":
                att.update(result="lost", ended=now.isoformat(), bank=0.0)
                events.append(("lost", att, bet))
                _new_attempt(state, now)
                continue
            att["bank"] = bet["payout"]
            att["peak"] = max(att["peak"], att["bank"])
            events.append((bet["status"], att, bet))
            if att["bank"] >= GOAL:
                att.update(result="won", ended=now.isoformat())
                events.append(("goal", att, bet))
                _new_attempt(state, now)
            continue
        # keine offene Wette: die nächste setzen
        choice = pick(upcoming, now)
        if choice:
            nb = {"placed": now.isoformat(), "stake": att["bank"], "status": "open", "payout": None,
                  "kickoff": max(l["kickoff"] for l in choice["legs"]), **choice}
            att["bets"].append(nb)
            events.append(("placed", att, nb))
        break
    done = [a for a in state["attempts"] if a["result"] != "open"]
    state["stats"] = {
        "attempts": len(state["attempts"]),
        "best_peak": max([a["peak"] for a in state["attempts"]], default=START),
        "best_wins": max([sum(b["status"] == "won" for b in a["bets"]) for a in state["attempts"]], default=0),
        "goals": sum(a["result"] == "won" for a in done),
        "bets": sum(len([b for b in a["bets"] if b["status"] in ("won", "lost")]) for a in state["attempts"]),
        "won": sum(sum(b["status"] == "won" for b in a["bets"]) for a in state["attempts"]),
    }
    state["updated"] = now.isoformat()
    return state, events

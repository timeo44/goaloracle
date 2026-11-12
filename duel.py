"""Export im gemeinsamen Vergleichsformat «tippduell/1» (web/duel.json).

Das Format ist bewusst einfach, damit auch ein anderer Bot es liefern kann.
Beschreibung und Beispiel: docs/tippduell-format.md
"""
from __future__ import annotations

import config as C

FORMAT = "tippduell/1"
MAP = {"BTTS": "BTTS_YES", "NOBTTS": "BTTS_NO", "HS": "HOME_SCORES", "AS": "AWAY_SCORES",
       "HO1.5": "HOME_O1.5", "AO1.5": "AWAY_O1.5"}


def pick_code(key: str) -> str:
    if "+" in key:
        return "+".join(pick_code(k) for k in key.split("+"))
    if key in ("1", "X", "2", "1X", "X2", "12"):
        return key
    if key in MAP:
        return MAP[key]
    if key.startswith("CS"):
        return "CS_" + key[2:]
    if key[0] in "OU" and key[1:2].isdigit():
        return key
    return "OTHER"


def comp_name(slug: str) -> str:
    if slug in C.DISPLAY:
        return C.DISPLAY[slug][0]
    return C.OTHER_NAMES.get(slug, slug)


def _status(hit, result) -> str:
    if result in ("void", "et"):
        return "void"
    return "won" if hit is True else "lost" if hit is False else "open"


def _score(result):
    return f"{result[0]}:{result[1]}" if isinstance(result, list) else None


def export(botd_state: dict, chal: dict | None, label, site: str, now) -> dict:
    tips = []
    for d in botd_state.get("days", []):
        for i, b in enumerate(d["bets"]):
            h, a = b["home"]["name"], b["away"]["name"]
            tips.append({
                "id": f"{d['day']}-{b['id']}-{b['key']}",
                "day": d["day"], "rank": i + 1,
                "placed": d.get("created") or d["day"] + "T10:00:00+01:00",
                "kickoff": b["kickoff"], "competition": comp_name(b["comp"]),
                "home": h, "away": a,
                "pick": pick_code(b["key"]), "label": label(b["key"], h, a),
                "odds": b.get("odds") or b.get("fair"), "odds_type": "market" if b.get("odds") else "fair",
                "probability": b["p"],
                "status": _status(b.get("hit"), b.get("result")), "score": _score(b.get("result")),
                "retro": bool(d.get("retro")),
            })
    challenge = None
    if chal and chal.get("attempts"):
        attempts = []
        for att in chal["attempts"]:
            bets = []
            for bt in att["bets"]:
                bets.append({
                    "placed": bt["placed"], "stake": bt["stake"], "odds": bt["odds"], "probability": bt["p"],
                    "status": bt["status"], "payout": bt.get("payout"),
                    "legs": [{"kickoff": l["kickoff"], "competition": comp_name(l["comp"]),
                              "home": l["home"], "away": l["away"], "pick": pick_code(l["key"]),
                              "label": label(l["key"], l["home"], l["away"]), "odds": l["odds"],
                              "status": l["status"], "score": _score(l.get("result")),
                              "home_logo": l.get("home_logo"), "away_logo": l.get("away_logo"),
                              "espn": {"league": l["comp"], "event": l["id"]}} for l in bt["legs"]],
                })
            attempts.append({"n": att["n"], "started": att["started"], "ended": att["ended"],
                             "status": att["result"], "bank": att["bank"], "peak": att["peak"], "bets": bets})
        challenge = {"start": chal["start"], "goal": chal["goal"], "currency": "CHF", "attempts": attempts}
    return {"format": FORMAT, "updated": now.isoformat(),
            "bot": {"name": "GoalOracle", "owner": "Timeo", "url": site or None},
            "tips": tips, "challenge": challenge}

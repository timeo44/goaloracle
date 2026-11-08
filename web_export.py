"""Schreibt die Daten für die Web-App (web/data.json).

Die Datei enthält auch die Bilanz: Jeder Tipp wird vor dem Spiel gespeichert
und nach dem Spiel mit dem echten Resultat verglichen.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from model import DixonColes, Match

HISTORY_MAX = 400


def match_id(m: Match) -> str:
    return f"{m.date:%Y%m%d}-{m.home}-{m.away}".replace(" ", "_")


def confidence(p: float) -> str:
    return "hoch" if p >= 0.60 else "mittel" if p >= 0.45 else "tief"


def form(team: str, played: list[Match], n: int = 5) -> str:
    games = sorted((m for m in played if team in (m.home, m.away)), key=lambda m: m.date)[-n:]
    out = ""
    for m in games:
        gf, ga = (m.hg, m.ag) if m.home == team else (m.ag, m.hg)
        out += "S" if gf > ga else "U" if gf == ga else "N"
    return out


def _r(x: float, d: int = 3) -> float:
    return round(float(x), d)


def build_data(model: DixonColes, matches: list[Match], names: dict[str, str],
               tlas: dict[str, str], now: datetime, days_ahead: int,
               previous: dict | None = None) -> dict:
    played = [m for m in matches if m.hg is not None]
    upcoming = sorted((m for m in matches if m.hg is None
                       and now <= m.date <= now + timedelta(days=days_ahead)),
                      key=lambda m: m.date)
    team = lambda k: {"key": k, "name": names.get(k, k.title()), "tla": tlas.get(k, k[:3].upper())}

    tips = []
    for m in upcoming:
        p = model.predict(m.home, m.away)
        hs, as_, ps = p.best_score()
        th, ta, pt = p.best_score(restrict_to_tip=True)
        tips.append({
            "id": match_id(m), "kickoff": m.date.isoformat(),
            "home": team(m.home), "away": team(m.away),
            "p": [_r(p.p_home), _r(p.p_draw), _r(p.p_away)],
            "tip": p.tip, "confidence": confidence(p.tip_prob),
            "score": [hs, as_, _r(ps)], "score_tip": [th, ta, _r(pt)],
            "xg": [_r(p.xg_home, 2), _r(p.xg_away, 2)],
            "over25": _r(p.p_over25), "btts": _r(p.p_btts),
            "grid": [[_r(v, 4) for v in row[:6]] for row in p.matrix[:6]],
        })

    current = set(names)
    table = [{"team": team(t), "gf": _r(gf, 2), "ga": _r(ga, 2), "form": form(t, played)}
             for t, gf, ga in model.ratings() if t in current]

    # ---- Bilanz fortschreiben ----
    history = {h["id"]: h for h in (previous or {}).get("history", [])}
    for t in tips:  # letzter Tipp vor Anpfiff zählt
        history[t["id"]] = {"id": t["id"], "kickoff": t["kickoff"],
                            "home": t["home"], "away": t["away"], "p": t["p"],
                            "tip": t["tip"], "score": t["score"][:2], "result": None}
    results = {match_id(m): (m.hg, m.ag) for m in played}
    for h in history.values():
        if h["result"] is None and h["id"] in results:
            h["result"] = list(results[h["id"]])
    # verschobene Spiele ohne Resultat nach 5 Tagen verwerfen
    keep = [h for h in history.values()
            if h["result"] is not None or datetime.fromisoformat(h["kickoff"]) > now - timedelta(days=5)]
    keep.sort(key=lambda h: h["kickoff"], reverse=True)

    return {
        "generated": now.isoformat(),
        "days_ahead": days_ahead,
        "model": {"home_adv": _r(2.718281828 ** model.home_adv, 2), "matches": len(played)},
        "tips": tips,
        "table": table,
        "history": keep[:HISTORY_MAX],
    }


def write_data(path: str, **kwargs) -> dict:
    p = Path(path)
    previous = None
    if p.exists():
        try:
            previous = json.loads(p.read_text())
        except json.JSONDecodeError:
            previous = None
    data = build_data(previous=previous, **kwargs)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return data

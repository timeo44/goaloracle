"""Aktuelle Marktquoten von The Odds API (Gratis-Plan: 500 Credits pro Monat).

Eine Abfrage mit den Märkten 1X2 + Über/Unter in der Region EU kostet 2 Credits.
Darum werden nur Wettbewerbe abgefragt, die in den nächsten Tagen Spiele haben,
und unter einem Restguthaben von ODDS_MIN_CREDITS wird nichts mehr abgefragt.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import requests

BASE = "https://api.the-odds-api.com/v4"


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def fetch(key: str, wanted: dict[str, list[str]], upcoming: list[dict], now: datetime,
          days: int, min_credits: int, log=print) -> tuple[dict[str, dict], int | None]:
    """Gibt ({espn_event_id: {markt: quote}}, Restguthaben) zurück."""
    try:
        r = requests.get(f"{BASE}/sports", params={"apiKey": key}, timeout=30)
        r.raise_for_status()
        active = {s["key"] for s in r.json() if s.get("active")}
    except (requests.RequestException, ValueError) as e:
        log(f"Odds API nicht erreichbar: {e}")
        return {}, None

    soon = [e for e in upcoming if e["dt"] <= now + timedelta(days=days)]
    slugs = sorted({e["slug"] for e in soon})
    odds, remaining = {}, None
    for slug in slugs:
        sport = next((k for k in wanted.get(slug, []) if k in active), None)
        if not sport:
            continue
        if remaining is not None and remaining < min_credits:
            log(f"Odds API: nur noch {remaining} Credits – keine weiteren Abfragen")
            break
        try:
            r = requests.get(f"{BASE}/sports/{sport}/odds", timeout=30, params={
                "apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"})
            remaining = int(float(r.headers.get("x-requests-remaining", remaining or 0)))
            if r.status_code != 200:
                log(f"Odds API {sport}: HTTP {r.status_code}")
                continue
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log(f"Odds API {sport}: {e}")
            continue

        ours = [e for e in soon if e["slug"] == slug]
        for ev in data:
            t = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            best, best_s = None, 0.0
            for e in ours:
                if abs((e["dt"] - t).total_seconds()) > 3 * 3600:
                    continue
                s = max(_sim(ev["home_team"], e["home"]["full"]), _sim(ev["home_team"], e["home"]["name"])) + \
                    max(_sim(ev["away_team"], e["away"]["full"]), _sim(ev["away_team"], e["away"]["name"]))
                if s > best_s:
                    best, best_s = e, s
            if best is None or best_s < 1.0:
                continue
            prices = {}
            for bm in ev.get("bookmakers", []):
                for mk in bm.get("markets", []):
                    for o in mk.get("outcomes", []):
                        if mk["key"] == "h2h":
                            k = "1" if o["name"] == ev["home_team"] else "2" if o["name"] == ev["away_team"] else "X"
                        elif mk["key"] == "totals" and o.get("point") is not None:
                            k = ("O" if o["name"].lower() == "over" else "U") + f"{float(o['point']):g}"
                            if "." not in k:
                                continue  # nur halbe Linien (2.5 usw.)
                        else:
                            continue
                        prices.setdefault(k, []).append(float(o["price"]))
            odds[best["id"]] = {k: round(statistics.median(v), 3) for k, v in prices.items() if len(v) >= 2}
    log(f"Odds API: Quoten für {len(odds)} Spiele, Restguthaben {remaining}")
    return odds, remaining

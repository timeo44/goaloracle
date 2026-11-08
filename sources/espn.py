"""Resultate und Spielpläne von ESPN (öffentliche, inoffizielle Schnittstelle).

Abfrage pro Wettbewerb und Monat. Abgeschlossene Monate werden im Ordner
cache/espn/ gespeichert und nie wieder geladen, so braucht ein täglicher Lauf
nur wenige Abfragen.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; goaloracle/2.0)"}
CACHE = Path(__file__).resolve().parents[1] / "cache" / "espn"

FINAL_90 = {"STATUS_FULL_TIME", "STATUS_FINAL"}           # nach 90 Minuten entschieden
FINAL_ET = {"STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_END_OF_EXTRATIME",
            "STATUS_FINAL_ET", "STATUS_SHOOTOUT"}
DEAD = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_FORFEIT"}


def _compact(ev: dict, slug: str) -> dict | None:
    try:
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        h, a = teams["home"], teams["away"]
    except (KeyError, IndexError):
        return None
    st = ev.get("status", {}).get("type", {})

    def team(c):
        t = c.get("team", {})
        return {"id": str(t.get("id")), "name": t.get("shortDisplayName") or t.get("displayName") or "?",
                "full": t.get("displayName") or "", "tla": (t.get("abbreviation") or "")[:4].upper(),
                "logo": t.get("logo") or ""}

    def score(c):
        try:
            return int(float(c.get("score")))
        except (TypeError, ValueError):
            return None

    return {
        "id": str(ev.get("id")), "slug": slug, "date": ev.get("date"),
        "home": team(h), "away": team(a),
        "hs": score(h), "as": score(a),
        "status": st.get("name", ""), "completed": bool(st.get("completed")),
        "neutral": bool(comp.get("neutralSite", False)),
    }


def _fetch_month(slug: str, ym: str, retries: int = 3) -> list[dict] | None:
    for attempt in range(retries):
        try:
            r = requests.get(URL.format(slug=slug), params={"dates": ym, "limit": 1000},
                             headers=HEADERS, timeout=30)
            if r.status_code == 200:
                out = []
                for ev in r.json().get("events", []):
                    c = _compact(ev, slug)
                    if c:
                        out.append(c)
                return out
            if r.status_code in (400, 404):
                return []  # Wettbewerb/Monat existiert nicht: leer merken
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _months(start: tuple[int, int], end: datetime) -> list[str]:
    y, m = start
    out = []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _dead_slug(slug: str) -> bool:
    """True, wenn ESPN für diesen Wettbewerb in keinem gespeicherten Monat Spiele hatte."""
    files = list(CACHE.glob(f"{slug}_*.json"))
    return len(files) >= 6 and all(f.stat().st_size <= 2 for f in files)


def load(slugs: list[str], start: tuple[int, int], now: datetime, log=print) -> list[dict]:
    """Alle Spiele der Wettbewerbe ab start bis einen Monat nach heute."""
    CACHE.mkdir(parents=True, exist_ok=True)
    horizon = now + timedelta(days=32)
    jobs, events = [], []
    for slug in slugs:
        for ym in _months(start, horizon):
            f = CACHE / f"{slug}_{ym}.json"
            y, m = int(ym[:4]), int(ym[4:])
            month_end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
            final = month_end < now - timedelta(days=5)  # Monat sicher abgeschlossen
            if final and f.exists():
                events += json.loads(f.read_text())
            elif not final and _dead_slug(slug) and f.exists() and \
                    datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) > now - timedelta(days=7):
                continue   # Wettbewerb ohne Daten bei ESPN: nur wöchentlich neu prüfen
            else:
                jobs.append((slug, ym, f, final))

    def run(job):
        slug, ym, f, final = job
        return job, _fetch_month(slug, ym)

    missing = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (slug, ym, f, final), evs in pool.map(run, jobs):
            if evs is None:
                missing += 1
                if f.exists():           # Netzfehler: alten Stand nehmen
                    events += json.loads(f.read_text())
                continue
            events += evs
            f.write_text(json.dumps(evs, separators=(",", ":")))

    log(f"ESPN: {len(jobs)} Abfragen, {missing} ohne Daten, {len(events)} Spiele gesamt")

    seen, out = set(), []
    for e in events:            # Duplikate (Spiel in zwei Monaten) entfernen
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out


def parse_date(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    if len(s) == 22 and s[16] == "+":   # "2025-11-01T15:00+00:00" ohne Sekunden
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s)

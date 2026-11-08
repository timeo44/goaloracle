"""Datenquellen.

- Laufende Saison (Resultate + Spielplan): football-data.org API (gratis, Token nötig)
- Frühere Saisons (nur Resultate): football-data.co.uk CSV (gratis, ohne Token)

Der Gratis-Plan von football-data.org liefert nur die laufende Saison, darum
kommen die Vorsaisons aus der CSV-Quelle. Die Teamnamen der beiden Quellen
werden über canon() auf denselben Schlüssel gebracht.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

import requests

from model import Match

API_BASE = "https://api.football-data.org/v4"
CSV_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
HEADERS = {"User-Agent": "goaloracle/1.0"}

_DROP = {"fc", "afc", "city", "town", "united", "utd", "albion", "hotspur",
         "wanderers", "hove", "forest", "the", "and"}
_ALIAS = {"man": "manchester", "nottm": "nottingham", "wolves": "wolverhampton",
          "spurs": "tottenham", "bromwich": "brom", "queens": "qpr"}


def canon(name: str) -> str:
    """Einheitlicher Teamschlüssel, z. B. 'Man City' und 'Manchester City FC' -> 'manchester city'."""
    cleaned = name.lower().replace("'", "").replace("’", "").replace("&", " ")
    tokens = re.sub(r"[^a-z ]", " ", cleaned).split()
    tokens = [_ALIAS.get(t, t) for t in tokens]
    if tokens[:1] == ["qpr"]:
        return "qpr"
    core = [t for t in tokens if t not in _DROP] or tokens
    # Bei Manchester/Sheffield ist der Zusatz nötig, sonst wären zwei Clubs gleich
    if core in (["manchester"], ["sheffield"]):
        suffix = "city" if "city" in tokens else "united"
        core = core + [suffix]
    return " ".join(core)


def current_season(today: datetime) -> int:
    """Startjahr der laufenden Saison (Saison 2026/27 -> 2026)."""
    return today.year if today.month >= 7 else today.year - 1


def fetch_current_season(token: str, season: int) -> tuple[list[Match], dict[str, str]]:
    """Alle Spiele der Saison (gespielt + angesetzt) und Anzeigenamen je Schlüssel."""
    r = requests.get(f"{API_BASE}/competitions/PL/matches",
                     params={"season": season},
                     headers={**HEADERS, "X-Auth-Token": token}, timeout=30)
    if r.status_code == 403:
        raise RuntimeError("football-data.org: Zugriff verweigert – Token prüfen.")
    r.raise_for_status()

    matches, names = [], {}
    for m in r.json().get("matches", []):
        if m["status"] in ("CANCELLED", "SUSPENDED"):
            continue
        home, away = m["homeTeam"], m["awayTeam"]
        if not home.get("name") or not away.get("name"):
            continue
        hk, ak = canon(home["name"]), canon(away["name"])
        names[hk] = home.get("shortName") or home["name"]
        names[ak] = away.get("shortName") or away["name"]
        ft = (m.get("score") or {}).get("fullTime") or {}
        finished = m["status"] == "FINISHED" and ft.get("home") is not None
        matches.append(Match(
            date=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            home=hk, away=ak,
            hg=ft["home"] if finished else None,
            ag=ft["away"] if finished else None,
        ))
    return matches, names


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).replace(hour=15, tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def fetch_past_season(season: int) -> list[Match]:
    code = f"{season % 100:02d}{(season + 1) % 100:02d}"
    r = requests.get(CSV_URL.format(code=code), headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        d = _parse_date(row.get("Date", ""))
        if not d or not row.get("HomeTeam") or not row.get("FTHG"):
            continue
        try:
            out.append(Match(d, canon(row["HomeTeam"]), canon(row["AwayTeam"]),
                             int(float(row["FTHG"])), int(float(row["FTAG"]))))
        except ValueError:
            continue
    return out


def load_all(token: str, today: datetime, prev_seasons: int = 2):
    """Gibt (alle Spiele, Anzeigenamen, Warnungen) zurück."""
    season = current_season(today)
    matches, names = fetch_current_season(token, season)
    warnings = []
    for s in range(season - prev_seasons, season):
        try:
            matches += fetch_past_season(s)
        except Exception as e:  # Vorsaison fehlt: Bot läuft trotzdem weiter
            warnings.append(f"Saison {s}/{(s + 1) % 100:02d} nicht geladen ({e})")
    return matches, names, warnings

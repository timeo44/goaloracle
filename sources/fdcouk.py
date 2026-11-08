"""football-data.co.uk: historische Quoten, Ecken und Karten.

Die Teamnamen dort weichen von ESPN ab ("Man United" vs. "Manchester United").
Darum wird jedes Spiel über Liga + Datum + Resultat + Namensähnlichkeit einem
ESPN-Spiel zugeordnet. Das ist robust, auch wenn ein Name völlig anders heisst.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; goaloracle/2.0)"}
CACHE = Path(__file__).resolve().parents[1] / "cache" / "fdco"


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _date(s: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def fetch(codes: list[str], seasons: list[int], current: int, log=print) -> dict[str, list[dict]]:
    """Gibt {code: [Zeilen]} zurück. Abgeschlossene Saisons kommen aus dem Cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = defaultdict(list)
    for code in codes:
        for s in seasons:
            sc = season_code(s)
            f = CACHE / f"{code}_{sc}.csv"
            text = None
            if s < current and f.exists():
                text = f.read_text()
            else:
                try:
                    r = requests.get(URL.format(season=sc, code=code), headers=HEADERS, timeout=30)
                    if r.status_code == 200 and b"HomeTeam" in r.content[:500]:
                        text = r.content.decode("utf-8-sig", errors="replace")
                        f.write_text(text)
                except requests.RequestException:
                    pass
                if text is None and f.exists():
                    text = f.read_text()
            if not text:
                continue
            for row in csv.DictReader(io.StringIO(text)):
                d = _date(row.get("Date", ""))
                if not d or not row.get("HomeTeam") or row.get("FTHG") in (None, ""):
                    continue
                out[code].append({
                    "date": d, "home": row["HomeTeam"], "away": row["AwayTeam"],
                    "hg": int(float(row["FTHG"])), "ag": int(float(row["FTAG"])),
                    "hc": _num(row.get("HC")), "ac": _num(row.get("AC")),
                    "hy": _num(row.get("HY")), "ay": _num(row.get("AY")),
                    "o1": _num(row.get("AvgH")) or _num(row.get("B365H")),
                    "oX": _num(row.get("AvgD")) or _num(row.get("B365D")),
                    "o2": _num(row.get("AvgA")) or _num(row.get("B365A")),
                    "oO25": _num(row.get("Avg>2.5")) or _num(row.get("B365>2.5")),
                    "oU25": _num(row.get("Avg<2.5")) or _num(row.get("B365<2.5")),
                })
    log(f"football-data.co.uk: {sum(len(v) for v in out.values())} Spiele mit Quoten/Ecken")
    return out


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " ").replace("'", "")
    s = re.sub(r"\b(fc|cf|ac|afc|sc|sv|ssc|as|us|rc|cd|ud|sd|ca|club|calcio|de|la|vfb|vfl|tsg|1)\b", " ", s)
    s = s.replace("utd", "united").replace("man ", "manchester ").replace("nottm", "nottingham")
    return " ".join(re.sub(r"[^a-z ]", " ", s).split())


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    return SequenceMatcher(None, a, b).ratio()


def attach(rows_by_code: dict[str, list[dict]], events: list[dict], code_to_slug: dict[str, str]) -> int:
    """Hängt Quoten/Ecken/Karten an passende ESPN-Spiele (Feld 'fd'). Gibt Anzahl zurück."""
    by_slug_day = defaultdict(list)
    for e in events:
        if e["slug"] in code_to_slug.values() and e["hs"] is not None:
            d = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).date()
            by_slug_day[(e["slug"], d)].append(e)

    attached = 0
    for code, rows in rows_by_code.items():
        slug = code_to_slug[code]
        # 1. Runde: Namenszuordnung per Mehrheitsentscheid
        votes = defaultdict(Counter)
        cands_for = []
        for row in rows:
            cands = []
            for dd in (0, -1, 1):
                cands += by_slug_day.get((slug, row["date"] + timedelta(days=dd)), [])
            best, best_s = None, 0.0
            for e in cands:
                s = _sim(row["home"], e["home"]["full"] or e["home"]["name"]) + \
                    _sim(row["away"], e["away"]["full"] or e["away"]["name"])
                if e["hs"] == row["hg"] and e["as"] == row["ag"]:
                    s += 1.0
                if s > best_s:
                    best, best_s = e, s
            cands_for.append(cands)
            if best is not None and best_s >= 1.6:
                votes[row["home"]][best["home"]["id"]] += 1
                votes[row["away"]][best["away"]["id"]] += 1
        name_to_id = {n: c.most_common(1)[0][0] for n, c in votes.items()}
        # 2. Runde: Spiele über die gesicherten IDs verbinden
        for row, cands in zip(rows, cands_for):
            hid, aid = name_to_id.get(row["home"]), name_to_id.get(row["away"])
            for e in cands:
                if e["home"]["id"] == hid and e["away"]["id"] == aid:
                    e["fd"] = {k: row[k] for k in ("hc", "ac", "hy", "ay", "o1", "oX", "o2", "oO25", "oU25")}
                    attached += 1
                    break
    return attached

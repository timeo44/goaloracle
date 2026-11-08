"""Erzeugt tests/demo.json mit simulierten Daten (für Vorschau und Design-Tests).

python tests/make_demo.py
"""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import DixonColes, Match  # noqa: E402
from web_export import build_data  # noqa: E402

TEAMS = [  # Anzeigename, Kürzel, Angriff, Abwehr (simuliert)
    ("Arsenal", "ARS", .38, -.42), ("Man City", "MCI", .40, -.25), ("Liverpool", "LIV", .42, -.18),
    ("Chelsea", "CHE", .22, -.15), ("Newcastle", "NEW", .15, -.12), ("Aston Villa", "AVL", .12, -.05),
    ("Tottenham", "TOT", .18, .08), ("Brighton Hove", "BHA", .10, .02), ("Crystal Palace", "CRY", .02, -.08),
    ("Nottingham", "NOT", -.02, -.02), ("Bournemouth", "BOU", .06, .06), ("Brentford", "BRE", .05, .10),
    ("Fulham", "FUL", -.02, .05), ("Man United", "MUN", .05, .12), ("Everton", "EVE", -.15, -.01),
    ("West Ham", "WHU", -.08, .18), ("Wolverhampton", "WOL", -.20, .20), ("Leeds United", "LEE", -.18, .15),
    ("Sunderland", "SUN", -.25, .12), ("Burnley", "BUR", -.30, .28),
]


def schedule(keys, first_saturday, rounds, rng):
    """Rundenturnier nach Kreismethode, eine Runde pro Woche (Sa/So)."""
    out, ks = [], list(keys)
    n = len(ks)
    for r in range(rounds):
        base = first_saturday + timedelta(days=7 * r)
        k = r % (n - 1)
        rot = [ks[0]] + ks[1:][k:] + ks[1:][:k]
        for i in range(n // 2):
            h, a = rot[i], rot[n - 1 - i]
            if (r + i) % 2:
                h, a = a, h
            slot = [timedelta(hours=11, minutes=30), timedelta(hours=14), timedelta(hours=14),
                    timedelta(hours=14), timedelta(hours=16, minutes=30), timedelta(days=1, hours=13),
                    timedelta(days=1, hours=13), timedelta(days=1, hours=15, minutes=30),
                    timedelta(days=1, hours=13), timedelta(days=2, hours=20)][i]
            out.append(Match(base + slot, h, a))
    return out


def main():
    rng = np.random.default_rng(7)
    keys = [t[0].lower() for t in TEAMS]
    names = {t[0].lower(): t[0] for t in TEAMS}
    tlas = {t[0].lower(): t[1] for t in TEAMS}
    att = {t[0].lower(): t[2] for t in TEAMS}
    dfn = {t[0].lower(): t[3] for t in TEAMS}

    now = datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc)
    matches = schedule(keys, datetime(2025, 8, 16, tzinfo=timezone.utc), 38, rng)
    matches += schedule(keys, datetime(2026, 8, 22, tzinfo=timezone.utc), 16, rng)
    for m in matches:
        lam = np.exp(att[m.home] + dfn[m.away] + 0.27)
        mu = np.exp(att[m.away] + dfn[m.home])
        m.hg, m.ag = int(rng.poisson(lam)), int(rng.poisson(mu))

    # tägliche Läufe der letzten 4 Wochen simulieren, damit die Bilanz gefüllt ist
    data = None
    day = now - timedelta(days=28)
    while day <= now:
        view = copy.deepcopy(matches)
        for m in view:
            if m.date >= day:
                m.hg = m.ag = None
        model = DixonColes().fit(view, day)
        data = build_data(model, view, names, tlas, day, 10, data)
        day += timedelta(days=1)
    data["demo"] = True
    (ROOT / "tests" / "demo.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    done = [h for h in data["history"] if h["result"]]
    print(f"{len(data['tips'])} Tipps, {len(data['table'])} Teams, {len(done)} ausgewertete Tipps")


if __name__ == "__main__":
    main()

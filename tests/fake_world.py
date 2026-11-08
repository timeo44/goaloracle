"""Simulierte Fussballwelt im ESPN-Format für Offline-Tests der ganzen Pipeline.

python tests/fake_world.py   -> rechnet alles durch und schreibt nach tests/out/
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config as C  # noqa: E402

rng = np.random.default_rng(3)
NOW = datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc)
START = datetime(2024, 7, 15, tzinfo=timezone.utc)

leagues = {s: [] for s in C.TOP5 + ["ned.1", "por.1", "eng.2"]}
teams = {}
tid = 1000
for s in leagues:
    lvl = -0.35 if s == "eng.2" else (-0.15 if s in ("ned.1", "por.1") else 0)
    for i in range(18):
        tid += 1
        att, dfn = rng.normal(lvl, .28), rng.normal(-lvl, .22)
        teams[str(tid)] = {"id": str(tid), "name": f"{s[:3].upper()} Club {i + 1}", "full": f"{s} Club {i + 1}",
                           "tla": f"{s[0].upper()}{i + 1:02d}", "logo": "", "att": att, "dfn": dfn, "league": s}
        leagues[s].append(str(tid))
nations = []
for i in range(24):
    tid += 1
    teams[str(tid)] = {"id": str(tid), "name": f"Land {i + 1}", "full": f"Land {i + 1}", "tla": f"L{i + 1:02d}",
                       "logo": "", "att": rng.normal(0, .35), "dfn": rng.normal(0, .3), "league": "nat"}
    nations.append(str(tid))
amateurs = []
for i in range(12):
    tid += 1
    teams[str(tid)] = {"id": str(tid), "name": f"Amateur {i + 1}", "full": f"Amateur {i + 1}", "tla": f"A{i + 1:02d}",
                       "logo": "", "att": -1.0, "dfn": .9, "league": "ama"}
    amateurs.append(str(tid))

events, eid = [], 0


def game(slug, d, h, a, neutral=False):
    global eid
    eid += 1
    th, ta = teams[h], teams[a]
    lam = np.exp(th["att"] + ta["dfn"] + (0 if neutral else .25))
    mu = np.exp(ta["att"] + th["dfn"])
    done = d < NOW
    ev = {"id": str(eid), "slug": slug, "date": d.strftime("%Y-%m-%dT%H:%MZ"),
          "home": {k: th[k] for k in ("id", "name", "full", "tla", "logo")},
          "away": {k: ta[k] for k in ("id", "name", "full", "tla", "logo")},
          "hs": int(rng.poisson(lam)) if done else None, "as": int(rng.poisson(mu)) if done else None,
          "status": "STATUS_FULL_TIME" if done else "STATUS_SCHEDULED", "completed": done, "neutral": neutral}
    if done and slug in C.TOP5 + ["ned.1", "por.1", "eng.2"]:
        p1 = 1 / (1 + np.exp(-(lam - mu) * 1.3))
        ev["fd"] = {"hc": int(rng.poisson(5.3)), "ac": int(rng.poisson(4.4)), "hy": int(rng.poisson(1.8)),
                    "ay": int(rng.poisson(2.1)), "hst": int(rng.poisson(lam * 3.2)), "ast": int(rng.poisson(mu * 3.2)), "o1": round(0.93 / max(p1 * .75, .05), 2), "oX": 3.5,
                    "o2": round(0.93 / max((1 - p1) * .75, .05), 2), "oO25": 1.85, "oU25": 1.95}
    events.append(ev)


d = START
week = 0
while d < NOW + timedelta(days=30):
    sat = d + timedelta(days=(5 - d.weekday()) % 7)
    for s, ts in leagues.items():
        order = rng.permutation(ts)
        for i in range(0, len(order), 2):
            game(s, sat + timedelta(hours=14 + (i % 3) * 2, days=i % 2), order[i], order[i + 1])
    if d.month in (9, 10, 11, 12, 2, 3) and week % 2 == 0:
        top = [t for s in C.TOP5 for t in leagues[s][:6]] + leagues["ned.1"][:4] + leagues["por.1"][:4]
        mid = [t for s in C.TOP5 for t in leagues[s][6:10]] + leagues["ned.1"][4:8]
        for slug, pool, day in (("uefa.champions", top, 1), ("uefa.europa", mid, 3), ("uefa.europa.conf", mid[::-1], 3)):
            pick = rng.permutation(pool)[:16]
            for i in range(0, 16, 2):
                game(slug, sat + timedelta(days=day + 2, hours=20), pick[i], pick[i + 1])
    if week % 6 == 3:
        for slug, lg in (("eng.fa", "eng.1"), ("ger.dfb_pokal", "ger.1"), ("ita.coppa_italia", "ita.1"),
                         ("esp.copa_del_rey", "esp.1"), ("fra.coupe_de_france", "fra.1")):
            pool = rng.permutation(leagues[lg])[:4]
            for i, t in enumerate(pool):
                game(slug, sat + timedelta(days=3, hours=19), t, amateurs[(week + i) % 12] if i % 2 else leagues["eng.2"][i])
    if d.month in (9, 10, 11, 3, 6) and d.day <= 7:
        order = rng.permutation(nations)
        for i in range(0, 24, 2):
            game("uefa.nations" if d.month in (9, 10, 11) else "fifa.friendly", sat + timedelta(days=6, hours=19),
                 order[i], order[i + 1])
    d = sat + timedelta(days=7)
    week += 1

# kommende Nations-League-Runde in den Testzeitraum legen
for i in range(0, 12, 2):
    game("uefa.nations", NOW + timedelta(days=4, hours=12), nations[i], nations[i + 1])


def run():
    import bot
    out = ROOT / "tests" / "out"
    out.mkdir(exist_ok=True)

    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    with mock.patch.object(bot, "WEB", out), mock.patch.object(bot, "ROOT", out), \
            mock.patch.object(bot, "datetime", FixedDT), \
            mock.patch.object(bot.espn, "load", lambda *a, **k: events), \
            mock.patch.object(bot.fdcouk, "fetch", lambda *a, **k: {}), \
            mock.patch.object(bot.fdcouk, "attach", lambda *a, **k: 0), \
            mock.patch("engine.ROOT", out), \
            mock.patch.object(sys, "argv", ["bot.py", "--dry-run"]):
        bot.main()
    print(f"{len(events)} simulierte Spiele")


if __name__ == "__main__":
    run()

"""Offline-Test ohne Internet: simulierte Liga mit bekannten Stärken.

python tests/test_offline.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import backtest, build_report  # noqa: E402
from data import canon  # noqa: E402
from model import DixonColes, Match  # noqa: E402


def test_canon():
    pairs = [("Man City", "Manchester City FC"), ("Man United", "Manchester United FC"),
             ("Nott'm Forest", "Nottingham Forest FC"), ("Wolves", "Wolverhampton Wanderers FC"),
             ("Brighton", "Brighton & Hove Albion FC"), ("Tottenham", "Tottenham Hotspur FC"),
             ("West Ham", "West Ham United FC"), ("Newcastle", "Newcastle United FC"),
             ("Bournemouth", "AFC Bournemouth"), ("Leeds", "Leeds United FC"),
             ("Sunderland", "Sunderland AFC"), ("Sheffield United", "Sheffield United FC"),
             ("West Brom", "West Bromwich Albion FC"), ("Ipswich", "Ipswich Town FC")]
    for a, b in pairs:
        assert canon(a) == canon(b), (a, b, canon(a), canon(b))
    assert canon("Man City") != canon("Man United")
    print("canon ok")


def simulate(seed=1):
    rng = np.random.default_rng(seed)
    teams = [f"team {chr(97 + i)}" for i in range(20)]
    att = dict(zip(teams, rng.normal(0, 0.3, 20)))
    dfn = dict(zip(teams, rng.normal(0, 0.25, 20)))
    att = {t: v - np.mean(list(att.values())) for t, v in att.items()}
    start = datetime(2025, 8, 15, 14, tzinfo=timezone.utc)
    matches, k = [], 0
    for rnd in range(2):  # zwei Saisons Hin- und Rückrunde
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                d = start + timedelta(days=rnd * 365 + (k % 38) * 7 + k % 3)
                k += 1
                lam = np.exp(att[h] + dfn[a] + 0.25)
                mu = np.exp(att[a] + dfn[h])
                matches.append(Match(d, h, a, int(rng.poisson(lam)), int(rng.poisson(mu))))
    return teams, att, dfn, sorted(matches, key=lambda m: m.date)


def test_model_and_report():
    teams, att, dfn, matches = simulate()
    now = matches[-60].date  # die letzten 60 Spiele sind "Zukunft"
    for m in matches[-60:]:
        m.hg = m.ag = None
    model = DixonColes().fit(matches, now)

    corr_att = np.corrcoef([att[t] for t in teams], [model.att[t] for t in teams])[0, 1]
    corr_def = np.corrcoef([dfn[t] for t in teams], [model.dfn[t] for t in teams])[0, 1]
    print(f"Korrelation Angriff {corr_att:.2f}, Abwehr {corr_def:.2f}, "
          f"Heimvorteil {model.home_adv:.2f} (wahr 0.25), rho {model.rho:.3f}")
    assert corr_att > 0.7 and corr_def > 0.6

    p = model.predict(teams[0], teams[1])
    assert abs(p.p_home + p.p_draw + p.p_away - 1) < 1e-9
    names = {t: t.title() + (" & Co" if t == "team a" else "") for t in teams}
    report = build_report(model, matches, names, now, 10, ["Testwarnung"])
    assert "Tipp:" in report and "&amp;" in report
    print(report)
    return matches, now


def test_backtest(matches, now):
    played = [m for m in matches if m.hg is not None]
    print(backtest(played, now, 60, 0.0019))


if __name__ == "__main__":
    test_canon()
    ms, now = test_model_and_report()
    test_backtest(ms, now)
    print("\nAlle Tests ok.")

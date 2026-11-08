"""Dixon-Coles-Modell für Fussball-Resultate.

Jedes Team bekommt eine Angriffs- und eine Abwehrstärke. Dazu kommen ein
Heimvorteil und eine Korrektur (rho) für tiefe Resultate wie 0:0 und 1:1,
die ein reines Poisson-Modell unterschätzt. Neuere Spiele zählen mehr
(exponentielle Zeitgewichtung, Parameter xi).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


@dataclass
class Match:
    date: datetime
    home: str
    away: str
    hg: int | None = None
    ag: int | None = None


@dataclass
class Prediction:
    home: str
    away: str
    xg_home: float
    xg_away: float
    p_home: float
    p_draw: float
    p_away: float
    p_over25: float
    p_btts: float
    matrix: np.ndarray

    @property
    def tip(self) -> str:
        probs = {"1": self.p_home, "X": self.p_draw, "2": self.p_away}
        return max(probs, key=probs.get)

    @property
    def tip_prob(self) -> float:
        return max(self.p_home, self.p_draw, self.p_away)

    def best_score(self, restrict_to_tip: bool = False) -> tuple[int, int, float]:
        """Wahrscheinlichstes Endresultat (optional nur passend zum 1X2-Tipp)."""
        m = self.matrix.copy()
        if restrict_to_tip:
            g = np.arange(m.shape[0])
            diff = g[:, None] - g[None, :]
            mask = {"1": diff > 0, "X": diff == 0, "2": diff < 0}[self.tip]
            m = np.where(mask, m, -1)
        i, j = np.unravel_index(np.argmax(m), m.shape)
        return int(i), int(j), float(self.matrix[i, j])


class DixonColes:
    def __init__(self, xi: float = 0.0019, l2: float = 0.02, max_goals: int = 10):
        self.xi = xi            # Zeitgewichtung pro Tag (0.0019 ≈ Halbwertszeit ~1 Jahr)
        self.l2 = l2            # leichte Regularisierung, stabilisiert Aufsteiger
        self.max_goals = max_goals
        self.teams: list[str] = []
        self.att: dict[str, float] = {}
        self.dfn: dict[str, float] = {}   # positiv = schwächere Abwehr
        self.home_adv = 0.0
        self.rho = 0.0

    # ---------- Fit ----------
    def fit(self, matches: list[Match], ref_date: datetime) -> "DixonColes":
        played = [m for m in matches if m.hg is not None and m.date < ref_date]
        if len(played) < 30:
            raise ValueError(f"Zu wenige Spiele zum Trainieren ({len(played)}).")

        self.teams = sorted({m.home for m in played} | {m.away for m in played})
        idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)

        h = np.array([idx[m.home] for m in played])
        a = np.array([idx[m.away] for m in played])
        hg = np.array([m.hg for m in played], dtype=float)
        ag = np.array([m.ag for m in played], dtype=float)
        days = np.array([(ref_date - m.date).total_seconds() / 86400 for m in played])
        w = np.exp(-self.xi * days)

        m00 = (hg == 0) & (ag == 0)
        m01 = (hg == 0) & (ag == 1)
        m10 = (hg == 1) & (ag == 0)
        m11 = (hg == 1) & (ag == 1)

        def nll(p):
            att, dfn, home, rho = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1]
            lam = np.exp(att[h] + dfn[a] + home)
            mu = np.exp(att[a] + dfn[h])
            ll = hg * np.log(lam) - lam + ag * np.log(mu) - mu
            tau = np.ones_like(lam)
            tau[m00] = 1 - lam[m00] * mu[m00] * rho
            tau[m01] = 1 + lam[m01] * rho
            tau[m10] = 1 + mu[m10] * rho
            tau[m11] = 1 - rho
            ll = ll + np.log(np.clip(tau, 1e-10, None))
            penalty = self.l2 * (np.sum(att ** 2) + np.sum(dfn ** 2))
            penalty += 50.0 * np.sum(att) ** 2  # Identifizierbarkeit: Summe Angriff = 0
            return -np.sum(w * ll) + penalty

        x0 = np.concatenate([np.zeros(2 * n), [0.25, -0.05]])
        bounds = [(-3, 3)] * (2 * n) + [(-1, 1), (-0.3, 0.3)]
        res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 2000})
        p = res.x
        self.att = dict(zip(self.teams, p[:n]))
        self.dfn = dict(zip(self.teams, p[n:2 * n]))
        self.home_adv, self.rho = float(p[2 * n]), float(p[2 * n + 1])
        return self

    # ---------- Vorhersage ----------
    def _params(self, team: str) -> tuple[float, float]:
        if team in self.att:
            return self.att[team], self.dfn[team]
        # Unbekanntes Team (z. B. Aufsteiger ohne Daten): Schnitt der 3 schwächsten
        weakest = sorted(self.teams, key=lambda t: self.att[t] - self.dfn[t])[:3]
        return (float(np.mean([self.att[t] for t in weakest])),
                float(np.mean([self.dfn[t] for t in weakest])))

    def predict(self, home: str, away: str) -> Prediction:
        ah, dh = self._params(home)
        aa, da = self._params(away)
        lam = float(np.exp(ah + da + self.home_adv))
        mu = float(np.exp(aa + dh))

        g = np.arange(self.max_goals + 1)
        mat = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        mat[0, 0] *= 1 - lam * mu * self.rho
        mat[0, 1] *= 1 + lam * self.rho
        mat[1, 0] *= 1 + mu * self.rho
        mat[1, 1] *= 1 - self.rho
        mat = np.clip(mat, 0, None)
        mat /= mat.sum()

        total = g[:, None] + g[None, :]
        return Prediction(
            home=home, away=away, xg_home=lam, xg_away=mu,
            p_home=float(np.tril(mat, -1).sum()),
            p_draw=float(np.trace(mat)),
            p_away=float(np.triu(mat, 1).sum()),
            p_over25=float(mat[total >= 3].sum()),
            p_btts=float(mat[1:, 1:].sum()),
            matrix=mat,
        )

    def ratings(self) -> list[tuple[str, float, float]]:
        """(Team, erwartete Tore für, erwartete Tore gegen) gegen ein Durchschnittsteam."""
        mean_att = np.mean(list(self.att.values()))
        mean_dfn = np.mean(list(self.dfn.values()))
        out = []
        for t in self.teams:
            gf = float(np.exp(self.att[t] + mean_dfn + self.home_adv / 2))
            ga = float(np.exp(mean_att + self.dfn[t] + self.home_adv / 2))
            out.append((t, gf, ga))
        return sorted(out, key=lambda r: r[1] - r[2], reverse=True)

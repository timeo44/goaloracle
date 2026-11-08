"""Statistische Modelle.

DixonColes: Tore. Jedes Team hat Angriff und Abwehr, dazu Heimvorteil (nicht bei
neutralem Platz) und eine Korrektur rho für 0:0/1:0/0:1/1:1. Alle Wettbewerbe
werden gemeinsam gerechnet, so werden Teams aus verschiedenen Ligen über
Europacup- und Pokalspiele vergleichbar.

RateModel: Ecken oder Karten, gleiche Idee ohne rho.

Beide nutzen einen exakten Gradienten, damit auch 600+ Teams in Sekunden gehen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    neutral: bool = False
    comp: str = ""
    id: str = ""
    extra: dict = field(default_factory=dict)  # z. B. {"hc":5,"ac":3,"hy":2,"ay":1}


@dataclass
class Prediction:
    home: str
    away: str
    xg_home: float
    xg_away: float
    matrix: np.ndarray

    @property
    def p_home(self) -> float:
        return float(np.tril(self.matrix, -1).sum())

    @property
    def p_draw(self) -> float:
        return float(np.trace(self.matrix))

    @property
    def p_away(self) -> float:
        return float(np.triu(self.matrix, 1).sum())

    @property
    def tip(self) -> str:
        probs = {"1": self.p_home, "X": self.p_draw, "2": self.p_away}
        return max(probs, key=probs.get)

    @property
    def tip_prob(self) -> float:
        return max(self.p_home, self.p_draw, self.p_away)

    @property
    def p_over25(self) -> float:
        g = np.arange(self.matrix.shape[0])
        return float(self.matrix[(g[:, None] + g[None, :]) >= 3].sum())

    @property
    def p_btts(self) -> float:
        return float(self.matrix[1:, 1:].sum())

    def best_score(self, restrict_to_tip: bool = False) -> tuple[int, int, float]:
        m = self.matrix.copy()
        if restrict_to_tip:
            g = np.arange(m.shape[0])
            diff = g[:, None] - g[None, :]
            mask = {"1": diff > 0, "X": diff == 0, "2": diff < 0}[self.tip]
            m = np.where(mask, m, -1)
        i, j = np.unravel_index(np.argmax(m), m.shape)
        return int(i), int(j), float(self.matrix[i, j])


def _fit_poisson_pair(h, a, yh, ya, w, n, prior_att, prior_def, l2, use_tau, x0=None):
    """Gewichtete ML-Schätzung mit exaktem Gradienten. Gibt Parametervektor zurück."""
    m00 = (yh == 0) & (ya == 0)
    m01 = (yh == 0) & (ya == 1)
    m10 = (yh == 1) & (ya == 0)
    m11 = (yh == 1) & (ya == 1)
    hw = w  # Heimvorteil-Indikator steckt in hflag
    del hw

    def f(p, hflag):
        att, dfn, home = p[:n], p[n:2 * n], p[2 * n]
        rho = p[2 * n + 1] if use_tau else 0.0
        eta_l = att[h] + dfn[a] + home * hflag
        eta_m = att[a] + dfn[h]
        lam, mu = np.exp(eta_l), np.exp(eta_m)
        ll = yh * eta_l - lam + ya * eta_m - mu
        g_l = yh - lam          # d ll / d eta_l
        g_m = ya - mu
        g_rho = 0.0
        if use_tau:
            tau = np.ones_like(lam)
            dl = np.zeros_like(lam)  # d tau / d lam
            dm = np.zeros_like(lam)
            dr = np.zeros_like(lam)
            tau[m00] = 1 - lam[m00] * mu[m00] * rho
            dl[m00] = -mu[m00] * rho
            dm[m00] = -lam[m00] * rho
            dr[m00] = -lam[m00] * mu[m00]
            tau[m01] = 1 + lam[m01] * rho
            dl[m01] = rho
            dr[m01] = lam[m01]
            tau[m10] = 1 + mu[m10] * rho
            dm[m10] = rho
            dr[m10] = mu[m10]
            tau[m11] = 1 - rho
            dr[m11] = -1
            tau = np.clip(tau, 1e-10, None)
            ll = ll + np.log(tau)
            g_l = g_l + lam * dl / tau
            g_m = g_m + mu * dm / tau
            g_rho = -np.sum(w * dr / tau)

        da, dd = att - prior_att, dfn - prior_def
        obj = -np.sum(w * ll) + l2 * (np.sum(da ** 2) + np.sum(dd ** 2)) + 50.0 * np.mean(att) ** 2 * n

        wl, wm = w * g_l, w * g_m
        grad_att = -(np.bincount(h, wl, n) + np.bincount(a, wm, n)) + 2 * l2 * da + 100.0 * np.mean(att)
        grad_def = -(np.bincount(a, wl, n) + np.bincount(h, wm, n)) + 2 * l2 * dd
        grad_home = -np.sum(wl * hflag)
        grad = np.concatenate([grad_att, grad_def, [grad_home]] + ([[g_rho]] if use_tau else []))
        return obj, grad

    return f


class DixonColes:
    def __init__(self, xi: float = 0.0019, l2: float = 0.5, max_goals: int = 10,
                 use_tau: bool = True, weak_prior: float = 0.45):
        self.xi = xi                  # Zeitgewichtung pro Tag (Halbwertszeit ~1 Jahr)
        self.l2 = l2                  # Regularisierung: wenig Daten -> Richtung Vorwissen
        self.max_goals = max_goals
        self.use_tau = use_tau
        self.weak_prior = weak_prior  # Vorwissen für Teams ohne Ligaspiele (Amateure im Pokal)
        self.teams: list[str] = []
        self.att: dict[str, float] = {}
        self.dfn: dict[str, float] = {}
        self.home_adv = 0.0
        self.rho = 0.0
        self.n_matches = 0

    def fit(self, matches: list[Match], ref_date: datetime, key: tuple[str, str] = ("hg", "ag"),
            league_teams: set[str] | None = None, warm: "DixonColes | None" = None) -> "DixonColes":
        played = []
        for m in matches:
            yh = getattr(m, key[0], None) if key[0] in ("hg", "ag") else m.extra.get(key[0])
            ya = getattr(m, key[1], None) if key[1] in ("hg", "ag") else m.extra.get(key[1])
            if yh is not None and ya is not None and m.date < ref_date:
                played.append((m, yh, ya))
        if len(played) < 30:
            raise ValueError(f"Zu wenige Spiele zum Trainieren ({len(played)}).")
        self.n_matches = len(played)

        self.teams = sorted({m.home for m, _, _ in played} | {m.away for m, _, _ in played})
        idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        h = np.array([idx[m.home] for m, _, _ in played])
        a = np.array([idx[m.away] for m, _, _ in played])
        yh = np.array([y for _, y, _ in played], dtype=float)
        ya = np.array([y for _, _, y in played], dtype=float)
        hflag = np.array([0.0 if m.neutral else 1.0 for m, _, _ in played])
        days = np.array([(ref_date - m.date).total_seconds() / 86400 for m, _, _ in played])
        w = np.exp(-self.xi * days)

        # Vorwissen: Teams, die nur in Pokalen auftauchen, gelten erstmal als schwach
        prior_att = np.zeros(n)
        prior_def = np.zeros(n)
        if league_teams is not None:
            for t, i in idx.items():
                if t not in league_teams:
                    prior_att[i], prior_def[i] = -self.weak_prior, self.weak_prior

        f = _fit_poisson_pair(h, a, yh, ya, w, n, prior_att, prior_def, self.l2, self.use_tau)
        x0 = np.concatenate([prior_att, prior_def, [0.25]] + ([[-0.05]] if self.use_tau else []))
        if warm is not None:
            for t, i in idx.items():
                if t in warm.att:
                    x0[i], x0[n + i] = warm.att[t], warm.dfn[t]
            x0[2 * n] = warm.home_adv
            if self.use_tau:
                x0[2 * n + 1] = warm.rho
        # mittlere Torrate als Startwert für die Grundhöhe
        base = np.log(max(1e-3, (yh.mean() + ya.mean()) / 2))
        if warm is None:
            x0[:n] += base / 2
            x0[n:2 * n] += base / 2

        bounds = [(-4, 4)] * (2 * n) + [(-1, 1)] + ([(-0.3, 0.3)] if self.use_tau else [])
        res = minimize(lambda p: f(p, hflag), x0, jac=True, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 3000})
        p = res.x
        recent = days < 400
        cnt = np.bincount(h[recent], minlength=n) + np.bincount(a[recent], minlength=n)
        self.games = dict(zip(self.teams, cnt.tolist()))   # Spiele im letzten Jahr
        self.att = dict(zip(self.teams, p[:n]))
        self.dfn = dict(zip(self.teams, p[n:2 * n]))
        self.home_adv = float(p[2 * n])
        self.rho = float(p[2 * n + 1]) if self.use_tau else 0.0
        return self

    # ---------- Vorhersage ----------
    def knows(self, team: str, min_games: int = 0) -> bool:
        return team in self.att and getattr(self, "games", {}).get(team, 0) >= min_games

    def _params(self, team: str) -> tuple[float, float]:
        if team in self.att:
            return self.att[team], self.dfn[team]
        mean_a = float(np.mean(list(self.att.values())))
        mean_d = float(np.mean(list(self.dfn.values())))
        return mean_a - self.weak_prior, mean_d + self.weak_prior

    def rates(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        ah, dh = self._params(home)
        aa, da = self._params(away)
        lam = float(np.exp(ah + da + (0.0 if neutral else self.home_adv)))
        mu = float(np.exp(aa + dh))
        return lam, mu

    def predict(self, home: str, away: str, neutral: bool = False) -> Prediction:
        lam, mu = self.rates(home, away, neutral)
        g = np.arange(self.max_goals + 1)
        mat = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        if self.use_tau:
            mat[0, 0] *= 1 - lam * mu * self.rho
            mat[0, 1] *= 1 + lam * self.rho
            mat[1, 0] *= 1 + mu * self.rho
            mat[1, 1] *= 1 - self.rho
        mat = np.clip(mat, 0, None)
        mat /= mat.sum()
        return Prediction(home, away, lam, mu, mat)

    def ratings(self, teams: list[str] | None = None) -> list[tuple[str, float, float]]:
        """(Team, erwartete Tore für, gegen) gegen ein Durchschnittsteam der Auswahl."""
        teams = [t for t in (teams or self.teams) if t in self.att]
        if not teams:
            return []
        mean_att = np.mean([self.att[t] for t in teams])
        mean_dfn = np.mean([self.dfn[t] for t in teams])
        out = []
        for t in teams:
            gf = float(np.exp(self.att[t] + mean_dfn + self.home_adv / 2))
            ga = float(np.exp(mean_att + self.dfn[t] + self.home_adv / 2))
            out.append((t, gf, ga))
        return sorted(out, key=lambda r: r[1] - r[2], reverse=True)


class RateModel(DixonColes):
    """Ecken oder Karten: Poisson pro Team ohne Tief-Resultat-Korrektur."""

    def __init__(self, **kw):
        kw.setdefault("use_tau", False)
        kw.setdefault("l2", 2.0)
        kw.setdefault("weak_prior", 0.0)
        super().__init__(**kw)

"""Predictor: bündelt alle Modelle zu einer Prognose pro Spiel.

1. Tor-Modell (Dixon-Coles) in zwei Stufen: zuerst ohne Vorwissen, dann mit dem
   Niveau der eigenen Liga als Vorwissen. So starten Aufsteiger und Teams mit
   wenig Daten realistisch.
2. Schuss-Modell: Schüsse aufs Tor pro Team (football-data.co.uk), umgerechnet
   in Tore. Wird geometrisch mit dem Tor-Modell gemischt (Anteil beta).
3. Nationalteams: eigenes Tor-Modell.
4. Ecken und Karten: eigene Zählmodelle.
5. Markt-Kalibrierung: Wenn Quoten da sind, werden Modell- und Markt-
   Wahrscheinlichkeiten gemischt (Anteil w fürs Modell) und die Torraten so
   angepasst, dass die Resultat-Matrix dazu passt. Alle Märkte bleiben stimmig.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize

import config as C
from model import DixonColes, Match, Prediction, RateModel, score_matrix
from sources.espn import FINAL_90, parse_date

NATION_SLUGS = {s for s, v in C.DISPLAY.items() if v[2] == "nation"} | set(C.TRAIN_NATION)
EXTRA_KEYS = ("hc", "ac", "hy", "ay", "hst", "ast")


@dataclass
class Params:
    xi: float = 0.0019    # Zeitgewichtung pro Tag
    beta: float = 0.35    # Anteil Schuss-Modell an den Torraten (Clubs)
    w: float = 0.5        # Anteil Modell beim Mix mit Marktquoten (1X2)
    w_ou: float = 0.5     # dasselbe für Über/Unter
    tuned_at: str | None = None
    metrics: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Params":
        if not d:
            return cls()
        return cls(**{k: d[k] for k in ("xi", "beta", "w", "w_ou", "tuned_at", "metrics") if k in d})

    def to_dict(self) -> dict:
        return {"xi": self.xi, "beta": self.beta, "w": self.w, "w_ou": self.w_ou,
                "tuned_at": self.tuned_at, "metrics": self.metrics}


def to_matches(events: list[dict]) -> list[Match]:
    out = []
    for e in events:
        if not e["completed"] or e["hs"] is None or e["status"] not in FINAL_90:
            continue
        fd = e.get("fd") or {}
        extra = {k: int(fd[k]) for k in EXTRA_KEYS if fd.get(k) is not None}
        out.append(Match(parse_date(e["date"]), e["home"]["id"], e["away"]["id"], e["hs"], e["as"],
                         neutral=e["neutral"], comp=e["slug"], id=e["id"], extra=extra))
    return out


def league_priors(model: DixonColes, events: list[dict], ref: datetime) -> dict:
    """Vorwissen je Team = Durchschnitt seiner Liga (aus der ersten Modellstufe)."""
    since = ref - timedelta(days=400)
    seen = defaultdict(Counter)
    for e in events:
        if e["slug"] in C.LEAGUE_SLUGS and e["completed"]:
            d = parse_date(e["date"])
            if since <= d < ref:
                seen[e["home"]["id"]][e["slug"]] += 1
                seen[e["away"]["id"]][e["slug"]] += 1
    primary = {t: c.most_common(1)[0][0] for t, c in seen.items()}
    by_league = defaultdict(list)
    for t, lg in primary.items():
        if model.knows(t, 10):
            by_league[lg].append(t)
    means = {lg: (float(np.mean([model.att[t] for t in ts])), float(np.mean([model.dfn[t] for t in ts])))
             for lg, ts in by_league.items() if len(ts) >= 6}
    return {t: means[lg] for t, lg in primary.items() if lg in means}


def market_probs(odds: dict) -> tuple[list[float] | None, float | None]:
    """Marge aus den Quoten herausrechnen: (1X2-Wahrscheinlichkeiten, Über-2.5-Wahrscheinlichkeit)."""
    p12 = None
    if all(odds.get(k) for k in ("1", "X", "2")):
        inv = np.array([1 / odds["1"], 1 / odds["X"], 1 / odds["2"]])
        p12 = (inv / inv.sum()).tolist()
    po = None
    if odds.get("O2.5") and odds.get("U2.5"):
        io, iu = 1 / odds["O2.5"], 1 / odds["U2.5"]
        po = io / (io + iu)
    return p12, po


def outcome_probs(mat: np.ndarray) -> tuple[float, float, float, float]:
    g = np.arange(mat.shape[0])
    return (float(np.tril(mat, -1).sum()), float(np.trace(mat)), float(np.triu(mat, 1).sum()),
            float(mat[(g[:, None] + g[None, :]) >= 3].sum()))


def calibrate(lam: float, mu: float, rho: float, t1: float, t2: float, to: float | None) -> tuple[float, float]:
    """Torraten so anpassen, dass Heimsieg/Auswärtssieg (und Über 2.5) die Zielwerte treffen."""
    def loss(x):
        m = score_matrix(np.exp(x[0]), np.exp(x[1]), rho, 8)
        p1, _, p2, po = outcome_probs(m)
        out = (p1 - t1) ** 2 + (p2 - t2) ** 2
        if to is not None:
            out += (po - to) ** 2
        return out
    res = minimize(loss, [np.log(lam), np.log(mu)], method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-9, "maxiter": 400})
    return float(np.exp(res.x[0])), float(np.exp(res.x[1]))


class Predictor:
    def __init__(self, params: Params | None = None):
        self.params = params or Params()
        self.goals = self.sot = self.nation = self.corners = self.cards = None
        self.conv = 0.3   # Tore pro Schuss aufs Tor

    # ---------- Training ----------
    def fit(self, events: list[dict], ref: datetime, warm: "Predictor | None" = None,
            with_nations: bool = True, with_counts: bool = True, log=None) -> "Predictor":
        xi = self.params.xi
        club_ev = [e for e in events if e["slug"] not in NATION_SLUGS]
        cm = to_matches(club_ev)
        league_teams = {t for e in club_ev if e["slug"] in C.LEAGUE_SLUGS for t in (e["home"]["id"], e["away"]["id"])}
        w_goals = warm.goals if warm else None
        stage1 = DixonColes(xi=xi).fit(cm, ref, league_teams=league_teams, warm=w_goals)
        priors = league_priors(stage1, club_ev, ref)
        self.goals = DixonColes(xi=xi).fit(cm, ref, league_teams=league_teams, priors=priors, warm=stage1)

        sot_m = [m for m in cm if "hst" in m.extra and m.date < ref]
        if len(sot_m) > 500:
            self.sot = RateModel(xi=xi).fit(sot_m, ref, key=("hst", "ast"), warm=warm.sot if warm else None)
            recent = [m for m in sot_m if (ref - m.date).days < 365]
            shots = sum(m.extra["hst"] + m.extra["ast"] for m in recent)
            self.conv = sum(m.hg + m.ag for m in recent) / shots if shots else 0.3
        if with_nations:
            try:
                nat = to_matches([e for e in events if e["slug"] in NATION_SLUGS])
                self.nation = DixonColes(xi=xi, weak_prior=0.3).fit(nat, ref, warm=warm.nation if warm else None)
            except ValueError:
                self.nation = None
        if with_counts:
            try:
                self.corners = RateModel(xi=xi).fit([m for m in cm if "hc" in m.extra], ref, key=("hc", "ac"))
                self.cards = RateModel(xi=xi).fit([m for m in cm if "hy" in m.extra], ref, key=("hy", "ay"))
            except ValueError:
                pass
        if log:
            log(f"Modelle: Clubs {len(self.goals.teams)} Teams/{self.goals.n_matches} Spiele, "
                f"Schüsse {self.sot.n_matches if self.sot else 0} Spiele, "
                f"Nationen {len(self.nation.teams) if self.nation else 0} Teams, "
                f"Ecken {self.corners.n_matches if self.corners else 0} Spiele, "
                f"Liga-Vorwissen für {len(priors)} Teams")
        return self

    # ---------- Prognose ----------
    def model_for(self, slug: str) -> DixonColes | None:
        return self.nation if slug in NATION_SLUGS else self.goals

    def reliable(self, e: dict) -> bool:
        m = self.model_for(e["slug"])
        return bool(m) and m.knows(e["home"]["id"], C.MIN_GAMES) and m.knows(e["away"]["id"], C.MIN_GAMES)

    def model_rates(self, e: dict, beta: float | None = None) -> tuple[float, float, bool] | None:
        """Torraten laut Modell (ohne Markt). Drittes Feld: Schuss-Modell beteiligt."""
        m = self.model_for(e["slug"])
        if m is None:
            return None
        h, a, nt, comp = e["home"]["id"], e["away"]["id"], e["neutral"], e["slug"]
        lam, mu = m.rates(h, a, nt, comp)
        beta = self.params.beta if beta is None else beta
        used = False
        if m is self.goals and self.sot and beta > 0 and self.sot.knows(h, 8) and self.sot.knows(a, 8):
            sh, sa = self.sot.rates(h, a, nt, comp)
            lam = lam ** (1 - beta) * (self.conv * sh) ** beta
            mu = mu ** (1 - beta) * (self.conv * sa) ** beta
            used = True
        return lam, mu, used

    def predict(self, e: dict, odds: dict | None = None) -> dict | None:
        mr = self.model_rates(e)
        if mr is None:
            return None
        lam, mu, used_sot = mr
        m = self.model_for(e["slug"])
        rho = m.rho
        mat_model = score_matrix(lam, mu, rho)
        p1, px, p2, po = outcome_probs(mat_model)
        out = {"lam": lam, "mu": mu, "rho": rho, "sot": used_sot,
               "p_model": [p1, px, p2], "po_model": po, "p_market": None, "po_market": None,
               "matrix": mat_model, "known": self.reliable(e)}
        # Markt-Kalibrierung (nur bei verlässlichen Teams sinnvoll, sonst ebenfalls: Markt weiss mehr)
        if odds:
            pm, pom = market_probs(odds)
            if pm:
                w, wo = self.params.w, self.params.w_ou
                t1 = w * p1 + (1 - w) * pm[0]
                t2 = w * p2 + (1 - w) * pm[2]
                to = (wo * po + (1 - wo) * pom) if pom is not None else None
                lam2, mu2 = calibrate(lam, mu, rho, t1, t2, to)
                out.update(lam=lam2, mu=mu2, matrix=score_matrix(lam2, mu2, rho),
                           p_market=pm, po_market=pom)
        corners = cards = None
        if m is self.goals:
            h, a, nt, comp = e["home"]["id"], e["away"]["id"], e["neutral"], e["slug"]
            if self.corners and self.corners.knows(h, 5) and self.corners.knows(a, 5):
                corners = self.corners.rates(h, a, nt, comp)
            if self.cards and self.cards.knows(h, 5) and self.cards.knows(a, 5):
                cards = self.cards.rates(h, a, nt, comp)
        out["corners"], out["cards"] = corners, cards
        out["pred"] = Prediction(e["home"]["id"], e["away"]["id"], out["lam"], out["mu"], out["matrix"])
        return out

"""Feintuning per Rückblick (Walk-Forward).

Für die letzten ~15 Monate wird alle drei Wochen neu trainiert, jeweils nur mit
Daten vor diesem Zeitpunkt, und die folgenden Top-5-Ligaspiele werden
vorhergesagt. Verglichen werden mehrere Einstellungen:

  xi    Zeitgewichtung (wie schnell alte Spiele an Gewicht verlieren)
  beta  Anteil des Schuss-Modells an den Torraten

Bewertet wird mit Log-Loss (je tiefer, desto besser). Danach wird der beste
Anteil w für den Mix aus Modell und Marktquoten bestimmt. Die Vorhersagen der
besten Einstellung sind gleichzeitig die Daten für den Rückblick-Simulator.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

import config as C
from model import score_matrix
from predictor import Params, Predictor, market_probs, outcome_probs
from sources.espn import FINAL_90, parse_date

XIS = [0.0012, 0.0019, 0.003]
BETAS = [0.0, 0.25, 0.45, 0.65]
STEP_DAYS = 21


def _ll(p):
    return -math.log(max(p, 1e-9))


def sim_row(e, p1, px, p2, po):
    fd = e["fd"]
    return [e["date"][:10], e["slug"], e["home"]["tla"] or e["home"]["name"][:3],
            e["away"]["tla"] or e["away"]["name"][:3],
            round(p1, 3), round(px, 3), round(p2, 3), round(po, 3), round(1 - po, 3),
            fd["o1"], fd["oX"], fd["o2"], fd.get("oO25"), fd.get("oU25"), e["hs"], e["as"]]


def targets(events, start, end=None):
    return [e for e in events if e["slug"] in C.TOP5 and e.get("fd") and e["fd"].get("o1")
            and e["status"] in FINAL_90 and e["hs"] is not None
            and start <= parse_date(e["date"]) < (end or datetime.max.replace(tzinfo=timezone.utc))]


def evaluate(rows: list[list]) -> dict:
    """Log-Loss und Trefferquote für Modell, Markt und optimalen Mix."""
    n = len(rows)
    if not n:
        return {}
    res, ll_m, ll_k, ll_ou_m, ll_ou_k, hit_m, hit_k = [], 0, 0, 0, 0, 0, 0
    pm_all, pk_all, ou = [], [], []
    for r in rows:
        hg, ag = r[14], r[15]
        k = 0 if hg > ag else 1 if hg == ag else 2
        pm = [r[4], r[5], r[6]]
        pk, pok = market_probs({"1": r[9], "X": r[10], "2": r[11], "O2.5": r[12], "U2.5": r[13]})
        pm_all.append((pm, k))
        pk_all.append(pk)
        ll_m += _ll(pm[k])
        ll_k += _ll(pk[k])
        hit_m += int(np.argmax(pm) == k)
        hit_k += int(np.argmax(pk) == k)
        if pok is not None:
            over = hg + ag > 2.5
            ou.append((r[7], pok, over))
    out = {"n": n, "ll_model": ll_m / n, "ll_market": ll_k / n, "hit_model": hit_m / n, "hit_market": hit_k / n}
    best_w, best = 0.0, 9.0
    for w in np.arange(0, 1.0001, 0.05):
        ll = sum(_ll(w * pm[k] + (1 - w) * pk[k]) for (pm, k), pk in zip(pm_all, pk_all)) / n
        if ll < best:
            best_w, best = float(w), ll
    out.update(w=round(best_w, 2), ll_blend=best,
               hit_blend=sum(int(np.argmax([best_w * a + (1 - best_w) * b for a, b in zip(pm, pk)]) == k)
                             for (pm, k), pk in zip(pm_all, pk_all)) / n)
    if ou:
        f = lambda p, o: _ll(p if o else 1 - p)
        out["ll_ou_model"] = sum(f(a, o) for a, _, o in ou) / len(ou)
        out["ll_ou_market"] = sum(f(b, o) for _, b, o in ou) / len(ou)
        best_wo, bo = 0.0, 9.0
        for w in np.arange(0, 1.0001, 0.05):
            ll = sum(f(w * a + (1 - w) * b, o) for a, b, o in ou) / len(ou)
            if ll < bo:
                best_wo, bo = float(w), ll
        out.update(w_ou=round(best_wo, 2), ll_ou_blend=bo)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def tune(events: list[dict], now: datetime, log=print) -> tuple[Params, list[list]]:
    start = now - timedelta(days=455)
    tg = targets(events, start)
    if len(tg) < 300:
        log(f"Feintuning übersprungen: nur {len(tg)} Spiele mit Quoten")
        return Params(), []
    rows = defaultdict(list)   # (xi, beta) -> Zeilen
    d = start
    warm = {xi: None for xi in XIS}
    n_fits = 0
    while d < now:
        block = [e for e in tg if d <= parse_date(e["date"]) < d + timedelta(days=STEP_DAYS)]
        if block:
            for xi in XIS:
                try:
                    pr = Predictor(Params(xi=xi)).fit(events, d, warm=warm[xi], with_nations=False, with_counts=False)
                except ValueError:
                    continue
                warm[xi] = pr
                n_fits += 1
                for e in block:
                    for beta in BETAS:
                        mr = pr.model_rates(e, beta=beta)
                        if not mr:
                            continue
                        p1, px, p2, po = outcome_probs(score_matrix(mr[0], mr[1], pr.goals.rho, 10))
                        rows[(xi, beta)].append(sim_row(e, p1, px, p2, po))
        d += timedelta(days=STEP_DAYS)
    grid = []
    for (xi, beta), rs in rows.items():
        ev = evaluate(rs)
        score = ev["ll_model"] + ev.get("ll_ou_model", 0)
        grid.append({"xi": xi, "beta": beta, "ll": ev["ll_model"], "ll_ou": ev.get("ll_ou_model"), "score": score})
    grid.sort(key=lambda g: g["score"])
    best = grid[0]
    best_rows = sorted(rows[(best["xi"], best["beta"])], key=lambda r: r[0])
    ev = evaluate(best_rows)
    params = Params(xi=best["xi"], beta=best["beta"], w=ev["w"], w_ou=ev.get("w_ou", ev["w"]),
                    tuned_at=now.isoformat(), metrics={**ev, "grid": grid, "fits": n_fits})
    log(f"Feintuning: xi={params.xi}, beta={params.beta}, w={params.w}, w_ou={params.w_ou} | "
        f"Log-Loss Modell {ev['ll_model']}, Markt {ev['ll_market']}, Mix {ev['ll_blend']} "
        f"({ev['n']} Spiele, {n_fits} Trainings)")
    return params, best_rows

"""Alle Wettmärkte eines Spiels, exakt aus der Resultat-Matrix abgeleitet.

Schlüssel (in der Web-App übersetzt):
  1, X, 2                Sieg Heim / Unentschieden / Sieg Gast
  1X, X2, 12             Doppelchance
  O1.5 / U1.5 …          Über/Unter Tore (0.5 bis 4.5)
  BTTS / NOBTTS          Beide Teams treffen ja/nein
  HS / AS                Heimteam trifft / Gastteam trifft
  HO1.5 / AO1.5          Heim-/Gastteam schiesst mehr als 1.5 Tore
  CS2-1                  Exaktes Resultat 2:1
  1+O2.5 usw.            Kombi im selben Spiel
  CO9.5 / CU9.5 …        Eckbälle total (nur wenn Ecken-Daten vorhanden)
  C1 / CX / C2           Mehr Ecken Heim / gleich viele / Gast
  KO3.5 / KU3.5 …        Gelbe Karten total
"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson

GOAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]
CORNER_LINES = [7.5, 8.5, 9.5, 10.5, 11.5]
CARD_LINES = [2.5, 3.5, 4.5, 5.5]
COMBO_RESULTS = ["1", "X", "2", "1X", "X2"]
COMBO_EXTRAS = ["O1.5", "O2.5", "U2.5", "U3.5", "BTTS", "NOBTTS"]


def _masks(n: int) -> dict[str, np.ndarray]:
    g = np.arange(n)
    hg, ag = g[:, None] + 0 * g[None, :], 0 * g[:, None] + g[None, :]
    tot = hg + ag
    m = {
        "1": hg > ag, "X": hg == ag, "2": hg < ag,
        "BTTS": (hg > 0) & (ag > 0),
        "HS": hg > 0, "AS": ag > 0,
        "HO1.5": hg >= 2, "AO1.5": ag >= 2,
    }
    m["1X"], m["X2"], m["12"] = m["1"] | m["X"], m["X"] | m["2"], m["1"] | m["2"]
    m["NOBTTS"] = ~m["BTTS"]
    for line in GOAL_LINES:
        m[f"O{line}"] = tot > line
        m[f"U{line}"] = tot < line
    return m


def goal_markets(matrix: np.ndarray, n_scores: int = 6) -> dict[str, float]:
    m = _masks(matrix.shape[0])
    out = {k: float(matrix[v].sum()) for k, v in m.items()}
    for r in COMBO_RESULTS:
        for e in COMBO_EXTRAS:
            out[f"{r}+{e}"] = float(matrix[m[r] & m[e]].sum())
    flat = np.argsort(matrix, axis=None)[::-1][:n_scores]
    for idx in flat:
        i, j = np.unravel_index(idx, matrix.shape)
        out[f"CS{i}-{j}"] = float(matrix[i, j])
    return out


def count_markets(lam: float, mu: float, prefix: str, lines: list[float], with_side: bool) -> dict[str, float]:
    """Totals (und optional 'wer hat mehr') für zwei unabhängige Poisson-Zählungen."""
    out = {}
    tot = lam + mu
    for line in lines:
        k = int(np.floor(line))
        p_under = float(poisson.cdf(k, tot))
        out[f"{prefix}O{line}"] = 1 - p_under
        out[f"{prefix}U{line}"] = p_under
    if with_side:
        g = np.arange(30)
        ph, pa = poisson.pmf(g, lam), poisson.pmf(g, mu)
        mat = np.outer(ph, pa)
        diff = g[:, None] - g[None, :]
        out[f"{prefix}1"] = float(mat[diff > 0].sum())
        out[f"{prefix}X"] = float(mat[diff == 0].sum())
        out[f"{prefix}2"] = float(mat[diff < 0].sum())
    return out


def all_markets(matrix: np.ndarray, corners: tuple[float, float] | None = None,
                cards: tuple[float, float] | None = None) -> dict[str, float]:
    out = goal_markets(matrix)
    if corners:
        out.update(count_markets(*corners, "C", CORNER_LINES, True))
    if cards:
        out.update(count_markets(*cards, "K", CARD_LINES, False))
    return out


def outcome_hit(key: str, hg: int, ag: int, extra: dict | None = None) -> bool | None:
    """Hat der Tipp gewonnen? None, wenn nicht auswertbar (z. B. Ecken ohne Daten)."""
    if "+" in key:
        parts = [outcome_hit(p, hg, ag, extra) for p in key.split("+")]
        return None if None in parts else all(parts)
    if key.startswith("CS"):
        i, j = key[2:].split("-")
        return hg == int(i) and ag == int(j)
    if key[0] in "CK" and key not in ("1", "X", "2"):
        extra = extra or {}
        if key[0] == "C":
            h, a = extra.get("hc"), extra.get("ac")
        else:
            h, a = extra.get("hy"), extra.get("ay")
        if h is None or a is None:
            return None
        rest = key[1:]
        if rest in ("1", "X", "2"):
            return {"1": h > a, "X": h == a, "2": h < a}[rest]
        line = float(rest[1:])
        return (h + a > line) if rest[0] == "O" else (h + a < line)
    m = _masks(max(hg, ag) + 1)
    return bool(m[key][hg, ag])

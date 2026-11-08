"""GoalOracle – Premier-League-Tippbot.

Normaler Lauf:   python bot.py              -> Analyse + Tipps an Telegram
Nur anzeigen:    python bot.py --dry-run    -> Ausgabe im Terminal, nichts senden
Backtest:        python bot.py --backtest   -> wie gut hätte das Modell getroffen?
"""
from __future__ import annotations

import argparse
import html
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from data import load_all
from model import DixonColes, Match
from web_export import write_data

TZ = ZoneInfo("Europe/Zurich")
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ---------------- Hilfsfunktionen ----------------
def fmt_time(d: datetime) -> str:
    d = d.astimezone(TZ)
    return f"{WD[d.weekday()]} {d:%d.%m. %H:%M}"


def confidence(p: float) -> str:
    return "hoch" if p >= 0.60 else "mittel" if p >= 0.45 else "tief"


def form(team: str, played: list[Match], n: int = 5) -> str:
    games = sorted((m for m in played if team in (m.home, m.away)), key=lambda m: m.date)[-n:]
    out = ""
    for m in games:
        gf, ga = (m.hg, m.ag) if m.home == team else (m.ag, m.hg)
        out += "S" if gf > ga else "U" if gf == ga else "N"
    return out or "-"


def send_telegram(text: str, token: str, chat_id: str) -> None:
    """Teilt lange Nachrichten auf (Telegram-Limit 4096 Zeichen)."""
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > 3800:
            chunks.append(cur)
            cur = ""
        cur += block + "\n\n"
    chunks.append(cur)
    for c in filter(str.strip, chunks):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": c.strip(), "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Telegram-Fehler {r.status_code}: {r.text}")


# ---------------- Tagesreport ----------------
def build_report(model: DixonColes, matches: list[Match], names: dict[str, str],
                 now: datetime, days_ahead: int, warnings: list[str]) -> str:
    name = lambda k: html.escape(names.get(k, k.title()))
    played = [m for m in matches if m.hg is not None]
    upcoming = sorted((m for m in matches if m.hg is None and now <= m.date <= now + timedelta(days=days_ahead)),
                      key=lambda m: m.date)

    lines = [f"⚽🔮 <b>GOALORACLE</b> · Premier League\n{now.astimezone(TZ):%d.%m.%Y}"]

    # Tipps
    if upcoming:
        lines.append(f"<b>🎯 Tipps (nächste {days_ahead} Tage)</b>")
        for m in upcoming:
            p = model.predict(m.home, m.away)
            hs, as_, ps = p.best_score()
            th, ta, pt = p.best_score(restrict_to_tip=True)
            score_line = f"Resultat: <b>{hs}:{as_}</b> ({ps:.0%})"
            if (th, ta) != (hs, as_):
                score_line += f" · passend zum Tipp: {th}:{ta} ({pt:.0%})"
            lines.append(
                f"<b>{fmt_time(m.date)}</b>\n"
                f"{name(m.home)} – {name(m.away)}\n"
                f"1: {p.p_home:.0%} · X: {p.p_draw:.0%} · 2: {p.p_away:.0%}\n"
                f"👉 Tipp: <b>{p.tip}</b> (Sicherheit {confidence(p.tip_prob)})\n"
                f"{score_line}\n"
                f"xG {p.xg_home:.1f} – {p.xg_away:.1f} · Über 2.5: {p.p_over25:.0%} · "
                f"Beide treffen: {p.p_btts:.0%}"
            )
    else:
        lines.append(f"Keine PL-Spiele in den nächsten {days_ahead} Tagen.")

    # Stärke-Ranking der aktuellen Teams
    current = set(names)
    rows = [r for r in model.ratings() if r[0] in current]
    table = ["#  Team            Tore+ Tore- Form"]
    for i, (t, gf, ga) in enumerate(rows, 1):
        table.append(f"{i:<2} {names.get(t, t)[:15]:<15} {gf:5.2f} {ga:5.2f} {form(t, played)}")
    lines.append("<b>📊 Stärke-Ranking</b> (erwartete Tore pro Spiel gegen Durchschnittsteam)\n"
                 f"<pre>{html.escape(chr(10).join(table))}</pre>")

    lines.append(f"<i>Modell: Dixon-Coles · Heimvorteil {math.exp(model.home_adv):.2f}× · "
                 f"{len(played)} Spiele ausgewertet. Auch ein Orakel irrt sich – wett nur, was du verlieren kannst.</i>")
    if warnings:
        lines.append("⚠️ " + "; ".join(html.escape(w) for w in warnings))
    return "\n\n".join(lines)


# ---------------- Backtest ----------------
def backtest(matches: list[Match], now: datetime, days: int, xi: float) -> str:
    played = sorted((m for m in matches if m.hg is not None), key=lambda m: m.date)
    start = now - timedelta(days=days)
    by_day = defaultdict(list)
    for m in played:
        if m.date >= start:
            by_day[m.date.astimezone(TZ).date()].append(m)

    n = hit_1x2 = hit_score = hit_score_tip = home_base = 0
    logloss = 0.0
    for day in sorted(by_day):
        cutoff = datetime(day.year, day.month, day.day, tzinfo=TZ)
        try:
            model = DixonColes(xi=xi).fit(played, cutoff)
        except ValueError:
            continue
        for m in by_day[day]:
            p = model.predict(m.home, m.away)
            actual = "1" if m.hg > m.ag else "X" if m.hg == m.ag else "2"
            n += 1
            hit_1x2 += p.tip == actual
            home_base += actual == "1"
            hit_score += p.best_score()[:2] == (m.hg, m.ag)
            hit_score_tip += p.best_score(True)[:2] == (m.hg, m.ag)
            prob = {"1": p.p_home, "X": p.p_draw, "2": p.p_away}[actual]
            logloss -= math.log(max(prob, 1e-9))
        print(f"  {day}: {len(by_day[day])} Spiele", file=sys.stderr)

    if not n:
        return "Backtest: keine Spiele im Zeitraum."
    return (f"📈 <b>Backtest</b> (letzte {days} Tage, {n} Spiele, jeweils nur mit Daten vor dem Spieltag)\n"
            f"1X2-Treffer: <b>{hit_1x2 / n:.1%}</b> (immer Heimsieg tippen: {home_base / n:.1%})\n"
            f"Exaktes Resultat: <b>{hit_score / n:.1%}</b> · passend zum Tipp: {hit_score_tip / n:.1%}\n"
            f"Log-Loss 1X2: {logloss / n:.3f} (Zufall ≈ 1.099, tiefer = besser)")


# ---------------- Main ----------------
def main() -> None:
    ap = argparse.ArgumentParser(description="GoalOracle – Premier-League-Tippbot")
    ap.add_argument("--dry-run", action="store_true", help="nur ausgeben, nicht an Telegram senden")
    ap.add_argument("--backtest", action="store_true", help="Trefferquote der Vergangenheit messen")
    ap.add_argument("--days", type=int, default=int(os.getenv("DAYS_AHEAD", 4)),
                    help="Tipps für Spiele der nächsten N Tage (Standard 4)")
    ap.add_argument("--backtest-days", type=int, default=180)
    ap.add_argument("--xi", type=float, default=0.0019, help="Zeitgewichtung pro Tag")
    ap.add_argument("--web", metavar="PFAD", help="Daten für die Web-App schreiben, z. B. web/data.json")
    ap.add_argument("--web-days", type=int, default=10, help="Tipps in der Web-App für N Tage (Standard 10)")
    ap.add_argument("--no-telegram", action="store_true", help="keine Telegram-Nachricht senden")
    args = ap.parse_args()

    fd_token = os.getenv("FOOTBALL_DATA_TOKEN")
    if not fd_token:
        sys.exit("FOOTBALL_DATA_TOKEN fehlt (gratis auf football-data.org/client/register).")

    now = datetime.now(timezone.utc)
    matches, names, tlas, warnings = load_all(fd_token, now)

    if args.backtest:
        text = backtest(matches, now, args.backtest_days, args.xi)
    else:
        model = DixonColes(xi=args.xi).fit(matches, now)
        text = build_report(model, matches, names, now, args.days, warnings)
        if args.web:
            write_data(args.web, model=model, matches=matches, names=names, tlas=tlas,
                       now=now, days_ahead=args.web_days)
            print(f"Web-Daten geschrieben: {args.web}")

    if args.no_telegram:
        return
    if args.dry_run:
        print(text)
        return
    tg_token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tg_token or not chat_id:
        print(text)
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen – Ausgabe nur im Terminal.")
    send_telegram(text, tg_token, chat_id)
    print("An Telegram gesendet.")


if __name__ == "__main__":
    main()

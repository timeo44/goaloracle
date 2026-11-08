"""GoalOracle – Fussball-Tippbot für die Top-5-Ligen, Europacups, Nations League und Pokale.

python bot.py                 -> alles rechnen, Web-Daten schreiben, Top-Tipps an Telegram
python bot.py --no-telegram   -> ohne Telegram
python bot.py --dry-run       -> Telegram-Text nur im Terminal zeigen
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import config as C
import engine as E
from sources import espn, fdcouk, oddsapi

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
TZ = ZoneInfo("Europe/Zurich")
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

LABEL = {"1": "Sieg {h}", "X": "Unentschieden", "2": "Sieg {a}", "1X": "{h} oder X", "X2": "X oder {a}",
         "12": "Kein Unentschieden", "BTTS": "Beide treffen", "NOBTTS": "Nicht beide treffen",
         "HS": "{h} trifft", "AS": "{a} trifft", "HO1.5": "{h} 2+ Tore", "AO1.5": "{a} 2+ Tore"}


def label(key, h, a):
    if "+" in key:
        return " & ".join(label(k, h, a) for k in key.split("+"))
    if key in LABEL:
        return LABEL[key].format(h=h, a=a)
    if key.startswith("CS"):
        return "Resultat " + key[2:].replace("-", ":")
    if key[0] in "OU":
        return ("Über " if key[0] == "O" else "Unter ") + key[1:] + " Tore"
    if key[0] == "C":
        return "Ecken " + ({"O": "über ", "U": "unter "}.get(key[1], "") + key[2:] if key[1] in "OU" else key[1:])
    if key[0] == "K":
        return ("Karten über " if key[1] == "O" else "Karten unter ") + key[2:]
    return key


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def telegram_text(singles, legs, now, site):
    when = lambda u: f"{WD[E.parse_date(u['kickoff']).astimezone(TZ).weekday()]} {E.parse_date(u['kickoff']).astimezone(TZ):%H:%M}"
    comp = lambda u: C.DISPLAY[u["comp"]][1]
    lines = [f"⚽🔮 <b>GOALORACLE</b> · Top-Tipps\n{now.astimezone(TZ):%d.%m.%Y}"]
    if not singles:
        lines.append("Heute und morgen keine Spiele in den abgedeckten Wettbewerben.")
    for i, u in enumerate(singles, 1):
        pk = u["pick"]
        h, a = html.escape(u["home"]["name"]), html.escape(u["away"]["name"])
        quote = f"Quote {pk['odds']:.2f} · Value {pk['ev']:+.0%}" if pk.get("ev") is not None \
            else f"faire Quote {pk['fair']:.2f}"
        lines.append(f"<b>{i}. {html.escape(label(pk['key'], u['home']['name'], u['away']['name']))}</b>\n"
                     f"{h} – {a} · {comp(u)} · {when(u)}\n"
                     f"Chance {pk['p']:.0%} · {quote}")
    if len(legs) >= 2:
        prob = 1.0
        txt = []
        for u, k, p in legs:
            prob *= p
            txt.append(f"• {html.escape(label(k, u['home']['name'], u['away']['name']))} "
                       f"({html.escape(u['home']['tla'])}–{html.escape(u['away']['tla'])}, {p:.0%})")
        lines.append("<b>🧩 Kombi des Tages</b>\n" + "\n".join(txt) +
                     f"\nGesamtchance {prob:.0%} · faire Quote {1 / prob:.2f}")
    if site:
        lines.append(f'Alle Spiele, Kombis und Testlauf: <a href="{site}">{site}</a>')
    lines.append("<i>Statistisches Modell, keine Garantie. Wette nur, was du verlieren kannst.</i>")
    return "\n\n".join(lines)


def send_telegram(text, token, chat_id):
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML",
                            "disable_web_page_preview": True})
    if not r.ok:
        raise RuntimeError(f"Telegram-Fehler {r.status_code}: {r.text}")


def main():
    ap = argparse.ArgumentParser(description="GoalOracle")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Telegram-Text nur anzeigen")
    ap.add_argument("--skip-sim", action="store_true", help="Rückblick nicht neu rechnen")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    slugs = list(C.DISPLAY) + C.TRAIN_CLUB_LEAGUES + C.TRAIN_NATION
    events = espn.load(slugs, C.HISTORY_START, now)
    rows = fdcouk.fetch(list(C.FDCO_MAP), [season - 2, season - 1, season], season)
    n = fdcouk.attach(rows, events, C.FDCO_MAP)
    print(f"Quoten/Ecken zugeordnet: {n} Spiele")

    models = E.fit_models(events, now)
    info, form = E.team_info(events), E.form_of(events, now)
    by_id = {e["id"]: e for e in events}

    odds, credits = {}, None
    key = os.getenv("ODDS_API_KEY")
    if key:
        soon = [{**e, "dt": E.parse_date(e["date"])} for e in events
                if e["slug"] in C.DISPLAY and not e["completed"] and e["status"] not in espn.DEAD]
        soon = [e for e in soon if e["dt"] > now]
        odds, credits = oddsapi.fetch(key, C.ODDS_KEYS, soon, now, C.ODDS_DAYS_AHEAD, C.ODDS_MIN_CREDITS)
    prev = load_json(WEB / "data.json", {})
    # Quoten vom Vortag behalten, wenn heute keine neuen geholt wurden
    for u in prev.get("upcoming", []):
        if u.get("odds") and u["id"] not in odds:
            odds[u["id"]] = u["odds"]

    upcoming = E.build_upcoming(models, events, info, form, odds, now)
    history = E.update_history(prev.get("history", []), upcoming, by_id, now)
    paper = E.run_paper(load_json(WEB / "paper.json", None), upcoming, by_id, now)
    rankings = E.build_rankings(models, events, info, form, now)

    data = {
        "generated": now.isoformat(),
        "comps": {k: {"name": v[0], "short": v[1], "type": v[2]} for k, v in C.DISPLAY.items()},
        "risk": C.RISK, "days_ahead": C.DAYS_AHEAD,
        "odds": {"key": bool(key), "credits": credits, "matches": sum(1 for u in upcoming if u["odds"])},
        "model": {"club_teams": len(models.club.teams), "club_matches": models.club.n_matches,
                  "home_adv": round(2.718281828 ** models.club.home_adv, 2),
                  "corners": bool(models.corners)},
        "upcoming": upcoming, "rankings": rankings, "history": history,
    }
    write_json(WEB / "data.json", data)
    write_json(WEB / "paper.json", paper)
    if not args.skip_sim:
        write_json(WEB / "sim.json", {"generated": now.isoformat(), "rows": E.build_sim(events, now)})
    print(f"Web-Daten: {len(upcoming)} Spiele, {len(history)} in der Bilanz, "
          f"Spielgeld {paper['balance']:.2f} CHF")

    if args.no_telegram:
        return
    singles, legs = E.top_tips(upcoming, now)
    site = os.getenv("SITE_URL", "")
    text = telegram_text(singles, legs, now, site)
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if args.dry_run or not token or not chat:
        print(text)
        return
    send_telegram(text, token, chat)
    print("Telegram gesendet.")


if __name__ == "__main__":
    sys.exit(main())

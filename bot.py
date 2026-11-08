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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import config as C
import engine as E
import tuning as T
from predictor import Params, Predictor
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


def wait_until(hhmm: str, max_minutes: int = 45):
    """Bis zur gewünschten Schweizer Uhrzeit warten (z. B. 10:00), höchstens max_minutes."""
    import time
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(TZ)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if 0 < wait <= max_minutes * 60:
        print(f"Warte {wait / 60:.1f} Minuten bis {hhmm} Uhr …")
        time.sleep(wait)


def main():
    ap = argparse.ArgumentParser(description="GoalOracle")
    ap.add_argument("--notify", action="store_true", help="Top-Tipps an Telegram senden")
    ap.add_argument("--send-at", metavar="HH:MM", help="Telegram erst zu dieser Schweizer Uhrzeit senden")
    ap.add_argument("--refresh-odds", action="store_true", help="Quoten sicher neu laden (kostet Credits)")
    ap.add_argument("--retune", action="store_true", help="Modell-Einstellungen neu optimieren (dauert einige Minuten)")
    ap.add_argument("--dry-run", action="store_true", help="Telegram-Text nur anzeigen")
    ap.add_argument("--skip-sim", action="store_true", help="Rückblick nicht neu rechnen")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    slugs = list(C.DISPLAY) + C.TRAIN_CLUB_LEAGUES + C.TRAIN_NATION
    events = espn.load(slugs, C.HISTORY_START, now)
    rows = fdcouk.fetch(list(C.FDCO_MAP), [season - 2, season - 1, season], season)
    n_fd = fdcouk.attach(rows, events, C.FDCO_MAP)
    print(f"football-data.co.uk zugeordnet: {n_fd} Spiele")

    # Modell-Einstellungen: gespeichert oder neu optimieren
    tuning_f = ROOT / "cache" / "tuning.json"
    params = Params.from_dict(load_json(tuning_f, None))
    tuned_rows = None
    if args.retune or not params.tuned_at:
        params, tuned_rows = T.tune(events, now)
        if params.tuned_at:
            write_json(tuning_f, params.to_dict())
    print(f"Einstellungen: xi={params.xi}, Schuss-Anteil={params.beta}, Modell-Anteil 1X2={params.w}, Ü/U={params.w_ou}")

    pr = Predictor(params).fit(events, now, log=print)
    info = E.team_info(events)
    fdet = E.form_details(events)
    form = E.form_of(events, now, fdet)
    by_id = {e["id"]: e for e in events}

    # Quoten: neu laden höchstens alle 6 Stunden, ausser ausdrücklich gewünscht
    prev = load_json(WEB / "data.json", {})
    prev_odds = prev.get("odds", {})
    odds, credits, fetched = {}, prev_odds.get("credits"), prev_odds.get("fetched")
    key = os.getenv("ODDS_API_KEY")
    stale = not fetched or (now - datetime.fromisoformat(fetched)) > timedelta(hours=6)
    if key and (args.refresh_odds or stale):
        soon = [{**e, "dt": E.parse_date(e["date"])} for e in events
                if e["slug"] in C.DISPLAY and not e["completed"] and e["status"] not in espn.DEAD]
        soon = [e for e in soon if e["dt"] > now]
        odds, c = oddsapi.fetch(key, C.ODDS_KEYS, soon, now, C.ODDS_DAYS_AHEAD, C.ODDS_MIN_CREDITS)
        credits = c if c is not None else credits
        fetched = now.isoformat()
    elif key:
        print("Quoten: letzte Abfrage jünger als 6 Stunden, verwende gespeicherte Quoten")
    for u in prev.get("upcoming", []):      # bekannte Quoten behalten
        if u.get("odds") and u["id"] not in odds:
            odds[u["id"]] = u["odds"]

    upcoming = E.build_upcoming(pr, events, info, form, odds, now)
    prev_hist = load_json(WEB / "history.json", {}).get("history") or prev.get("history", [])
    history = E.update_history(prev_hist, upcoming, by_id, now)
    paper = E.run_paper(load_json(WEB / "paper.json", None), upcoming, by_id, now)
    rankings = E.build_rankings(pr, events, info, form, now)

    slugs_with_data = {e["slug"] for e in events if e["completed"]}
    data = {
        "generated": now.isoformat(),
        "repo": os.getenv("GITHUB_REPOSITORY", ""),
        "comps": {k: {"name": v[0], "short": v[1], "type": v[2]} for k, v in C.DISPLAY.items()},
        "risk": C.RISK, "days_ahead": C.DAYS_AHEAD,
        "odds": {"key": bool(key), "credits": credits, "fetched": fetched,
                 "matches": sum(1 for u in upcoming if u["odds"])},
        "model": {
            "club_teams": len(pr.goals.teams), "club_matches": pr.goals.n_matches,
            "home_adv": round(2.718281828 ** pr.goals.home_adv, 2),
            "comp_home": {k: round(2.718281828 ** (pr.goals.home_adv + v), 2) for k, v in pr.goals.comp_home.items()
                          if k in C.DISPLAY},
            "corners": bool(pr.corners), "nation_teams": len(pr.nation.teams) if pr.nation else 0,
            "sot_matches": pr.sot.n_matches if pr.sot else 0, "conv": round(pr.conv, 3),
            "params": params.to_dict(),
            "feeds": {"espn_matches": sum(1 for e in events if e["completed"]),
                      "espn_comps": len(slugs_with_data), "fdco_matches": n_fd},
        },
        "upcoming": upcoming, "rankings": rankings,
        "history_summary": E.history_summary(history),
        "comp_names": {**{k: v[0] for k, v in C.DISPLAY.items()}, **C.OTHER_NAMES},
    }
    shown = {u[s]["id"] for u in upcoming for s in ("home", "away")} | \
            {r["team"]["id"] for rows in rankings.values() for r in rows}
    data["forms"] = {t: fdet[t] for t in shown if t in fdet}
    data["ratings"] = E.team_ratings(pr, rankings, shown, events, now)
    opp = {x[1] for t in data["forms"] for x in data["forms"][t]}
    data["teams"] = {t: info[t] for t in opp if t in info}
    write_json(WEB / "data.json", data)
    write_json(WEB / "paper.json", paper)
    write_json(WEB / "history.json", {"generated": now.isoformat(), "history": history})
    if not args.skip_sim:
        sim_rows = E.build_sim(events, now, params, tuned_rows)
        write_json(WEB / "sim.json", {"generated": now.isoformat(), "w": params.w, "w_ou": params.w_ou,
                                      "rows": sim_rows})
    print(f"Web-Daten: {len(upcoming)} Spiele, {len(history)} in der Bilanz, "
          f"Spielgeld {paper['balance']:.2f} CHF")

    if not args.notify and not args.dry_run:
        return
    singles, legs = E.top_tips(upcoming, now)
    site = os.getenv("SITE_URL", "")
    text = telegram_text(singles, legs, now, site)
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if args.dry_run or not token or not chat:
        print(text)
        return
    if args.send_at:
        wait_until(args.send_at)
    send_telegram(text, token, chat)
    print("Telegram gesendet.")


if __name__ == "__main__":
    sys.exit(main())

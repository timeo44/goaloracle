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
import botd as B
from sources import telegram as TG
import tuning as T
from predictor import Params, Predictor
from sources import crests, espn, fdcouk, oddsapi

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
TZ = ZoneInfo("Europe/Zurich")
esc = html.escape
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


def telegram_text(day: dict | None, state: dict, now, site):
    """Nachricht mit den 5 Bets des Tages und der Bilanz von gestern."""
    lines = [f"⚽🔮 <b>GOALORACLE</b> · Bets des Tages\n{WD[now.astimezone(TZ).weekday()]} {now.astimezone(TZ):%d.%m.%Y}"]
    bets = (day or {}).get("bets", [])
    if not bets:
        lines.append("Heute keine verlässlichen Spiele in den abgedeckten Wettbewerben.")
    tot_p, tot_q = 1.0, 1.0
    for i, b in enumerate(bets, 1):
        ko = E.parse_date(b["kickoff"]).astimezone(TZ)
        h, a = b["home"]["name"], b["away"]["name"]
        q = b.get("odds") or b["fair"]
        tot_p *= b["p"]
        tot_q *= q
        quote = f"Quote {b['odds']:.2f}" + (f" · Value {b['ev']:+.0%}" if b.get("ev") is not None and b["ev"] > 0 else "") \
            if b.get("odds") else f"faire Quote {b['fair']:.2f}"
        lines.append(f"<b>{i}. {html.escape(label(b['key'], h, a))}</b>\n"
                     f"{html.escape(h)} – {html.escape(a)} · {C.DISPLAY[b['comp']][1]} · {WD[ko.weekday()]} {ko:%H:%M}\n"
                     f"Chance {b['p']:.0%} · {quote}")
    if len(bets) >= 2:
        lines.append(f"<b>Alle {len(bets)} als Kombi:</b> Chance {tot_p:.1%} · Quote {tot_q:.2f}")
    # gestern
    prev = next((d for d in state.get("days", []) if not d.get("retro") and d["day"] < now.astimezone(TZ).date().isoformat()), None)
    if prev:
        done = [x for x in prev["bets"] if isinstance(x.get("hit"), bool)]
        if done:
            won = sum(x["hit"] for x in done)
            wo = [x for x in done if x.get("odds")]
            units = sum((x["odds"] - 1) if x["hit"] else -1 for x in wo)
            lines.append(f"Gestern: {won} von {len(done)} richtig" + (f" ({units:+.2f} Einheiten)" if wo else ""))
    S = state.get("stats_live") or {}
    if S.get("bets"):
        lines.append(f"Bilanz seit Start: {S['hits']}/{S['bets']} richtig" +
                     (f" · {S['profit']:+.2f} Einheiten" if S.get("with_odds") else ""))
    if site:
        lines.append(f'Alle Spiele und Details: <a href="{site}#top5">{site}</a>')
    lines.append("<i>Statistisches Modell, keine Garantie. Wette nur, was du verlieren kannst.</i>")
    return "\n\n".join(lines)


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


def paper_text(new_bets: list[dict], paper: dict, site: str) -> str:
    """Nachricht, wenn das Spielgeld-Konto (Testlauf) neue Wetten setzt."""
    n = len(new_bets)
    lines = [f"🎯 <b>Testlauf</b> · {'neue Wette' if n == 1 else f'{n} neue Wetten'}"]
    for b in new_bets:
        if b.get("legs"):
            parts = []
            for leg in b["legs"]:
                lko = E.parse_date(leg["kickoff"]).astimezone(TZ)
                lh, la = leg["match"].split(" – ", 1)
                parts.append(f"• {esc(label(leg['key'], lh, la))} ({leg['odds']:.2f})\n  {esc(leg['match'])} · {WD[lko.weekday()]} {lko:%H:%M}")
            lines.append(f"<b>{esc(b['match'])}</b> · jeder Tipp mind. 70 %, zusammen {b['p'] * 100:.0f}%\n" + "\n".join(parts) +
                         f"\nEinsatz {b['stake']:.2f} CHF · Quote {b['odds']:.2f} · möglicher Gewinn {b['stake'] * b['odds']:.2f} CHF")
            continue
        ko = E.parse_date(b["kickoff"]).astimezone(TZ)
        h, a = b["match"].split(" – ", 1) if " – " in b["match"] else (b["match"], "")
        val = f" · Value {b['ev'] * 100:+.0f}%" if b.get("ev") is not None and b["ev"] >= 0.03 else ""
        lines.append(f"<b>{esc(label(b['key'], h, a))}</b>\n{esc(b['match'])} · {WD[ko.weekday()]} {ko:%H:%M}\n"
                     f"Einsatz {b['stake']:.2f} CHF · Quote {b['odds']:.2f} · Chance {b['p'] * 100:.0f}%{val}\n"
                     f"möglicher Gewinn {b['stake'] * b['odds']:.2f} CHF")
    open_st = sum(b["stake"] for b in paper["bets"] if b["status"] == "open")
    lines.append(f"Konto: {paper['balance']:.2f} CHF frei · {open_st:.2f} CHF im Spiel")
    if site:
        lines.append(f'<a href="{site}#testlauf">Testlauf ansehen</a>')
    return "\n\n".join(lines)


def send_only(now) -> int:
    """Heutige Top 5 (so wie sie um 10 Uhr festgelegt wurden) nochmals an Telegram schicken."""
    state = load_json(WEB / "botd.json", None) or {"days": []}
    today = B.local_day(now)
    day = next((d for d in state["days"] if not d.get("retro") and d["day"] == today), None)
    if not day:
        print("Für heute sind noch keine Top 5 festgelegt (das passiert um 10:00).")
        return 1
    token, owner = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    text = telegram_text(day, state, now, os.getenv("SITE_URL", ""))
    if not token or not owner:
        print(text)
        return 0
    tg_file = ROOT / "cache" / "telegram.json"
    tg = TG.find_group(token, owner, tg_file)
    if tg.get("chat_id"):
        TG.send(token, tg["chat_id"], text, tg)
        TG.save(tg_file, tg)
        print(f"Telegram gesendet an Gruppe «{tg.get('title', '')}».")
    else:
        TG.send(token, owner, text)
        print("Telegram gesendet (privat).")
    return 0


def main():
    ap = argparse.ArgumentParser(description="GoalOracle")
    ap.add_argument("--notify", action="store_true", help="Top-Tipps an Telegram senden")
    ap.add_argument("--send-at", metavar="HH:MM", help="Telegram erst zu dieser Schweizer Uhrzeit senden")
    ap.add_argument("--refresh-odds", action="store_true", help="Quoten sicher neu laden (kostet Credits)")
    ap.add_argument("--retune", action="store_true", help="Modell-Einstellungen neu optimieren (dauert einige Minuten)")
    ap.add_argument("--dry-run", action="store_true", help="Telegram-Text nur anzeigen")
    ap.add_argument("--skip-sim", action="store_true", help="Rückblick nicht neu rechnen")
    ap.add_argument("--once", action="store_true",
                    help="Morgen-Nachricht nur einmal pro Tag (falls schon gesendet: keine Nachricht, keine neuen Quoten)")
    ap.add_argument("--send-only", action="store_true", help="Nur die heutigen Top 5 an Telegram senden, nichts rechnen")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if args.send_only:
        return send_only(now)
    if args.once:
        prev = load_json(WEB / "botd.json", None) or {"days": []}
        today = B.local_day(now)
        if any(d.get("sent") for d in prev.get("days", []) if d["day"] == today and not d.get("retro")):
            print("Morgen-Nachricht wurde heute schon gesendet: nur aktualisieren.")
            args.notify = args.refresh_odds = False
            args.send_at = None
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

    # Quoten: automatisch höchstens einmal pro Tag (der 10-Uhr-Lauf holt sie ausdrücklich), sonst gespeicherte
    prev = load_json(WEB / "data.json", {})
    prev_odds = prev.get("odds", {})
    odds, credits, fetched = {}, prev_odds.get("credits"), prev_odds.get("fetched")
    key = os.getenv("ODDS_API_KEY")
    stale = not fetched or (now - datetime.fromisoformat(fetched)) > timedelta(hours=24)
    if key and (args.refresh_odds or stale):
        soon = [{**e, "dt": E.parse_date(e["date"])} for e in events
                if e["slug"] in C.DISPLAY and not e["completed"] and e["status"] not in espn.DEAD]
        soon = [e for e in soon if e["dt"] > now]
        odds, c = oddsapi.fetch(key, C.ODDS_KEYS, soon, now, C.ODDS_DAYS_AHEAD, C.ODDS_MIN_CREDITS)
        credits = c if c is not None else credits
        fetched = now.isoformat()
    elif key:
        print("Quoten: letzte Abfrage jünger als 24 Stunden, verwende gespeicherte Quoten")
    for u in prev.get("upcoming", []):      # bekannte Quoten behalten
        if u.get("odds") and u["id"] not in odds:
            odds[u["id"]] = u["odds"]

    upcoming = E.build_upcoming(pr, events, info, form, odds, now)
    prev_hist = load_json(WEB / "history.json", {}).get("history") or prev.get("history", [])
    rankings = E.build_rankings(pr, events, info, form, now)
    # Nachträgliche Tipps: alle gespielten Partien der 15 Wettbewerbe seit Saisonstart und
    # jedes Spiel, das in der App irgendwo antippbar ist (Form der angezeigten Teams).
    # Neue Lücken werden bei jedem Lauf automatisch gefüllt.
    shown = {u[s]["id"] for u in upcoming for s in ("home", "away")} | \
            {r["team"]["id"] for rows in rankings.values() for r in rows}
    form_ids = {x[8] for t in shown for x in fdet.get(t, [])}
    season_start = datetime(season, 7, 1, tzinfo=timezone.utc)
    prev_hist = E.backfill_history(prev_hist, events, params, info, now, season_start,
                                   extra_ids=form_ids, extra_since=now - timedelta(days=400))
    history = E.update_history(prev_hist, upcoming, by_id, now)
    paper = E.run_paper(load_json(WEB / "paper.json", None), upcoming, by_id, now)
    new_paper = [b for b in paper["bets"] if b.get("placed") == now.isoformat()]
    # Bets des Tages: um 10 Uhr (bzw. beim ersten Lauf danach) festlegen, danach nur auswerten
    local_now = now.astimezone(TZ)
    create = args.notify or args.dry_run or local_now.hour >= 10
    botd_state, new_day = B.update(load_json(WEB / "botd.json", None), upcoming, history, by_id, now, create)
    if new_day:
        print(f"Bets des Tages festgelegt: {len(new_day['bets'])} Tipps")

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
        "botd_today": next((d for d in botd_state["days"] if not d.get("retro") and d["day"] == B.local_day(now)), None),
        "botd_stats": {k: botd_state[k] for k in ("stats_live", "stats_retro", "stats_all")},
        "comp_names": {**{k: v[0] for k, v in C.DISPLAY.items()}, **C.OTHER_NAMES},
    }
    data["forms"] = {t: fdet[t] for t in shown if t in fdet}
    data["ratings"] = E.team_ratings(pr, rankings, shown, events, now)
    opp = {x[1] for t in data["forms"] for x in data["forms"][t]}
    data["teams"] = {t: info[t] for t in opp if t in info}
    # Wappen lokal und klein ablegen (schneller auf dem Handy)
    crest_ids = shown | opp | {x["home"].get("id") for x in history} | {x["away"].get("id") for x in history}
    data["crests"] = sorted(crests.sync({t: info[t] for t in crest_ids if t in info}, WEB / "crests"))
    data["telegram"] = TG.load(ROOT / "cache" / "telegram.json").get("title") or None
    write_json(WEB / "data.json", data)
    write_json(WEB / "paper.json", paper)
    write_json(WEB / "botd.json", botd_state)
    write_json(WEB / "history.json", {"generated": now.isoformat(), "history": history})
    if not args.skip_sim:
        sim_rows = E.build_sim(events, now, params, tuned_rows)
        write_json(WEB / "sim.json", {"generated": now.isoformat(), "w": params.w, "w_ou": params.w_ou,
                                      "rows": sim_rows})
    print(f"Web-Daten: {len(upcoming)} Spiele, {len(history)} in der Bilanz, "
          f"Spielgeld {paper['balance']:.2f} CHF")

    token, owner = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    tg_file = ROOT / "cache" / "telegram.json"
    tg = TG.find_group(token, owner, tg_file) if token and owner and not args.dry_run else {}
    if new_paper:
        ptext = paper_text(new_paper, paper, os.getenv("SITE_URL", ""))
        if args.dry_run or not token or not owner:
            print(ptext)
        else:
            try:
                TG.send(token, tg.get("chat_id") or owner, ptext, tg)
                TG.save(tg_file, tg)
                print(f"Telegram: Testlauf, {len(new_paper)} neue Wetten gemeldet.")
            except RuntimeError as err:
                print(f"Testlauf-Nachricht fehlgeschlagen: {err}")
    if not args.notify and not args.dry_run:
        return
    site = os.getenv("SITE_URL", "")
    today = B.local_day(now)
    day = next((d for d in botd_state["days"] if not d.get("retro") and d["day"] == today), None)
    text = telegram_text(day, botd_state, now, site)
    if args.dry_run or not token or not owner:
        print(text)
        return
    if args.send_at:
        wait_until(args.send_at)
    sent = False
    if tg.get("chat_id"):
        try:
            TG.send(token, tg["chat_id"], text, tg)
            TG.save(tg_file, tg)
            print(f"Telegram gesendet an Gruppe «{tg.get('title', '')}».")
            sent = True
        except RuntimeError as err:
            print(f"Gruppe nicht erreichbar ({err}), sende privat.")
    if not sent:
        TG.send(token, owner, text)
        print("Telegram gesendet (privat).")
    if day is not None:   # merken, damit spätere (verspätete) Läufe nicht nochmals senden
        day["sent"] = datetime.now(timezone.utc).isoformat()
        write_json(WEB / "botd.json", botd_state)


if __name__ == "__main__":
    sys.exit(main())

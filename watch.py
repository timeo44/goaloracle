"""Challenge-Wächter: meldet Anpfiff und Abpfiff (mit Resultat) der Spiele der Challenge-Wette.

Läuft alle paar Minuten (cron-job.org, job=watch), rechnet nichts am Modell und liest nur
web/challenge.json. Was schon gemeldet wurde, steht in cache/notify.json (nur dieser Wächter
schreibt diese Datei, deshalb gibt es keine Konflikte mit den grossen Läufen).
Ist die Wette mit einem Abpfiff entschieden, stösst er einen normalen Lauf an: der rechnet ab
und setzt sofort die nächste Wette.
"""
from __future__ import annotations

import html
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from markets import outcome_hit
from sources.espn import DEAD, FINAL_90, parse_date

TZ = ZoneInfo("Europe/Zurich")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; goaloracle/2.0)"}
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _chf(x: float) -> str:
    return f"{x:,.2f}".replace(",", "'")


def espn_status(slug: str, event: str) -> dict | None:
    try:
        r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary",
                         params={"event": event}, headers=HEADERS, timeout=20)
        j = r.json()
        comp = j["header"]["competitions"][0]
    except Exception:
        return None
    st = (comp.get("status") or {}).get("type") or {}
    cs = comp.get("competitors") or []
    home = next((c for c in cs if c.get("homeAway") == "home"), cs[0] if cs else {})
    away = next((c for c in cs if c.get("homeAway") == "away"), cs[1] if len(cs) > 1 else {})
    score = lambda c: int(c["score"]) if str(c.get("score", "")).isdigit() else None
    return {"state": st.get("state"), "name": st.get("name", ""), "completed": bool(st.get("completed")),
            "detail": st.get("shortDetail") or st.get("detail") or "", "hs": score(home), "as": score(away)}


def leg_result(leg: dict, s: dict) -> str | None:
    """won / lost / void, oder None solange nicht entschieden."""
    if s["name"] in DEAD:
        return "void"
    if not s["completed"] or s["hs"] is None:
        return None
    if s["name"] in FINAL_90:
        return "won" if outcome_hit(leg["key"], s["hs"], s["as"]) else "lost"
    return "void"   # Verlängerung / Elfmeterschiessen: zählt nach Challenge-Regeln nicht


def run(root: Path, label, send, dispatch, now: datetime | None = None, log=print) -> int:
    now = now or datetime.now(timezone.utc)
    chal = json.loads((root / "web" / "challenge.json").read_text())
    nf = root / "cache" / "notify.json"
    try:
        sent = json.loads(nf.read_text())
    except (OSError, ValueError):
        sent = {}
    site = os.getenv("SITE_URL", "")
    # Kandidaten: die letzte Wette der letzten zwei Versuche (eine eben verlorene zählt noch)
    bets = []
    for att in chal["attempts"][-2:]:
        if att["bets"]:
            bets.append((att, att["bets"][-1]))
    changed, decided = False, False
    for att, bet in bets:
        legs = bet["legs"]
        results = {}
        for leg in legs:
            k = f"{bet['placed']}|{leg['id']}|{leg['key']}"
            ko = parse_date(leg["kickoff"])
            if now < ko - timedelta(minutes=5) or now > ko + timedelta(hours=8):
                if leg.get("status") in ("won", "lost", "void"):
                    results[leg["id"]] = leg["status"]
                continue
            if sent.get(k + "|ft"):
                results[leg["id"]] = sent[k + "|ft"]
                continue
            s = espn_status(leg["comp"], leg["id"])
            if not s:
                log(f"Keine Daten für {leg['home']} – {leg['away']}")
                continue
            res = leg_result(leg, s)
            h, a = html.escape(leg["home"]), html.escape(leg["away"])
            tip = f"{html.escape(label(leg['key'], leg['home'], leg['away']))} ({leg['odds']:.2f})"
            win_amount = bet["stake"] * math.prod(l["odds"] for l in legs)
            if s["state"] == "in" and not sent.get(k + "|ko"):
                lines = [f"⚽ <b>Anpfiff</b> · {h} – {a}", f"Tipp: {tip}"]
                lines.append(f"Challenge Versuch {att['n']}: {_chf(bet['stake'])} → {_chf(win_amount)} CHF"
                             + (f" · {len(legs)}er-Kombi" if len(legs) > 1 else ""))
                if site:
                    lines.append(f'<a href="{site}vergleich.html">Live ansehen</a>')
                send("\n".join(lines))
                sent[k + "|ko"] = now.isoformat()
                changed = True
            if res:
                results[leg["id"]] = res
                score = f"{s['hs']}:{s['as']}" if s["hs"] is not None else "–"
                mark = {"won": "✅ richtig", "lost": "❌ falsch", "void": "↩️ zählt nicht"}[res]
                extra = "" if s["name"] in FINAL_90 or res != "void" else (
                    " (abgesagt)" if s["name"] in DEAD else " (Verlängerung)")
                lines = [f"🏁 <b>Abpfiff</b> · {h} {score} {a}", f"Tipp: {tip} {mark}{extra}"]
                # Ist die ganze Wette damit entschieden?
                st = [results.get(l["id"]) or (l["status"] if l.get("status") in ("won", "lost", "void") else None) for l in legs]
                if "lost" in st:
                    nw = sum(b["status"] == "won" for b in att["bets"])
                    lines.append(f"Wette verloren. Versuch {att['n']} endet nach {nw} {'Sieg' if nw == 1 else 'Siegen'}. "
                                 f"Neuer Versuch mit 100 CHF.")
                    decided = True
                elif None not in st:
                    q = math.prod(l["odds"] for l, r in zip(legs, st) if r == "won")
                    lines.append(f"Wette gewonnen! Versuch {att['n']} steht jetzt bei <b>{_chf(bet['stake'] * q)} CHF</b>.")
                    decided = True
                else:
                    lines.append(f"Noch offen: {st.count(None)} Spiel" + ("e" if st.count(None) > 1 else "") + " der Kombi")
                if site:
                    lines.append(f'<a href="{site}vergleich.html">Live ansehen</a>')
                send("\n".join(lines))
                sent[k + "|ft"] = res
                sent.setdefault(k + "|ko", now.isoformat())
                changed = True
    if changed:
        cutoff = (now - timedelta(days=14)).isoformat()
        sent = {k: v for k, v in sent.items() if k.split("|", 1)[0] >= cutoff}
        nf.parent.mkdir(parents=True, exist_ok=True)
        nf.write_text(json.dumps(sent, ensure_ascii=False, indent=1))
    if decided:
        log("Wette entschieden: normaler Lauf wird gestartet (abrechnen, nächste Wette setzen)")
        dispatch()
    log(f"Wächter fertig ({'Meldungen gesendet' if changed else 'nichts Neues'})")
    return 0

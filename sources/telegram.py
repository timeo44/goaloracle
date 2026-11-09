"""Telegram: Nachrichten senden und eine Gruppe automatisch finden.

Fügt Timeo den Bot zu einer Gruppe hinzu, sieht der Bot das beim nächsten Lauf
(getUpdates) und merkt sich die Gruppe in cache/telegram.json. Ab dann gehen die
Nachrichten in diese Gruppe. Gezählt wird nur eine Gruppe, in die der Besitzer
(TELEGRAM_CHAT_ID = seine eigene Telegram-ID) den Bot geholt oder dort geschrieben hat,
damit niemand sonst den Bot in seine Gruppe umleiten kann.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
GROUPS = ("group", "supergroup")


def _call(token, method, **params):
    r = requests.post(API.format(token=token, method=method), json=params, timeout=30)
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "description": r.text, "error_code": r.status_code}


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def find_group(token: str, owner: str, path: Path, log=print) -> dict:
    """Prüft neue Telegram-Ereignisse und aktualisiert die gespeicherte Gruppe."""
    state = load(path)
    res = _call(token, "getUpdates", allowed_updates=["message", "my_chat_member"], timeout=0)
    if not res.get("ok"):
        log(f"Telegram: Ereignisse nicht lesbar ({res.get('description')})")
        return state
    found = None
    for up in res.get("result", []):
        if up["update_id"] <= state.get("seen", 0):
            continue
        state["seen"] = up["update_id"]
        mc, msg = up.get("my_chat_member"), up.get("message")
        if mc and mc["chat"]["type"] in GROUPS:
            chat, status = mc["chat"], mc["new_chat_member"]["status"]
            if status in ("left", "kicked"):
                if str(chat["id"]) == str(state.get("chat_id")):
                    log(f"Telegram: Bot wurde aus «{chat.get('title')}» entfernt")
                    state.pop("chat_id", None); state.pop("title", None)
                    found = None
            elif str(mc["from"]["id"]) == str(owner):
                found = chat
        elif msg and msg["chat"]["type"] in GROUPS:
            if msg.get("migrate_to_chat_id") and str(msg["chat"]["id"]) == str(state.get("chat_id")):
                state["chat_id"] = msg["migrate_to_chat_id"]
            elif str(msg.get("from", {}).get("id")) == str(owner) and str(msg["chat"]["id"]) != str(state.get("chat_id")):
                found = msg["chat"]
    if found and str(found["id"]) != str(state.get("chat_id")):
        state.update(chat_id=found["id"], title=found.get("title", ""),
                     since=datetime.now(timezone.utc).isoformat(), greeted=False)
        log(f"Telegram: neue Gruppe «{state['title']}»")
    if state.get("chat_id") and not state.get("greeted"):
        r = send(token, state["chat_id"],
                 "⚽🔮 <b>GoalOracle</b> ist jetzt in dieser Gruppe.\n\n"
                 "Jeden Morgen um 10:00 kommen hier die 5 Bets des Tages.", state)
        state["greeted"] = r
    save(path, state)
    return state


def send(token: str, chat_id, text: str, state: dict | None = None) -> bool:
    """Sendet eine Nachricht. Wird eine Gruppe zur Supergruppe, wird die neue ID übernommen."""
    for _ in range(2):
        res = _call(token, "sendMessage", chat_id=chat_id, text=text[:4000], parse_mode="HTML",
                    disable_web_page_preview=True)
        if res.get("ok"):
            return True
        new = (res.get("parameters") or {}).get("migrate_to_chat_id")
        if not new:
            raise RuntimeError(f"Telegram-Fehler {res.get('error_code')}: {res.get('description')}")
        chat_id = new
        if state is not None:
            state["chat_id"] = new
    return False

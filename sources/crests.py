"""Wappen lokal zwischenspeichern: einmal von ESPN laden, auf 96 px verkleinern, als WebP ablegen.

ESPN liefert 500×500-PNGs (oft 30–60 KB). Auf dem Handy bremsen hunderte davon die App.
Die verkleinerten Bilder (ca. 2–4 KB) liegen in web/crests/ und kommen von der eigenen Seite.
"""
from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SIZE = 96
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; goaloracle/2.0)"}


def _fetch(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and len(r.content) > 200:
            return r.content
    except requests.RequestException:
        pass
    return None


def sync(teams: dict[str, dict], folder: Path, max_new: int = 800, log=print) -> set[str]:
    """Lädt fehlende Wappen. Gibt die IDs zurück, für die ein lokales Wappen existiert."""
    try:
        from PIL import Image
    except ImportError:
        log("Wappen: Pillow fehlt, verwende ESPN-Bilder")
        return set()
    folder.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in folder.glob("*.webp")}
    miss_f = folder / "missing.json"
    try:
        missing = json.loads(miss_f.read_text())
    except (OSError, ValueError):
        missing = {}
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    todo = [(tid, t["logo"]) for tid, t in teams.items()
            if t.get("logo", "").startswith("http") and tid not in have
            and missing.get(tid, "") < week_ago][:max_new]

    def work(item):
        tid, url = item
        data = _fetch(url)
        if not data:
            return tid, False
        try:
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            img.thumbnail((SIZE, SIZE), Image.LANCZOS)
            canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            canvas.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2), img)
            canvas.save(folder / f"{tid}.webp", "WEBP", quality=88, method=6)
            return tid, True
        except Exception:
            return tid, False

    ok = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for tid, success in pool.map(work, todo):
            if success:
                have.add(tid)
                missing.pop(tid, None)
                ok += 1
            else:
                missing[tid] = now.isoformat()
    miss_f.write_text(json.dumps(missing))
    log(f"Wappen: {ok} neu geladen, {len(have)} lokal, {len(missing)} ohne Bild")
    return have

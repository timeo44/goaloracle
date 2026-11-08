# ⚽🔮 GoalOracle

Predict the game. Beat the gut feeling.

Analysiert jeden Morgen alle Premier-League-Teams, schickt die Tipps per Telegram und aktualisiert eine Web-App, die du mit Kollegen teilen kannst:

- **Tipps** für die Spiele der nächsten 4 Tage: Wahrscheinlichkeiten 1/X/2, Tipp mit Sicherheit, Endresultat-Tipp, xG, Über 2.5, beide treffen
- **Stärke-Ranking** aller 20 Teams mit erwarteten Toren für/gegen und Form der letzten 5 Spiele (S/U/N)
- **Web-App** (Ordner `web/`) mit Tipps für 10 Tage, Resultat-Heatmap pro Spiel, Ranking und **Bilanz** (jeder Tipp wird nach dem Spiel ausgewertet)

## Wie es funktioniert

1. Lädt die laufende Saison (Resultate + Spielplan) von football-data.org und die zwei Vorsaisons von football-data.co.uk.
2. Trainiert ein **Dixon-Coles-Modell**: Jedes Team bekommt eine Angriffs- und Abwehrstärke, dazu Heimvorteil und eine Korrektur für tiefe Resultate (0:0, 1:1). Neuere Spiele zählen mehr.
3. Berechnet für jedes Spiel die Wahrscheinlichkeit jedes Resultats von 0:0 bis 10:10. Daraus folgen 1X2, Endresultat usw.

**Endresultat-Tipp:** Das wahrscheinlichste Resultat insgesamt. Passt es nicht zum 1X2-Tipp (z. B. Tipp «1», aber 1:1 am wahrscheinlichsten), steht zusätzlich das beste Resultat, das zum Tipp passt.

## Einrichtung (ca. 15 Minuten)

### 1. API-Token für die Fussballdaten
Gratis registrieren auf <https://www.football-data.org/client/register>. Der Token kommt per Mail.

### 2. Telegram-Bot
1. In Telegram **@BotFather** öffnen → `/newbot` → Name wählen → du bekommst den **Bot-Token**.
2. Deinem neuen Bot eine beliebige Nachricht schicken.
3. Im Browser öffnen: `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates` → bei `"chat":{"id": ...}` steht deine **Chat-ID**.

### 3. GitHub
1. Neues **privates** Repository anlegen und diesen Ordner hochladen.
2. *Settings → Secrets and variables → Actions → New repository secret*, drei Secrets anlegen:
   - `FOOTBALL_DATA_TOKEN`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. *Actions → GoalOracle → Run workflow* zum ersten Testen.

Danach läuft der Bot täglich um 08:00 Uhr (Winterzeit) bzw. 09:00 Uhr (Sommerzeit). Die Uhrzeit änderst du in `.github/workflows/daily.yml`. Jeder Lauf speichert die neuen Tipps in `web/data.json`.

### 4. Web-App auf Netlify
1. Auf <https://app.netlify.com> **Add new project → Import an existing project → GitHub** wählen und das Repo `goaloracle` auswählen.
2. Die Einstellungen kommen aus `netlify.toml` (Publish directory `web`, kein Build-Befehl). Einfach **Deploy** klicken.
3. Unter *Project configuration → Change project name* den Namen `goaloracle` (oder `goaloracle-timeo`) wählen. Die Adresse ist dann `https://goaloracle.netlify.app`.
4. Jedes Mal, wenn der Bot neue Tipps speichert, aktualisiert Netlify die Seite automatisch.

Auf dem iPhone: Seite in Safari öffnen → Teilen → **Zum Home-Bildschirm**. Dann startet GoalOracle wie eine App.

## Lokal laufen lassen

```bash
pip install -r requirements.txt
export FOOTBALL_DATA_TOKEN=...
python bot.py --dry-run           # Ausgabe im Terminal, nichts senden
python bot.py --days 7 --dry-run  # Tipps für die nächsten 7 Tage
python bot.py --backtest --dry-run   # Trefferquote der letzten 180 Tage
python bot.py --web web/data.json --no-telegram   # nur Web-Daten schreiben
python tests/test_offline.py      # Selbsttest ohne Internet
python tests/make_demo.py         # Demo-Daten (tests/demo.json) für Design-Tests
```

## Backtest – wie gut ist er wirklich?

`--backtest` (oder in GitHub: *Run workflow → backtest*) tippt rückwirkend jeden Spieltag der letzten 180 Tage, jeweils nur mit den Daten, die vor dem Spieltag bekannt waren. Realistische Werte für so ein Modell:

| | typisch |
|---|---|
| 1X2 richtig | 50–55 % |
| Exaktes Resultat | 10–13 % |
| Log-Loss | ~0.98–1.00 |

Die Buchmacher (auch Sporttipp) haben ähnlich gute oder bessere Modelle und eine Marge in den Quoten. Ein Tipp mit 55 % Wahrscheinlichkeit bringt nur Gewinn, wenn die Quote über 1.82 liegt (1 / 0.55).

## Ideen für später

- Sporttipp-Quoten eintragen → Bot zeigt nur Tipps mit **Value** (Modell-Wahrscheinlichkeit × Quote > 1)
- Weitere Ligen (Bundesliga, Serie A …) – football-data.org deckt sie gratis ab
- Verletzungen/Sperren als manuelle Anpassung

## Hinweise

- Gratis-Plan football-data.org: 10 Anfragen pro Minute, Resultate leicht verzögert. Der Bot braucht 1 Anfrage pro Lauf.
- Fehlt eine Vorsaison (Quelle nicht erreichbar), läuft der Bot trotzdem und zeigt eine Warnung.
- GitHub Actions ist für private Repos bis 2000 Minuten/Monat gratis; ein Lauf dauert ca. 1 Minute.

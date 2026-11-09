# ⚽🔮 GoalOracle

Predict the game. Beat the gut feeling.

Statistische Tipps für **Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, Europa League, Conference League, Nations League** und die Pokale **FA Cup, League Cup, DFB-Pokal, Coppa Italia, Copa del Rey, Coupe de France**.

Jeden Morgen um **10:00** kommt die Telegram-Nachricht. Dafür:
1. lädt der Bot alle Resultate und Spielpläne aus über 60 Wettbewerben (ESPN), Schüsse aufs Tor, Ecken, Karten und historische Quoten (football-data.co.uk) und aktuelle Marktquoten (The Odds API),
2. trainiert ein gemeinsames Dixon-Coles-Modell über alle Clubs, mit eigenem Heimvorteil je Wettbewerb und dem Niveau der eigenen Liga als Vorwissen, dazu ein Schuss-Modell, ein Modell für Nationalteams und Modelle für Ecken und Karten,
3. mischt Modell und Marktquoten (Anteil wird per Rückblick optimiert) und berechnet daraus alle Märkte und Kombis exakt aus der Resultat-Matrix,
4. aktualisiert die Web-App, wertet die Bilanz aus und wettet im Spielgeld-Konto mit.

Jeden Montag früh optimiert sich das Modell selbst (Zeitgewichtung, Schuss-Anteil, Markt-Anteil) per Rückblick auf die letzten 15 Monate.

## Manuell neu rechnen

In der App unter **Einstellungen → Modell**: Optionen wählen (Telegram senden, Quoten neu laden, neu optimieren) und **Modell jetzt neu rechnen**. Dafür einmalig einen GitHub-Schlüssel (Fine-grained token, nur dieses Repo, Actions: Read and write) auf dem Gerät speichern. Ohne Schlüssel führt der Knopf zur GitHub-Seite mit **Run workflow**.

Alle 2 Stunden aktualisiert der Bot Resultate, Spielpläne, Bilanz und Prognosen (ohne Nachricht). Neue Quoten holt nur der 10-Uhr-Lauf oder ein manueller Lauf mit dem Schalter «Quoten neu laden». Das schont die 500 Gratis-Credits. Die offene App lädt neue Daten alle 10 Minuten selbst nach.

## Web-App

`https://<github-name>.github.io/goaloracle/`

- **Spiele**: alle Spiele der nächsten 7 Tage, antippen für beste Tipps, beste Kombis, alle Märkte und die Resultat-Heatmap. Oben Kombi-Vorschläge über mehrere Spiele.
- **Top 5**: die fünf Bets des Tages. Werden jeden Morgen um 10:00 festgelegt, per Telegram verschickt und danach nicht mehr verändert. Dazu die Bilanz (Trefferquote, Gewinn in Einheiten, ROI, Tage mit allen 5 richtig), live und nachträglich berechnet (`web/botd.json`).
- **Testlauf** (unter Einstellungen): *Rückblick simulieren* (Budget, Risiko, Einsatzart, Einzel- oder Kombiwetten über die letzten Saisons mit echten historischen Quoten) und *Spielgeld-Konto* (virtuelles Konto, das ab dem ersten Lauf täglich mitwettet).
- **Ranking**: Europa Top 30 und Stärke-Tabellen der Top-5-Ligen.
- **Bilanz**: jeder Tipp wird nach dem Spiel ausgewertet.
- **Einstellungen** (Regler-Symbol oben rechts): Tipp-Arten ein/aus (Ecken und Karten standardmässig aus), Wettbewerbe, Risikoprofil. Gilt pro Gerät.

## Einrichtung

GitHub-Secrets (*Settings → Secrets and variables → Actions*):

| Secret | Woher |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `TELEGRAM_CHAT_ID` | `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| `ODDS_API_KEY` | gratis auf <https://the-odds-api.com> (500 Credits/Monat) |

Ohne `ODDS_API_KEY` läuft alles, aber ohne Value-Erkennung und ohne Spielgeld-Wetten.

GitHub Pages: *Settings → Pages → Source: GitHub Actions*. Das Repo muss öffentlich sein (Tokens bleiben in den Secrets geheim).

## Anpassen

Alles in `config.py`: Wettbewerbe, Trainings-Ligen, Risikoprofile, Regeln fürs Spielgeld-Konto (`PAPER`), wie viele Tage voraus Quoten geholt werden. Die Modell-Einstellungen stehen nach dem Optimieren in `cache/tuning.json`.

## Lokal

```bash
pip install -r requirements.txt
python bot.py --dry-run          # alles rechnen, Telegram-Text nur anzeigen
python bot.py --retune --dry-run # mit Optimierung
python tests/fake_world.py       # Offline-Test mit simulierter Fussballwelt
```

## Ehrlich gesagt

Buchmacher haben gute Modelle und eine Marge. Value-Tipps sind Tipps, bei denen das Modell anderer Meinung ist als der Markt, und das Modell kann sich irren. Der Testlauf zeigt, wie es in der Vergangenheit gelaufen wäre. Das ist keine Garantie für die Zukunft.

Daten: ESPN (inoffizielle Schnittstelle, kann sich ändern), football-data.co.uk, The Odds API.

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

Quoten werden bei manuellen Läufen nur neu geholt, wenn die letzte Abfrage älter als 6 Stunden ist oder du es ausdrücklich wählst. Das schont die 500 Gratis-Credits.

## Web-App

`https://<github-name>.github.io/goaloracle/`

- **Spiele**: alle Spiele der nächsten 7 Tage, antippen für beste Tipps, beste Kombis, alle Märkte und die Resultat-Heatmap. Oben Kombi-Vorschläge über mehrere Spiele.
- **Testlauf**: *Rückblick simulieren* (Budget, Risiko, Einsatzart, Einzel- oder Kombiwetten über die letzten Saisons mit echten historischen Quoten) und *Spielgeld-Konto* (virtuelles Konto, das ab dem ersten Lauf täglich mitwettet).
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

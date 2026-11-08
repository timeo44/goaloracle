# ⚽🔮 GoalOracle

Predict the game. Beat the gut feeling.

Statistische Tipps für **Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, Europa League, Conference League, Nations League** und die Pokale **FA Cup, League Cup, DFB-Pokal, Coppa Italia, Copa del Rey, Coupe de France**.

Jeden Morgen um 8 Uhr:
1. lädt der Bot alle Resultate und Spielpläne (ESPN), historische Quoten, Ecken und Karten (football-data.co.uk) und aktuelle Marktquoten (The Odds API),
2. trainiert ein gemeinsames Dixon-Coles-Modell über rund 600 Clubs (Ligen, Pokale und Europacups zusammen, damit Teams aus verschiedenen Ländern vergleichbar sind) plus ein eigenes Modell für Nationalteams,
3. berechnet für jedes Spiel alle Märkte und Kombis im selben Spiel exakt aus der Resultat-Matrix,
4. schickt die Top-Tipps per Telegram, aktualisiert die Web-App und wettet im Spielgeld-Konto mit.

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

Alles in `config.py`: Wettbewerbe, Risikoprofile, Regeln fürs Spielgeld-Konto (`PAPER`), wie viele Tage voraus Quoten geholt werden (spart Credits).

## Lokal

```bash
pip install -r requirements.txt
python bot.py --dry-run          # alles rechnen, Telegram-Text nur anzeigen
python tests/fake_world.py       # Offline-Test mit simulierter Fussballwelt
```

## Ehrlich gesagt

Buchmacher haben gute Modelle und eine Marge. Value-Tipps sind Tipps, bei denen das Modell anderer Meinung ist als der Markt, und das Modell kann sich irren. Der Testlauf zeigt, wie es in der Vergangenheit gelaufen wäre. Das ist keine Garantie für die Zukunft.

Daten: ESPN (inoffizielle Schnittstelle, kann sich ändern), football-data.co.uk, The Odds API.

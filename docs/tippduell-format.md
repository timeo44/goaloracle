# Format «tippduell/1»

Gemeinsames Format, damit zwei Tipp-Bots auf einer Seite verglichen werden können.
Jeder Bot veröffentlicht nach jedem Lauf **eine JSON-Datei** unter einer öffentlichen URL
(ohne Login, mit CORS, z. B. GitHub Pages oder raw.githubusercontent.com).

GoalOracle: https://timeo44.github.io/goaloracle/duel.json
Vergleichsseite: https://timeo44.github.io/goaloracle/vergleich.html

## Aufbau

```json
{
  "format": "tippduell/1",
  "updated": "2026-11-12T17:13:00+00:00",
  "bot": { "name": "GoalOracle", "owner": "Timeo", "url": "https://…" },
  "tips": [ Tipp, … ],
  "challenge": Challenge | null
}
```

Die Vergleichsseite vergleicht **nur die Challenge**. `tips` ist optional und darf `[]` sein.

### Tipp (optional: die besten Tipps des Tages, max. 5 pro Tag)

| Feld | Typ | Bedeutung |
|---|---|---|
| `id` | string | eindeutig und stabil (bleibt bei jedem Lauf gleich) |
| `day` | `YYYY-MM-DD` | Tag, an dem getippt wurde (Schweizer Zeit) |
| `rank` | int | 1 = bester Tipp des Tages |
| `placed` | ISO-Zeit | wann der Tipp festgelegt wurde (muss **vor** dem Anpfiff liegen) |
| `kickoff` | ISO-Zeit mit Zeitzone | Anpfiff |
| `competition` | string | z. B. `Premier League`, `Champions League`, `Nations League` |
| `home`, `away` | string | Teamnamen auf Englisch, wie ESPN/Buchmacher (`Bayern Munich`, `Inter Milan`) |
| `pick` | string | Code, siehe unten |
| `label` | string | lesbarer Text, z. B. `Sieg Arsenal`, `Über 2.5 Tore` |
| `odds` | number | Quote des Tipps |
| `odds_type` | `market` \| `fair` | `market` = echte Buchmacher-Quote, `fair` = 1 / Wahrscheinlichkeit |
| `probability` | number 0–1 | Chance laut Modell |
| `status` | `open` \| `won` \| `lost` \| `void` | `void` = abgesagt / Verlängerung |
| `score` | `"2:1"` \| null | Endstand nach 90 Minuten |
| `retro` | bool | `true`, wenn nachträglich berechnet (zählt im Vergleich nicht) |

**Pick-Codes** (90 Minuten):
`1`, `X`, `2`, `1X`, `X2`, `12`, `O2.5` / `U2.5` (jede .5-Linie, z. B. `O1.5`, `U3.5`),
`BTTS_YES`, `BTTS_NO`, `HOME_SCORES`, `AWAY_SCORES`, `HOME_O1.5`, `AWAY_O1.5`,
`CS_2-1` (genaues Resultat). Mehrere Ereignisse im selben Spiel: mit `+` verbinden (`1+O2.5`).
Alles andere: `OTHER` (dann zählt nur `label`).

### Challenge (100 → 100'000 mit einer Wette nach der anderen)

```json
{
  "start": 100, "goal": 100000, "currency": "CHF",
  "attempts": [
    {
      "n": 1, "started": "ISO", "ended": "ISO" | null,
      "status": "open" | "lost" | "won",
      "bank": 190.0, "peak": 190.0,
      "bets": [
        {
          "placed": "ISO", "stake": 100.0, "odds": 1.9, "probability": 0.5,
          "status": "open" | "won" | "lost" | "void", "payout": 190.0 | null,
          "legs": [
            { "kickoff": "ISO", "competition": "…", "home": "…", "away": "…",
              "pick": "2", "label": "Sieg Belgium", "odds": 1.9,
              "status": "open" | "won" | "lost" | "void", "score": "1:2" | null }
          ]
        }
      ]
    }
  ]
}
```
Einzelwette = 1 Leg, Kombi = mehrere Legs. `bank` = aktueller Betrag des Versuchs,
`peak` = Höchststand. Ein verlorener Versuch hat `status: "lost"` und `bank: 0`.

Regeln der Challenge: Start 100, immer nur eine offene Wette, der ganze Betrag wird weiter
eingesetzt, jede Wette etwa Quote 2, eine verlorene Wette beendet den Versuch.

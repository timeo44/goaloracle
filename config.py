"""Einstellungen: Wettbewerbe, Datenquellen, Risikoprofile."""

# Wettbewerbe, für die GoalOracle Tipps zeigt: ESPN-Kürzel -> (Name, Kurzname, Typ)
DISPLAY = {
    "eng.1": ("Premier League", "PL", "club"),
    "esp.1": ("La Liga", "LaLiga", "club"),
    "ger.1": ("Bundesliga", "BL", "club"),
    "ita.1": ("Serie A", "SA", "club"),
    "fra.1": ("Ligue 1", "L1", "club"),
    "uefa.champions": ("Champions League", "UCL", "club"),
    "uefa.europa": ("Europa League", "UEL", "club"),
    "uefa.europa.conf": ("Conference League", "UECL", "club"),
    "uefa.nations": ("Nations League", "UNL", "nation"),
    "eng.fa": ("FA Cup", "FA Cup", "club"),
    "eng.league_cup": ("League Cup", "EFL Cup", "club"),
    "ger.dfb_pokal": ("DFB-Pokal", "Pokal", "club"),
    "ita.coppa_italia": ("Coppa Italia", "Coppa", "club"),
    "esp.copa_del_rey": ("Copa del Rey", "Copa", "club"),
    "fra.coupe_de_france": ("Coupe de France", "CdF", "club"),
}

# Zusätzliche Wettbewerbe nur fürs Training (machen Teams vergleichbar)
TRAIN_CLUB_LEAGUES = [
    "eng.2", "eng.3", "eng.4", "ger.2", "ita.2", "esp.2", "fra.2",
    "ned.1", "por.1", "bel.1", "sco.1", "tur.1", "aut.1", "sui.1", "gre.1", "den.1",
]
TRAIN_NATION = [
    "fifa.friendly", "fifa.worldq.uefa", "uefa.euroq", "uefa.euro", "fifa.world",
    "fifa.worldq.conmebol", "fifa.worldq.concacaf", "fifa.worldq.caf", "fifa.worldq.afc",
]

# Ligen (nicht Pokale): Teams darin bekommen kein "schwach"-Vorwissen
LEAGUE_SLUGS = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", *TRAIN_CLUB_LEAGUES}
TOP5 = ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1"]

# football-data.co.uk Datei -> ESPN-Liga (für Quoten, Ecken, Karten)
FDCO_MAP = {
    "E0": "eng.1", "E1": "eng.2", "E2": "eng.3", "E3": "eng.4",
    "D1": "ger.1", "D2": "ger.2", "I1": "ita.1", "I2": "ita.2",
    "SP1": "esp.1", "SP2": "esp.2", "F1": "fra.1", "F2": "fra.2",
    "N1": "ned.1", "P1": "por.1", "B1": "bel.1", "SC0": "sco.1", "T1": "tur.1", "G1": "gre.1",
}

# The Odds API: ESPN-Kürzel -> mögliche Sport-Schlüssel (nur aktive werden genutzt)
ODDS_KEYS = {
    "eng.1": ["soccer_epl"],
    "esp.1": ["soccer_spain_la_liga"],
    "ger.1": ["soccer_germany_bundesliga"],
    "ita.1": ["soccer_italy_serie_a"],
    "fra.1": ["soccer_france_ligue_one"],
    "uefa.champions": ["soccer_uefa_champs_league"],
    "uefa.europa": ["soccer_uefa_europa_league"],
    "uefa.europa.conf": ["soccer_uefa_europa_conference_league"],
    "uefa.nations": ["soccer_uefa_nations_league"],
    "eng.fa": ["soccer_fa_cup"],
    "eng.league_cup": ["soccer_england_efl_cup"],
    "ger.dfb_pokal": ["soccer_germany_dfb_pokal"],
    "ita.coppa_italia": ["soccer_italy_coppa_italia"],
    "esp.copa_del_rey": ["soccer_spain_copa_del_rey"],
    "fra.coupe_de_france": ["soccer_france_coupe_de_france"],
}
ODDS_MIN_CREDITS = 25        # darunter keine Abfragen mehr bis zum nächsten Monat
ODDS_DAYS_AHEAD = 3          # Quoten nur für Spiele der nächsten 3 Tage holen (spart Credits)

HISTORY_START = (2024, 7)    # ab hier Resultate laden (Jahr, Monat)
DAYS_AHEAD = 7               # Tipps in der Web-App
SPORTTIPP_DISCOUNT = 0.07    # Sporttipp-Quoten liegen grob 7 % unter dem Marktschnitt

# Risikoprofile: Quotenbereich, Mindest-Value, Kelly-Anteil, max. Spiele pro Kombi
RISK = {
    "vorsichtig": {"min_odds": 1.25, "max_odds": 2.0, "min_ev": 0.02, "kelly": 0.15, "max_legs": 2},
    "ausgewogen": {"min_odds": 1.4, "max_odds": 3.2, "min_ev": 0.03, "kelly": 0.25, "max_legs": 3},
    "mutig": {"min_odds": 1.8, "max_odds": 8.0, "min_ev": 0.05, "kelly": 0.4, "max_legs": 4},
}

# Spielgeld-Konto (läuft ab dem ersten Lauf automatisch mit)
PAPER = {
    "start_budget": 1000.0,
    "risk": "ausgewogen",
    "stake_mode": "percent",   # "fix" (CHF pro Tipp) oder "percent" (% vom Kontostand)
    "stake": 2.0,
    "max_bets_per_day": 6,
    "markets": ["1X2", "OU"],  # nur Märkte mit echten Quoten
}

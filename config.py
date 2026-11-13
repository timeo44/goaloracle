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
# Unterbau der Top-5 (wichtig für Pokale) und weitere europäische Ligen (wichtig für Europacups).
# Kürzel, die ESPN nicht kennt, kosten nur beim ersten Lauf eine Abfrage pro Monat und werden dann übersprungen.
TRAIN_CLUB_LEAGUES = [
    "eng.2", "eng.3", "eng.4", "eng.5", "ger.2", "ger.3", "ita.2", "ita.3", "esp.2", "fra.2", "fra.3",
    "ned.1", "ned.2", "por.1", "por.2", "bel.1", "bel.2", "sco.1", "sco.2", "tur.1", "aut.1", "sui.1", "sui.2",
    "gre.1", "den.1", "nor.1", "swe.1", "pol.1", "cze.1", "cro.1", "srb.1", "ukr.1", "rou.1", "isr.1",
    "cyp.1", "hun.1", "svk.1", "svn.1", "bul.1", "irl.1", "fin.1", "isl.1", "kaz.1", "aze.1", "geo.1",
]
TRAIN_NATION = [
    "fifa.friendly", "fifa.worldq.uefa", "uefa.euroq", "uefa.euro", "fifa.world",
    "fifa.worldq.conmebol", "fifa.worldq.concacaf", "fifa.worldq.caf", "fifa.worldq.afc", "fifa.worldq.ofc",
    "concacaf.nations.league", "concacaf.gold", "conmebol.america", "caf.nations", "afc.asian.cup",
]

# Namen der Trainings-Wettbewerbe (für die Form-Anzeige)
OTHER_NAMES = {
    "eng.2": "Championship", "eng.3": "League One", "eng.4": "League Two", "ger.2": "2. Bundesliga",
    "ita.2": "Serie B", "esp.2": "LaLiga 2", "fra.2": "Ligue 2", "ned.1": "Eredivisie", "por.1": "Liga Portugal",
    "bel.1": "Pro League", "sco.1": "Premiership", "tur.1": "Süper Lig", "aut.1": "Bundesliga AT",
    "sui.1": "Super League", "gre.1": "Super League GR", "den.1": "Superliga", "fifa.friendly": "Testspiel",
    "fifa.worldq.uefa": "WM-Quali", "uefa.euroq": "EM-Quali", "uefa.euro": "EM", "fifa.world": "WM",
    "fifa.worldq.conmebol": "WM-Quali", "fifa.worldq.concacaf": "WM-Quali", "fifa.worldq.caf": "WM-Quali",
    "fifa.worldq.afc": "WM-Quali", "fifa.worldq.ofc": "WM-Quali", "eng.5": "National League",
    "ger.3": "3. Liga", "ita.3": "Serie C", "fra.3": "National", "ned.2": "Eerste Divisie",
    "por.2": "Liga Portugal 2", "bel.2": "Challenger Pro League", "sco.2": "Championship SCO",
    "sui.2": "Challenge League", "nor.1": "Eliteserien", "swe.1": "Allsvenskan", "pol.1": "Ekstraklasa",
    "cze.1": "Chance Liga", "cro.1": "HNL", "srb.1": "Superliga SRB", "ukr.1": "Premier Liga UKR",
    "rou.1": "Liga 1 ROU", "isr.1": "Ligat ha'Al", "cyp.1": "First Division CYP", "hun.1": "NB I",
    "svk.1": "Niké Liga", "svn.1": "PrvaLiga", "bul.1": "First League BUL", "irl.1": "League of Ireland",
    "fin.1": "Veikkausliiga", "isl.1": "Besta deild", "kaz.1": "Premier League KAZ", "aze.1": "Premyer Liqa",
    "geo.1": "Erovnuli Liga", "concacaf.nations.league": "Nations League CONCACAF",
    "concacaf.gold": "Gold Cup", "conmebol.america": "Copa América", "caf.nations": "Afrika-Cup",
    "afc.asian.cup": "Asienmeisterschaft",
}

# Ligen (nicht Pokale): Teams darin bekommen kein "schwach"-Vorwissen
LEAGUE_SLUGS = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", *TRAIN_CLUB_LEAGUES}
TOP5 = ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1"]

# football-data.co.uk Datei -> ESPN-Liga (für Quoten, Ecken, Karten)
FDCO_MAP = {
    "E0": "eng.1", "E1": "eng.2", "E2": "eng.3", "E3": "eng.4",
    "D1": "ger.1", "D2": "ger.2", "I1": "ita.1", "I2": "ita.2",
    "SP1": "esp.1", "SP2": "esp.2", "F1": "fra.1", "F2": "fra.2",
    "N1": "ned.1", "P1": "por.1", "B1": "bel.1", "SC0": "sco.1", "SC1": "sco.2", "T1": "tur.1",
    "G1": "gre.1", "EC": "eng.5",
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
MIN_GAMES = 12               # so viele Spiele im letzten Jahr braucht ein Team für Value-Tipps
DAYS_AHEAD = 7               # Tipps in der Web-App

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
    # Kombi (höchstens eine pro Tag) nur, wenn sie sehr wahrscheinlich ist
    "combo_min_leg_p": 0.70,   # jeder Teil mindestens 70 %
    "combo_min_p": 0.55,       # die ganze Kombi mindestens 55 %
    "combo_min_odds": 1.35,    # sonst lohnt sich die Kombi nicht
    "combo_stake_factor": 0.5, # halber Einsatz
}


# Telegram: welche Nachrichten automatisch gesendet werden.
# Die Challenge (neue Wette, Anpfiff, Abpfiff mit Resultat) wird immer gemeldet.
TELEGRAM = {
    "top5": False,   # tägliche Top 5 um 10:00 (der Knopf «Top 5 an Telegram senden» geht trotzdem)
    "paper": False,  # Wetten des Spielgeld-Kontos (Testlauf)
}

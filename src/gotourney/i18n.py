"""Texts of the output PDFs (pairing, award ceremony) in several languages.

Built in: English, German, French. "custom" reads the texts from a translation file (TOML),
for which ``translation_template()`` gives a commented example (the German texts).
"""

from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path

LANGUAGES = ("en", "de", "fr", "custom")
LANGUAGE_ALIASES = {
    "en": "en", "english": "en", "englisch": "en", "anglais": "en",
    "de": "de", "german": "de", "deutsch": "de", "allemand": "de",
    "fr": "fr", "french": "fr", "französisch": "fr", "francais": "fr", "français": "fr",
    "custom": "custom",
}
TRANSLATION_FILE = "translation.toml"

# key -> (description for the translation file, placeholders)
KEYS = {
    "pairing_title": ("title of the pairing PDF", "{tournament} {round}"),
    "pairing_boards": ("line under the title", "{n}"),
    "pairing_footer": ("page footer", "{round} {page}"),
    "col_board": ("column: board number", ""),
    "col_white": ("column: white player", ""),
    "col_white_win": ("column: white wins (\\n = line break)", ""),
    "col_draw": ("column: draw / jigo", ""),
    "col_black_win": ("column: black wins (\\n = line break)", ""),
    "col_black": ("column: black player", ""),
    "col_handicap": ("column: handicap (\\n = line break)", ""),
    "alpha_title": ("title of the alphabetical pairing list", "{tournament} {round}"),
    "alpha_not_paired": ("alphabetical list: player who does not play this round", ""),
    "col_player": ("alphabetical list column: player", ""),
    "col_colour": ("alphabetical list column: colour", ""),
    "col_opponent": ("alphabetical list column: opponent", ""),
    "standings_title": ("title of the standings PDF", "{tournament} {round}"),
    "standings_start": ("title of the standings PDF before round 1", "{tournament}"),
    "standings_footer": ("page footer of the standings PDF", "{page}"),
    "standings_legend": ("explanation under the standings table", ""),
    "col_place": ("standings column: place", ""),
    "col_name": ("standings column: name", ""),
    "col_rank": ("standings column: rank", ""),
    "col_tgor": ("standings column: TGoR", ""),
    "col_round": ("standings column: one round", "{round}"),
    "awards_title": ("award slides: title slide", ""),
    "award_place": ("award slide: final place", "{place}"),
    "award_games": ("award slide: games won", "{wins} {games}"),
    "award_tgor": ("award slide: final TGoR and change", "{tgor} {change}"),
    "prize_place": ("default prize title, type place", "{place} {ordinal}"),
    "prize_wins": ("default prize title, type wins", "{wins} {games}"),
    "prize_best_in_group": ("default prize title, type best_in_group", "{group}"),
    "prize_rating_gain": ("default prize title, type rating_gain", ""),
    "sys_title": ("system summary PDF: title", "{tournament}"),
    "sys_subtitle": ("system summary: line under the title", ""),
    "sys_intro": ("system summary: the system in one sentence", ""),
    "sys_h_start": ("system summary heading: starting rating", ""),
    "sys_start": ("system summary: starting rating", ""),
    "sys_bar": ("system summary: top bar", "{bar}"),
    "sys_h_update": ("system summary heading: after every round", ""),
    "sys_update": ("system summary: rating update", "{k}"),
    "sys_example": ("system summary: example of an even game", "{rating} {gain} {loss}"),
    "sys_h_pairing": ("system summary heading: pairing", ""),
    "sys_pairing": ("system summary: pairing", ""),
    "sys_rule_avoid_same": ("system summary: rule 'avoid same value'", "{field} {points}"),
    "sys_rule_prefer_same": ("system summary: rule 'prefer same value'", "{field} {points}"),
    "sys_rule_forbid_same": ("system summary: rule 'never same value'", "{field}"),
    "sys_rule_require_same": ("system summary: rule 'only same value'", "{field}"),
    "sys_h_handicap": ("system summary heading: handicap", ""),
    "sys_handicap": ("system summary: full handicap", ""),
    "sys_handicap_reduced": ("system summary: reduced handicap", "{reduction}"),
    "sys_floor": ("system summary: handicap floor", "{floor}"),
    "sys_komi": ("system summary: komi and colours", "{even} {handicap}"),
    "sys_h_more": ("system summary heading: other rules", ""),
    "sys_joker": ("system summary: odd number of players", ""),
    "sys_results": ("system summary: jigo and forfeits", ""),
    "sys_h_winner": ("system summary heading: winner", ""),
    "sys_winner": ("system summary: winner and tie-break", "{rounds}"),
    "sys_h_game": ("system summary heading: rules and time", ""),
    "sys_rules_japanese": ("system summary: Japanese rules", ""),
    "sys_rules_chinese": ("system summary: Chinese rules", ""),
    "sys_rules_aga": ("system summary: AGA rules", ""),
    "sys_clock_sudden_death": ("system summary: clock without overtime", "{main}"),
    "sys_clock_byoyomi": ("system summary: clock with byo-yomi", "{main} {periods} {seconds}"),
    "sys_clock_canadian": ("system summary: clock with Canadian byo-yomi", "{main} {stones} {minutes}"),
    "sys_clock_fischer": ("system summary: Fischer clock", "{main} {seconds}"),
    "sys_clock_fischer_max": ("system summary: Fischer clock, upper limit", "{max}"),
    "date_format": ("dates (strftime format: %d day, %m month, %Y year)", ""),
    "ordinal": ("ordinal numbers, e.g. '{n}.' -> '1.'; exceptions in [ordinals]", "{n}"),
}

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "pairing_title": "{tournament} – Round {round}",
        "pairing_boards": "{n} boards",
        "pairing_footer": "Round {round} – page {page}",
        "col_board": "Board",
        "col_white": "White",
        "col_white_win": "White\nwin",
        "col_draw": "Draw",
        "col_black_win": "Black\nwin",
        "col_black": "Black",
        "col_handicap": "Handi-\ncap",
        "alpha_title": "{tournament} – Round {round} (alphabetical)",
        "alpha_not_paired": "does not play this round",
        "col_player": "Player",
        "col_colour": "Colour",
        "col_opponent": "Opponent",
        "standings_title": "{tournament} – Standings after round {round}",
        "standings_start": "{tournament} – Starting list",
        "standings_footer": "Standings – page {page}",
        "standings_legend": "○ / ● white / black against the player on this place · + win, − loss, = jigo, "
                            "! forfeit · (n) handicap stones · – not played · TGoR (change since the start)",
        "col_place": "Place",
        "col_name": "Name",
        "col_rank": "Rank",
        "col_tgor": "TGoR",
        "col_round": "R{round}",
        "awards_title": "Award ceremony",
        "award_place": "Place {place}",
        "award_games": "{wins} of {games} games won",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} place",
        "prize_wins": "{wins} wins",
        "prize_best_in_group": "Best player ({group})",
        "prize_rating_gain": "Biggest TGoR gain",
        "date_format": "%Y-%m-%d",
        "sys_title": "{tournament}",
        "sys_subtitle": "How the tournament works",
        "sys_intro": "Instead of McMahon points, every player has a tournament rating (TGoR). It changes after every round. The highest TGoR at the end wins.",
        "sys_h_start": "Starting rating",
        "sys_start": "Your EGD rating (GoR) on the day of registration. Without one: the value of your rank (1k = 2000, 1d = 2100, 100 points per rank).",
        "sys_bar": "Nobody starts higher than {bar}: the strongest players start level.",
        "sys_h_update": "After every round",
        "sys_update": "All ratings are updated with the EGD rating formula, but {k} times as fast. The more surprising a result, the more points it moves: winning against a stronger player, or with fewer stones, brings more.",
        "sys_example": "Example: two players with {rating} play even – the winner gains {gain}, the loser loses {loss} points.",
        "sys_h_pairing": "Pairing",
        "sys_pairing": "You play the opponent whose TGoR is closest to yours – never the same opponent twice.",
        "sys_rule_avoid_same": "Same {field}: avoided if possible (counts as {points} points more difference).",
        "sys_rule_prefer_same": "Same {field}: preferred (a different {field} counts as {points} points more difference).",
        "sys_rule_forbid_same": "Same {field}: never paired.",
        "sys_rule_require_same": "Only players with the same {field} are paired.",
        "sys_h_handicap": "Handicap",
        "sys_handicap": "Full handicap: one stone per full 100 points of TGoR difference, at most 9.",
        "sys_handicap_reduced": "One stone per full 100 points of TGoR difference, at most 9, minus {reduction}.",
        "sys_floor": "For the handicap, ratings below {floor} count as {floor}.",
        "sys_komi": "The stronger player takes white. Komi: {even} in even games, {handicap} with handicap. You may agree on a different handicap; the one played is rated.",
        "sys_h_more": "Good to know",
        "sys_joker": "Odd number of players: a joker sits out and keeps their rating.",
        "sys_results": "Jigo counts as half a win. Forfeits are not rated.",
        "sys_h_winner": "Winner",
        "sys_winner": "The highest TGoR after round {rounds} wins. If equal: the lower starting GoR ranks higher, then the lot decides.",
        "sys_h_game": "Rules and time",
        "sys_rules_japanese": "Japanese rules (territory scoring).",
        "sys_rules_chinese": "Chinese rules (area scoring).",
        "sys_rules_aga": "AGA rules.",
        "sys_clock_sudden_death": "{main} minutes per player, no overtime: whoever runs out of time loses.",
        "sys_clock_byoyomi": "{main} minutes per player, then byo-yomi: {periods} periods of {seconds} seconds.",
        "sys_clock_canadian": "{main} minutes per player, then Canadian byo-yomi: {stones} stones in {minutes} minutes.",
        "sys_clock_fischer": "{main} minutes per player, plus {seconds} seconds for every move (Fischer).",
        "sys_clock_fischer_max": "At most {max} minutes on the clock.",
        "ordinal": "{n}th",
        "example_best_child": "Best child",
    },
    "de": {
        "pairing_title": "{tournament} – Runde {round}",
        "pairing_boards": "{n} Bretter",
        "pairing_footer": "Runde {round} – Seite {page}",
        "col_board": "Brett",
        "col_white": "Weiß",
        "col_white_win": "Weiß\ngewinnt",
        "col_draw": "Jigo",
        "col_black_win": "Schwarz\ngewinnt",
        "col_black": "Schwarz",
        "col_handicap": "Vor-\ngabe",
        "alpha_title": "{tournament} – Runde {round} (alphabetisch)",
        "alpha_not_paired": "setzt diese Runde aus",
        "col_player": "Spieler",
        "col_colour": "Farbe",
        "col_opponent": "Gegner",
        "standings_title": "{tournament} – Tabelle nach Runde {round}",
        "standings_start": "{tournament} – Startliste",
        "standings_footer": "Tabelle – Seite {page}",
        "standings_legend": "○ / ● Weiß / Schwarz gegen den Spieler auf diesem Platz · + Sieg, − Niederlage, "
                            "= Jigo, ! kampflos · (n) Vorgabesteine · – nicht gespielt · TGoR (Änderung seit Beginn)",
        "col_place": "Platz",
        "col_name": "Name",
        "col_rank": "Rang",
        "col_tgor": "TGoR",
        "col_round": "R{round}",
        "awards_title": "Siegerehrung",
        "award_place": "Platz {place}",
        "award_games": "{wins} von {games} Partien gewonnen",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} Platz",
        "prize_wins": "{wins} Siege",
        "prize_best_in_group": "Bestplatziert ({group})",
        "prize_rating_gain": "Größter TGoR-Zuwachs",
        "date_format": "%d.%m.%Y",
        "sys_title": "{tournament}",
        "sys_subtitle": "So funktioniert das Turnier",
        "sys_intro": "Statt McMahon-Punkten hat jeder Spieler eine Turnierwertung (TGoR). Sie ändert sich nach jeder Runde. Die höchste TGoR am Ende gewinnt.",
        "sys_h_start": "Startwertung",
        "sys_start": "Ihre EGD-Wertung (GoR) am Tag der Anmeldung. Ohne EGD-Wertung: der Wert Ihres Rangs (1k = 2000, 1d = 2100, 100 Punkte pro Rang).",
        "sys_bar": "Niemand startet höher als {bar}: Die stärksten Spieler beginnen gleichauf.",
        "sys_h_update": "Nach jeder Runde",
        "sys_update": "Alle Wertungen werden mit der EGD-Formel neu berechnet, aber {k}-mal so schnell. Je überraschender ein Ergebnis, desto mehr Punkte bewegt es: Ein Sieg gegen einen Stärkeren oder mit weniger Steinen bringt mehr.",
        "sys_example": "Beispiel: Zwei Spieler mit {rating} spielen ohne Vorgabe – der Sieger gewinnt {gain}, der Verlierer verliert {loss} Punkte.",
        "sys_h_pairing": "Auslosung",
        "sys_pairing": "Sie spielen gegen den Gegner, dessen TGoR Ihrer am nächsten liegt – nie zweimal gegen denselben.",
        "sys_rule_avoid_same": "Gleicher {field}: wird möglichst vermieden (zählt wie {points} Punkte mehr Unterschied).",
        "sys_rule_prefer_same": "Gleicher {field}: wird bevorzugt (ein anderer {field} zählt wie {points} Punkte mehr Unterschied).",
        "sys_rule_forbid_same": "Gleicher {field}: wird nie gepaart.",
        "sys_rule_require_same": "Nur Spieler mit gleichem {field} werden gepaart.",
        "sys_h_handicap": "Vorgabe",
        "sys_handicap": "Volle Vorgabe: ein Stein pro vollen 100 Punkten TGoR-Unterschied, höchstens 9.",
        "sys_handicap_reduced": "Ein Stein pro vollen 100 Punkten TGoR-Unterschied, höchstens 9, minus {reduction}.",
        "sys_floor": "Für die Vorgabe zählen Wertungen unter {floor} als {floor}.",
        "sys_komi": "Der Stärkere nimmt Weiß. Komi: {even} ohne Vorgabe, {handicap} mit Vorgabe. Sie dürfen eine andere Vorgabe vereinbaren; gewertet wird die gespielte.",
        "sys_h_more": "Gut zu wissen",
        "sys_joker": "Ungerade Spielerzahl: Ein Joker setzt aus und behält seine Wertung.",
        "sys_results": "Jigo zählt als halber Sieg. Kampflose Partien werden nicht gewertet.",
        "sys_h_winner": "Sieger",
        "sys_winner": "Die höchste TGoR nach Runde {rounds} gewinnt. Bei Gleichstand liegt die niedrigere Start-GoR vorn, danach entscheidet das Los.",
        "sys_h_game": "Regeln und Bedenkzeit",
        "sys_rules_japanese": "Japanische Regeln (Gebietszählung).",
        "sys_rules_chinese": "Chinesische Regeln (Flächenzählung).",
        "sys_rules_aga": "AGA-Regeln.",
        "sys_clock_sudden_death": "{main} Minuten pro Spieler, ohne Nachspielzeit: Wer die Zeit überschreitet, verliert.",
        "sys_clock_byoyomi": "{main} Minuten pro Spieler, dann Byo-Yomi: {periods} Perioden zu {seconds} Sekunden.",
        "sys_clock_canadian": "{main} Minuten pro Spieler, dann kanadisches Byo-Yomi: {stones} Steine in {minutes} Minuten.",
        "sys_clock_fischer": "{main} Minuten pro Spieler, dazu {seconds} Sekunden für jeden Zug (Fischer).",
        "sys_clock_fischer_max": "Höchstens {max} Minuten auf der Uhr.",
        "ordinal": "{n}.",
        "example_best_child": "Bestes Kind",
    },
    "fr": {
        "pairing_title": "{tournament} – Ronde {round}",
        "pairing_boards": "{n} tables",
        "pairing_footer": "Ronde {round} – page {page}",
        "col_board": "Table",
        "col_white": "Blanc",
        "col_white_win": "Victoire\nBlanc",
        "col_draw": "Jigo",
        "col_black_win": "Victoire\nNoir",
        "col_black": "Noir",
        "col_handicap": "Handi-\ncap",
        "alpha_title": "{tournament} – Ronde {round} (ordre alphabétique)",
        "alpha_not_paired": "ne joue pas cette ronde",
        "col_player": "Joueur",
        "col_colour": "Couleur",
        "col_opponent": "Adversaire",
        "standings_title": "{tournament} – Classement après la ronde {round}",
        "standings_start": "{tournament} – Liste de départ",
        "standings_footer": "Classement – page {page}",
        "standings_legend": "○ / ● Blanc / Noir contre le joueur à cette place · + victoire, − défaite, "
                            "= jigo, ! forfait · (n) pierres de handicap · – pas joué · TGoR (évolution depuis le début)",
        "col_place": "Place",
        "col_name": "Nom",
        "col_rank": "Niveau",
        "col_tgor": "TGoR",
        "col_round": "R{round}",
        "awards_title": "Remise des prix",
        "award_place": "{place}e place",
        "award_games": "{wins} victoires sur {games} parties",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} place",
        "prize_wins": "{wins} victoires",
        "prize_best_in_group": "Meilleur classement ({group})",
        "prize_rating_gain": "Plus forte progression TGoR",
        "date_format": "%d/%m/%Y",
        "sys_title": "{tournament}",
        "sys_subtitle": "Comment fonctionne le tournoi",
        "sys_intro": "Au lieu des points McMahon, chaque joueur a un classement de tournoi (TGoR). Il change après chaque ronde. Le TGoR le plus élevé à la fin gagne.",
        "sys_h_start": "Classement de départ",
        "sys_start": "Votre classement EGD (GoR) le jour de l'inscription. Sans classement : la valeur de votre niveau (1k = 2000, 1d = 2100, 100 points par niveau).",
        "sys_bar": "Personne ne commence au-dessus de {bar} : les joueurs les plus forts partent à égalité.",
        "sys_h_update": "Après chaque ronde",
        "sys_update": "Tous les classements sont recalculés avec la formule EGD, mais {k} fois plus vite. Plus un résultat est surprenant, plus il rapporte : gagner contre un joueur plus fort, ou avec moins de pierres, rapporte davantage.",
        "sys_example": "Exemple : deux joueurs à {rating} jouent sans handicap – le gagnant prend {gain}, le perdant perd {loss} points.",
        "sys_h_pairing": "Appariement",
        "sys_pairing": "Vous jouez contre l'adversaire dont le TGoR est le plus proche du vôtre – jamais deux fois le même.",
        "sys_rule_avoid_same": "Même {field} : évité si possible (compte comme {points} points d'écart en plus).",
        "sys_rule_prefer_same": "Même {field} : préféré (un {field} différent compte comme {points} points d'écart en plus).",
        "sys_rule_forbid_same": "Même {field} : jamais apparié.",
        "sys_rule_require_same": "Seuls les joueurs avec le même {field} sont appariés.",
        "sys_h_handicap": "Handicap",
        "sys_handicap": "Handicap complet : une pierre par tranche complète de 100 points d'écart de TGoR, au plus 9.",
        "sys_handicap_reduced": "Une pierre par tranche complète de 100 points d'écart de TGoR, au plus 9, moins {reduction}.",
        "sys_floor": "Pour le handicap, les classements inférieurs à {floor} comptent comme {floor}.",
        "sys_komi": "Le plus fort prend blanc. Komi : {even} sans handicap, {handicap} avec handicap. Vous pouvez convenir d'un autre handicap ; c'est celui joué qui compte.",
        "sys_h_more": "Bon à savoir",
        "sys_joker": "Nombre impair de joueurs : un joker ne joue pas et garde son classement.",
        "sys_results": "Le jigo compte pour une demi-victoire. Les forfaits ne sont pas comptés.",
        "sys_h_winner": "Vainqueur",
        "sys_winner": "Le TGoR le plus élevé après la ronde {rounds} gagne. En cas d'égalité, le GoR de départ le plus bas passe devant, puis le tirage au sort.",
        "sys_h_game": "Règles et temps",
        "sys_rules_japanese": "Règles japonaises (décompte du territoire).",
        "sys_rules_chinese": "Règles chinoises (décompte de la surface).",
        "sys_rules_aga": "Règles AGA.",
        "sys_clock_sudden_death": "{main} minutes par joueur, sans temps supplémentaire : qui dépasse son temps perd.",
        "sys_clock_byoyomi": "{main} minutes par joueur, puis byo-yomi : {periods} périodes de {seconds} secondes.",
        "sys_clock_canadian": "{main} minutes par joueur, puis byo-yomi canadien : {stones} pierres en {minutes} minutes.",
        "sys_clock_fischer": "{main} minutes par joueur, plus {seconds} secondes par coup (Fischer).",
        "sys_clock_fischer_max": "Au plus {max} minutes à la pendule.",
        "ordinal": "{n}e",
        "example_best_child": "Meilleur enfant",
    },
}
ORDINAL_EXCEPTIONS = {"fr": {1: "1re"}}


class TranslationError(Exception):
    pass


def normalize_language(value: str) -> str | None:
    return LANGUAGE_ALIASES.get(str(value).strip().casefold())


def _english_ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class Translator:
    def __init__(self, language: str, texts: dict[str, str], ordinals: dict[int, str] | None = None):
        self.language = language
        self.texts = texts
        self.ordinals = ordinals or {}

    def t(self, key: str, **values) -> str:
        text = self.texts.get(key, TEXTS["en"][key])
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return TEXTS["en"][key].format(**values)

    def ordinal(self, n: int) -> str:
        if n in self.ordinals:
            return self.ordinals[n]
        if self.language == "en":
            return _english_ordinal(n)
        return self.t("ordinal", n=n)

    def date(self, iso: str) -> str:
        try:
            return dt.date.fromisoformat(iso.strip()).strftime(self.texts.get("date_format", "%Y-%m-%d"))
        except ValueError:
            return iso

    def date_range(self, dates: list[str]) -> str:
        return " – ".join(self.date(d) for d in sorted(set(dates)))


def builtin(language: str) -> Translator:
    return Translator(language, TEXTS[language], ORDINAL_EXCEPTIONS.get(language))


def load_custom(path: Path) -> tuple[Translator, list[str]]:
    """Read a translation file. Missing keys fall back to English (returned as warnings)."""
    if not path.exists():
        raise TranslationError(f"{path} not found. Run 'gotourney translation-file' to create an example "
                               f"(German) and edit it.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise TranslationError(f"{path}: {e}") from e
    texts, warnings = {}, []
    for key in KEYS:
        value = data.get(key)
        if value is None:
            warnings.append(f"{path.name}: '{key}' missing, using English")
            continue
        if not isinstance(value, str):
            raise TranslationError(f"{path.name}: '{key}' must be text")
        texts[key] = value
    unknown = set(data) - set(KEYS) - {"ordinals"}
    for key in sorted(unknown):
        warnings.append(f"{path.name}: unknown key '{key}' ignored")
    ordinals = {}
    raw = data.get("ordinals", {})
    if not isinstance(raw, dict):
        raise TranslationError(f"{path.name}: [ordinals] must be a table like 1 = \"1st\"")
    for k, v in raw.items():
        try:
            ordinals[int(k)] = str(v)
        except ValueError:
            raise TranslationError(f"{path.name}: [ordinals] key {k!r} is not a number") from None
    # check placeholders: formatting with all known placeholder names must work
    sample = {"tournament": "T", "round": 1, "n": 1, "page": 1, "place": 1, "wins": 1, "games": 1,
              "tgor": 1, "change": "+1", "ordinal": "1.", "group": "G", "bar": "2300", "k": 3,
              "rating": "2000", "gain": "+30", "loss": "-30", "field": "Club", "reduction": 1, "floor": "100",
              "even": "6.5", "handicap": "0.5", "rounds": 5, "points": 150,
              "main": 60, "periods": 5, "seconds": 30, "stones": 15, "minutes": 5, "max": 90}
    for key, value in texts.items():
        try:
            value.format(**sample)
        except (KeyError, IndexError, ValueError) as e:
            raise TranslationError(f"{path.name}: '{key}' has an unknown placeholder ({e})") from None
    return Translator("custom", texts, ordinals), warnings


def get_translator(cfg, directory: Path) -> tuple[Translator, list[str]]:
    lang = cfg.output.language
    if lang == "custom":
        return load_custom(Path(directory) / cfg.output.translation_file)
    return builtin(lang), []


def _toml_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def translation_template(language: str = "de") -> str:
    """A complete translation file with the texts of a built-in language (default German)."""
    texts = TEXTS[language]
    lines = [
        "# Translation of the output PDFs (pairing, award ceremony).",
        "# Used when tournament.toml has   [output] language = \"custom\".",
        "# This example contains the German texts; change them as you like.",
        "# Keep the placeholders in {braces}; \\n is a line break. Missing keys are taken from English.",
        "",
    ]
    for key, (description, placeholders) in KEYS.items():
        note = f"   (placeholders: {placeholders})" if placeholders else ""
        lines.append(f"# {description}{note}")
        lines.append(f"{key} = {_toml_string(texts[key])}")
        lines.append("")
    lines.append("# Exceptions for ordinal numbers, e.g. for French: 1 = \"1re\"")
    lines.append("[ordinals]")
    for n, text in ORDINAL_EXCEPTIONS.get(language, {}).items():
        lines.append(f"{n} = {_toml_string(text)}")
    return "\n".join(lines) + "\n"

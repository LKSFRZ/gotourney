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
    "awards_title": ("award slides: title slide", ""),
    "award_place": ("award slide: final place", "{place}"),
    "award_games": ("award slide: games won", "{wins} {games}"),
    "award_tgor": ("award slide: final TGoR and change", "{tgor} {change}"),
    "prize_place": ("default prize title, type place", "{place} {ordinal}"),
    "prize_wins": ("default prize title, type wins", "{wins} {games}"),
    "prize_best_in_group": ("default prize title, type best_in_group", "{group}"),
    "prize_rating_gain": ("default prize title, type rating_gain", ""),
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
        "awards_title": "Award ceremony",
        "award_place": "Place {place}",
        "award_games": "{wins} of {games} games won",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} place",
        "prize_wins": "{wins} wins",
        "prize_best_in_group": "Best player ({group})",
        "prize_rating_gain": "Biggest TGoR gain",
        "date_format": "%Y-%m-%d",
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
        "awards_title": "Siegerehrung",
        "award_place": "Platz {place}",
        "award_games": "{wins} von {games} Partien gewonnen",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} Platz",
        "prize_wins": "{wins} Siege",
        "prize_best_in_group": "Bestplatziert ({group})",
        "prize_rating_gain": "Größter TGoR-Zuwachs",
        "date_format": "%d.%m.%Y",
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
        "awards_title": "Remise des prix",
        "award_place": "{place}e place",
        "award_games": "{wins} victoires sur {games} parties",
        "award_tgor": "TGoR {tgor} ({change})",
        "prize_place": "{ordinal} place",
        "prize_wins": "{wins} victoires",
        "prize_best_in_group": "Meilleur classement ({group})",
        "prize_rating_gain": "Plus forte progression TGoR",
        "date_format": "%d/%m/%Y",
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
              "tgor": 1, "change": "+1", "ordinal": "1.", "group": "G"}
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

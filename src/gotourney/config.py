"""Tournament settings, stored in ``tournament.toml`` in the tournament directory."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE = "tournament.toml"

ACCEPTED_KOMI_EVEN = (6.5, 7.0, 7.5)

TEMPLATE = """\
# Settings for one tournament. Edit by hand as needed.

[tournament]                 # EGD metadata, written to the .h9 header
code    = ""                 # TC - left empty, assigned by the EGD after upload
name    = "{name}"           # EV
place   = ""                 # PC, e.g. "DE, Schwerin"
dates   = []                 # DT, e.g. ["2026-09-26", "2026-09-27"]
class   = "A"                # CL
time    = 60                 # TM, basic thinking time in minutes
comment = ""                 # CM, e.g. "(submitted by ...)"
rounds  = {rounds}                 # number of rounds; R1..Rn columns in players.ods follow this

[output]
language = "{language}"            # language of the PDFs (pairing, award ceremony): en, de, fr or custom
translation_file = "translation.toml"   # texts for language = "custom" (example: German)

[rating]
k_factor = 3.0               # multiplies the EGD 'con' factor (bonus term is not used)
top_bar  = "3d"              # starting TGoR is capped here: a rank ("3d" = 2300) or a GoR number; "none" = no bar

[handicap]
reduction     = 0            # "full minus N": written as HA[h<reduction>]; h0 = full, h9 = no handicap
komi_even     = 6.5          # accepted standards: 6.5, 7, 7.5 (Chinese rules)
komi_handicap = 0.5

[pairing]
random_seed  = 12345         # colour choice and random tie-breaks

# Pairing rules: each rule makes some pairs more expensive (or impossible) for the pairing.
#   field  = a player column: "Club", "Country", "Rank" or an additional field (e.g. "Age group")
#   type   = "avoid_same"    same value: pair counts as `points` more TGoR difference
#            "prefer_same"   different values: pair counts as `points` more TGoR difference
#            "forbid_same"   same value: never paired automatically
#            "require_same"  different values: never paired automatically
#   values = optional: these values form one group and count as the same value; values outside
#            the group count together as "the rest" (e.g. all children vs. everybody else)
#   groups = optional, instead of values: several groups, e.g. [["U7", "U11"], ["U15", "U19"]]
# An empty cell never counts as "same" for avoid_same / forbid_same (e.g. players without club),
# and with values / groups these rules only apply inside a group.
# Delete or comment out a rule to switch it off.

[[pairing.rules]]
field  = "Club"
type   = "avoid_same"
points = 150

# Example (off): children (U7, U11, U15) preferably play other children
# [[pairing.rules]]
# field  = "Age group"
# type   = "prefer_same"
# points = 200
# values = ["U7", "U11", "U15"]
#
# Example (off): younger and older children kept apart from each other and from adults
# [[pairing.rules]]
# field  = "Age group"
# type   = "prefer_same"
# points = 200
# groups = [["U7", "U11"], ["U15", "U19"]]

[registration]
gor_outdated_years = 5       # warn if a player's last EGD tournament is older than this
rank_gor_tolerance = 300     # warn if declared rank and GoR differ by more than this
extra_fields = ["Fee paid", "Age group"]    # additional player data (columns in players.ods)

# Fields with a list of values get a dropdown in the registration window and only accept
# these values; additional fields not listed here are free text.
[registration.field_values]
"Fee paid"  = ["yes", "no"]
"Age group" = ["U7", "U11", "U15", "U19", "Ü50"]

# Award ceremony: 'gotourney awards' writes awards.pdf with one slide per prize winner,
# in the order of the prizes below. Prize types:
#   "place"          places = [3, 2, 1]               players on these final places
#   "wins"           min_wins = 4                     everybody with at least this many wins (jigo = 1/2)
#   "best_in_group"  field = "Age group", values = [...] (one group) or groups = [[...], [...]]
#                    (one prize per group), count = 1  best placed player(s) of the group
#   "rating_gain"    count = 1                        biggest TGoR gain (final - start)
# Optional for every prize:
#   title     = slide heading; placeholders {{place}} {{ordinal}} {{wins}} {{games}} {{group}} {{n}}
#               (without a title, a default in the output language is used)
#   exclusive = true    skip players who already got an earlier prize
[awards]
title_slide = true           # first slide with tournament name, place and dates

[[awards.prizes]]
type     = "wins"
min_wins = {rounds}

[[awards.prizes]]
type   = "best_in_group"
field  = "Age group"
values = ["U7", "U11", "U15"]
title  = "{best_child}"

[[awards.prizes]]
type   = "place"
places = [3, 2, 1]
"""

PRIZE_TYPES = ("place", "wins", "best_in_group", "rating_gain")
PRIZE_PLACEHOLDERS = ("place", "ordinal", "wins", "games", "group", "n")

DEFAULT_EXTRA_FIELDS = ["Fee paid", "Age group"]
DEFAULT_FIELD_VALUES = {"Fee paid": ["yes", "no"], "Age group": ["U7", "U11", "U15", "U19", "Ü50"]}
RULE_TYPES = ("avoid_same", "prefer_same", "forbid_same", "require_same")
RULE_BUILTIN_FIELDS = ("Club", "Country", "Rank")
DEFAULT_CLUB_PENALTY = 150.0


class ConfigError(Exception):
    pass


@dataclass
class TournamentInfo:
    code: str = ""
    name: str = ""
    place: str = ""
    dates: list[str] = field(default_factory=list)
    klass: str = "A"
    time: int = 60
    comment: str = ""
    rounds: int = 5


DEFAULT_TOP_BAR = 2300.0     # 3 dan


@dataclass
class RatingSettings:
    k_factor: float = 3.0
    top_bar: float | None = DEFAULT_TOP_BAR     # cap for the starting TGoR; None = no bar


@dataclass
class HandicapSettings:
    reduction: int = 0
    komi_even: float = 6.5
    komi_handicap: float = 0.5


@dataclass
class PairingRule:
    field: str
    type: str                  # one of RULE_TYPES
    points: float = 0.0        # for avoid_same / prefer_same
    values: list[str] = field(default_factory=list)          # one group (shorthand)
    groups: list[list[str]] = field(default_factory=list)    # several groups

    @property
    def all_groups(self) -> list[list[str]]:
        """The groups of values; empty = every value is its own group."""
        return self.groups or ([self.values] if self.values else [])

    @property
    def hard(self) -> bool:
        return self.type in ("forbid_same", "require_same")

    def describe(self) -> str:
        text = f"{self.field}: {self.type.replace('_', ' ')}"
        if not self.hard:
            text += f" ({self.points:g} points)"
        groups = self.all_groups
        if groups:
            text += " for " + " / ".join("{" + ", ".join(g) + "}" for g in groups)
        return text


def default_rules() -> list[PairingRule]:
    return [PairingRule("Club", "avoid_same", DEFAULT_CLUB_PENALTY)]


@dataclass
class PairingSettings:
    random_seed: int = 12345
    rules: list[PairingRule] = field(default_factory=default_rules)


@dataclass
class RegistrationSettings:
    gor_outdated_years: int = 5
    rank_gor_tolerance: int = 300
    extra_fields: list[str] = field(default_factory=lambda: list(DEFAULT_EXTRA_FIELDS))
    field_values: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_FIELD_VALUES.items()})

    def values_for(self, name: str) -> list[str] | None:
        """Allowed values (dropdown) of an additional field, or None for free text."""
        key = name.strip().lower()
        return next((v for k, v in self.field_values.items() if k.strip().lower() == key), None)


@dataclass
class Prize:
    type: str                                   # one of PRIZE_TYPES
    title: str = ""                             # "" = default title in the output language
    places: list[int] = field(default_factory=list)
    min_wins: float = 0.0
    group_field: str = ""                       # TOML key: field
    values: list[str] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)
    count: int = 1
    exclusive: bool = False

    @property
    def all_groups(self) -> list[list[str]]:
        return self.groups or ([self.values] if self.values else [])


def default_prizes(rounds: int) -> list[Prize]:
    return [
        Prize("wins", min_wins=float(rounds)),
        Prize("best_in_group", group_field="Age group", values=["U7", "U11", "U15"]),
        Prize("place", places=[3, 2, 1]),
    ]


@dataclass
class AwardSettings:
    title_slide: bool = True
    prizes: list[Prize] = field(default_factory=list)


@dataclass
class OutputSettings:
    language: str = "en"                        # en, de, fr or custom
    translation_file: str = "translation.toml"


@dataclass
class Config:
    tournament: TournamentInfo = field(default_factory=TournamentInfo)
    rating: RatingSettings = field(default_factory=RatingSettings)
    handicap: HandicapSettings = field(default_factory=HandicapSettings)
    pairing: PairingSettings = field(default_factory=PairingSettings)
    registration: RegistrationSettings = field(default_factory=RegistrationSettings)
    awards: AwardSettings = field(default_factory=AwardSettings)
    output: OutputSettings = field(default_factory=OutputSettings)


def _get(section: dict, key: str, typ, default, where: str):
    if key not in section:
        return default
    value = section[key]
    try:
        if typ is float and isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if typ is int and isinstance(value, int) and not isinstance(value, bool):
            return value
        if typ is str and isinstance(value, str):
            return value
        if typ is list and isinstance(value, list):
            return [str(v) for v in value]
    except (TypeError, ValueError):
        pass
    raise ConfigError(f"{where}.{key}: expected {typ.__name__}, got {value!r}")


def _top_bar(value) -> float | None:
    """'3d' -> 2300, 2350 -> 2350, 'none' / '' / false -> None."""
    from .rank import Rank, RankError
    if value is None or value is False or (isinstance(value, str) and value.strip().lower() in ("", "none", "no", "off")):
        return None
    if isinstance(value, bool):
        raise ConfigError("rating.top_bar: expected a rank like \"3d\", a GoR number or \"none\"")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(Rank.parse(str(value)).to_gor())
    except RankError:
        try:
            return float(str(value).strip())
        except ValueError:
            raise ConfigError(f"rating.top_bar: {value!r} is not a rank (e.g. \"3d\"), a GoR number or \"none\"") from None


def _rules(p: dict) -> list[PairingRule]:
    raw = p.get("rules")
    if raw is None:
        # no rules configured: the club rule (older files: with their club_penalty)
        return [PairingRule("Club", "avoid_same", _get(p, "club_penalty", float, DEFAULT_CLUB_PENALTY, "pairing"))]
    if "club_penalty" in p:
        raise ConfigError("pairing.club_penalty cannot be combined with [[pairing.rules]]; "
                          "set the points of the Club rule instead")
    if not isinstance(raw, list):
        raise ConfigError("pairing.rules: write each rule as a [[pairing.rules]] table")
    rules = []
    for i, r in enumerate(raw, start=1):
        where = f"pairing.rules (rule {i})"
        if not isinstance(r, dict):
            raise ConfigError(f"{where}: expected a table")
        unknown = set(r) - {"field", "type", "points", "values", "groups"}
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        name = _get(r, "field", str, "", where).strip()
        if not name:
            raise ConfigError(f"{where}: 'field' is missing")
        typ = _get(r, "type", str, "", where).strip().lower()
        if typ not in RULE_TYPES:
            raise ConfigError(f"{where}: type must be one of {', '.join(RULE_TYPES)}")
        points = _get(r, "points", float, None, where)
        if typ in ("avoid_same", "prefer_same"):
            if points is None:
                raise ConfigError(f"{where}: {typ} needs 'points'")
            if points < 0:
                raise ConfigError(f"{where}: points must not be negative")
        values = [v.strip() for v in _get(r, "values", list, [], where) if v.strip()]
        groups = _groups(r.get("groups", []), where)
        if values and groups:
            raise ConfigError(f"{where}: use either 'values' (one group) or 'groups', not both")
        seen_values: set[str] = set()
        for g in groups or [values]:
            for v in g:
                if v.casefold() in seen_values:
                    raise ConfigError(f"{where}: value {v!r} appears in more than one group")
                seen_values.add(v.casefold())
        rules.append(PairingRule(name, typ, points or 0.0, values, groups))
    return rules


def _groups(raw, where: str) -> list[list[str]]:
    if not isinstance(raw, list) or not all(isinstance(g, list) for g in raw):
        raise ConfigError(f"{where}: groups must be a list of lists, e.g. [[\"U7\", \"U11\"], [\"U15\"]]")
    groups = []
    for g in raw:
        vals = [str(v).strip() for v in g if str(v).strip()]
        if not vals:
            raise ConfigError(f"{where}: groups must not contain an empty group")
        groups.append(vals)
    return groups


def _awards(a: dict, rounds: int) -> AwardSettings:
    if not isinstance(a, dict):
        raise ConfigError("awards: expected a table [awards]")
    unknown = set(a) - {"title_slide", "prizes"}
    if unknown:
        raise ConfigError(f"awards: unknown key(s) {', '.join(sorted(unknown))}")
    title_slide = a.get("title_slide", True)
    if not isinstance(title_slide, bool):
        raise ConfigError("awards.title_slide: expected true or false")
    raw = a.get("prizes")
    if raw is None:
        return AwardSettings(title_slide, default_prizes(rounds))
    if not isinstance(raw, list):
        raise ConfigError("awards.prizes: write each prize as an [[awards.prizes]] table")
    prizes = []
    for i, p in enumerate(raw, start=1):
        where = f"awards.prizes (prize {i})"
        if not isinstance(p, dict):
            raise ConfigError(f"{where}: expected a table")
        unknown = set(p) - {"type", "title", "places", "min_wins", "field", "values", "groups",
                            "count", "exclusive"}
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        typ = _get(p, "type", str, "", where).strip().lower()
        if typ not in PRIZE_TYPES:
            raise ConfigError(f"{where}: type must be one of {', '.join(PRIZE_TYPES)}")
        title = _get(p, "title", str, "", where)
        try:
            title.format(**{k: "x" for k in PRIZE_PLACEHOLDERS})
        except (KeyError, IndexError, ValueError) as e:
            raise ConfigError(f"{where}: title {title!r} has an unknown placeholder ({e}); "
                              f"use {', '.join('{' + k + '}' for k in PRIZE_PLACEHOLDERS)}") from None
        prize = Prize(typ, title, exclusive=bool(p.get("exclusive", False)))
        count = p.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ConfigError(f"{where}: count must be a whole number of at least 1")
        prize.count = count
        if typ == "place":
            places = p.get("places")
            if (not isinstance(places, list) or not places
                    or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 1 for x in places)):
                raise ConfigError(f"{where}: 'places' must be a list of places, e.g. [3, 2, 1]")
            prize.places = places
        elif typ == "wins":
            mw = _get(p, "min_wins", float, None, where)
            if mw is None or mw <= 0:
                raise ConfigError(f"{where}: 'min_wins' (a positive number) is required")
            prize.min_wins = mw
        elif typ == "best_in_group":
            prize.group_field = _get(p, "field", str, "", where).strip()
            if not prize.group_field:
                raise ConfigError(f"{where}: 'field' is required, e.g. \"Age group\"")
            prize.values = [v.strip() for v in _get(p, "values", list, [], where) if v.strip()]
            prize.groups = _groups(p.get("groups", []), where)
            if bool(prize.values) == bool(prize.groups):
                raise ConfigError(f"{where}: give either 'values' (one group) or 'groups'")
        prizes.append(prize)
    return AwardSettings(title_slide, prizes)


def _output(o: dict) -> OutputSettings:
    from .i18n import LANGUAGES, normalize_language
    if not isinstance(o, dict):
        raise ConfigError("output: expected a table [output]")
    raw = _get(o, "language", str, "en", "output")
    lang = normalize_language(raw)
    if lang is None:
        raise ConfigError(f"output.language: {raw!r} is not supported (use {', '.join(LANGUAGES)})")
    file = _get(o, "translation_file", str, "translation.toml", "output").strip() or "translation.toml"
    return OutputSettings(lang, file)


def _field_values(g: dict) -> dict[str, list[str]]:
    if "extra_fields" not in g and "field_values" not in g:
        return {k: list(v) for k, v in DEFAULT_FIELD_VALUES.items()}
    raw = g.get("field_values", {})
    if not isinstance(raw, dict):
        raise ConfigError("registration.field_values: expected a table like \"Fee paid\" = [\"yes\", \"no\"]")
    result = {}
    for name, values in raw.items():
        vals = [v.strip() for v in _get(raw, name, list, [], "registration.field_values")]
        if not vals or any(not v for v in vals):
            raise ConfigError(f"registration.field_values.{name}: give a list of non-empty values")
        if len({v.lower() for v in vals}) != len(vals):
            raise ConfigError(f"registration.field_values.{name}: a value is listed twice")
        result[name.strip()] = vals
    return result


def parse_config(data: dict) -> Config:
    t = data.get("tournament", {})
    r = data.get("rating", {})
    h = data.get("handicap", {})
    p = data.get("pairing", {})
    g = data.get("registration", {})
    cfg = Config(
        tournament=TournamentInfo(
            code=_get(t, "code", str, "", "tournament"),
            name=_get(t, "name", str, "", "tournament"),
            place=_get(t, "place", str, "", "tournament"),
            dates=_get(t, "dates", list, [], "tournament"),
            klass=_get(t, "class", str, "A", "tournament"),
            time=_get(t, "time", int, 60, "tournament"),
            comment=_get(t, "comment", str, "", "tournament"),
            rounds=_get(t, "rounds", int, 5, "tournament"),
        ),
        rating=RatingSettings(k_factor=_get(r, "k_factor", float, 3.0, "rating"),
                              top_bar=_top_bar(r.get("top_bar", DEFAULT_TOP_BAR))),
        handicap=HandicapSettings(
            reduction=_get(h, "reduction", int, 0, "handicap"),
            komi_even=_get(h, "komi_even", float, 6.5, "handicap"),
            komi_handicap=_get(h, "komi_handicap", float, 0.5, "handicap"),
        ),
        pairing=PairingSettings(
            random_seed=_get(p, "random_seed", int, 12345, "pairing"),
            rules=_rules(p),
        ),
        registration=RegistrationSettings(
            gor_outdated_years=_get(g, "gor_outdated_years", int, 5, "registration"),
            rank_gor_tolerance=_get(g, "rank_gor_tolerance", int, 300, "registration"),
            extra_fields=[f.strip() for f in _get(g, "extra_fields", list, DEFAULT_EXTRA_FIELDS,
                                                  "registration")],
            field_values=_field_values(g),
        ),
        awards=_awards(data.get("awards", {}), _get(t, "rounds", int, 5, "tournament")),
        output=_output(data.get("output", {})),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.tournament.rounds < 1:
        raise ConfigError("tournament.rounds must be at least 1")
    if not 0 <= cfg.handicap.reduction <= 9:
        raise ConfigError("handicap.reduction must be between 0 and 9")
    if cfg.handicap.komi_even not in ACCEPTED_KOMI_EVEN:
        raise ConfigError(
            f"handicap.komi_even must be one of {', '.join(map(str, ACCEPTED_KOMI_EVEN))}"
        )
    if cfg.rating.k_factor <= 0:
        raise ConfigError("rating.k_factor must be positive")
    from .players import is_builtin_column
    for rule in cfg.pairing.rules:
        builtin = next((b for b in RULE_BUILTIN_FIELDS if b.lower() == rule.field.lower()), None)
        if builtin:
            rule.field = builtin
        elif is_builtin_column(rule.field):
            raise ConfigError(f"pairing.rules: field {rule.field!r} cannot be used in a rule "
                              f"(use {', '.join(RULE_BUILTIN_FIELDS)} or an additional field)")
    seen = set()
    for name in cfg.registration.extra_fields:
        if not name:
            raise ConfigError("registration.extra_fields: field names must not be empty")
        if is_builtin_column(name):
            raise ConfigError(f"registration.extra_fields: {name!r} is already a standard column")
        if name.lower() in seen:
            raise ConfigError(f"registration.extra_fields: {name!r} is listed twice")
        seen.add(name.lower())
    for name in cfg.registration.field_values:
        if name.lower() not in seen:
            raise ConfigError(f"registration.field_values: {name!r} is not in registration.extra_fields")


def load_config(directory: Path) -> Config:
    path = Path(directory) / CONFIG_FILE
    if not path.exists():
        raise ConfigError(f"{path} not found. Run 'gotourney init' first.")
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    try:
        return parse_config(data)
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from e


def write_template(directory: Path, name: str, rounds: int = 5, language: str = "en") -> Path:
    from .i18n import TEXTS, normalize_language
    if rounds < 1:
        raise ConfigError("the number of rounds must be at least 1")
    lang = normalize_language(language)
    if lang not in TEXTS:
        raise ConfigError(f"language {language!r} is not supported here (use en, de or fr)")
    path = Path(directory) / CONFIG_FILE
    path.write_text(TEMPLATE.format(name=name.replace('"', "'"), rounds=rounds, language=lang,
                                    best_child=TEXTS[lang]["example_best_child"]), encoding="utf-8")
    return path

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
#   values = optional: the rule only applies when a player has one of these values
# An empty cell never counts as "same" for avoid_same / forbid_same (e.g. players without club);
# for prefer_same / require_same, two empty cells count as the same value.
# Delete or comment out a rule to switch it off.

[[pairing.rules]]
field  = "Club"
type   = "avoid_same"
points = 150

# Example (off): children preferably play children of their own age group
# [[pairing.rules]]
# field  = "Age group"
# type   = "prefer_same"
# points = 200
# values = ["U7", "U11", "U15"]

[registration]
gor_outdated_years = 5       # warn if a player's last EGD tournament is older than this
rank_gor_tolerance = 300     # warn if declared rank and GoR differ by more than this
extra_fields = ["Fee paid", "Age group"]    # additional player data (columns in players.ods)

# Fields with a list of values get a dropdown in the registration window and only accept
# these values; additional fields not listed here are free text.
[registration.field_values]
"Fee paid"  = ["yes", "no"]
"Age group" = ["U7", "U11", "U15", "U19", "Ü50"]
"""

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
    values: list[str] = field(default_factory=list)

    @property
    def hard(self) -> bool:
        return self.type in ("forbid_same", "require_same")

    def describe(self) -> str:
        text = f"{self.field}: {self.type.replace('_', ' ')}"
        if not self.hard:
            text += f" ({self.points:g} points)"
        if self.values:
            text += f" for {', '.join(self.values)}"
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
class Config:
    tournament: TournamentInfo = field(default_factory=TournamentInfo)
    rating: RatingSettings = field(default_factory=RatingSettings)
    handicap: HandicapSettings = field(default_factory=HandicapSettings)
    pairing: PairingSettings = field(default_factory=PairingSettings)
    registration: RegistrationSettings = field(default_factory=RegistrationSettings)


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
        unknown = set(r) - {"field", "type", "points", "values"}
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
        rules.append(PairingRule(name, typ, points or 0.0, values))
    return rules


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


def write_template(directory: Path, name: str, rounds: int = 5) -> Path:
    if rounds < 1:
        raise ConfigError("the number of rounds must be at least 1")
    path = Path(directory) / CONFIG_FILE
    path.write_text(TEMPLATE.format(name=name.replace('"', "'"), rounds=rounds), encoding="utf-8")
    return path

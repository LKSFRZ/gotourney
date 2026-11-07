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
club_penalty = 150           # added to the TGoR difference of same-club pairs
random_seed  = 12345         # colour choice and random tie-breaks

[registration]
gor_outdated_years = 5       # warn if a player's last EGD tournament is older than this
rank_gor_tolerance = 300     # warn if declared rank and GoR differ by more than this
extra_fields = []            # additional player data, e.g. ["Email", "Fee paid", "Age group"]
"""


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
class PairingSettings:
    club_penalty: float = 150.0
    random_seed: int = 12345


@dataclass
class RegistrationSettings:
    gor_outdated_years: int = 5
    rank_gor_tolerance: int = 300
    extra_fields: list[str] = field(default_factory=list)


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
            club_penalty=_get(p, "club_penalty", float, 150.0, "pairing"),
            random_seed=_get(p, "random_seed", int, 12345, "pairing"),
        ),
        registration=RegistrationSettings(
            gor_outdated_years=_get(g, "gor_outdated_years", int, 5, "registration"),
            rank_gor_tolerance=_get(g, "rank_gor_tolerance", int, 300, "registration"),
            extra_fields=[f.strip() for f in _get(g, "extra_fields", list, [], "registration")],
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
    if cfg.pairing.club_penalty < 0:
        raise ConfigError("pairing.club_penalty must not be negative")
    from .players import is_builtin_column
    seen = set()
    for name in cfg.registration.extra_fields:
        if not name:
            raise ConfigError("registration.extra_fields: field names must not be empty")
        if is_builtin_column(name):
            raise ConfigError(f"registration.extra_fields: {name!r} is already a standard column")
        if name.lower() in seen:
            raise ConfigError(f"registration.extra_fields: {name!r} is listed twice")
        seen.add(name.lower())


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

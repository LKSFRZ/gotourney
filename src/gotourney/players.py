"""Loading and saving ``players.ods``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Player
from .ods import Column, OdsError, read_sheet, require_columns, write_sheet
from .rank import Rank, RankError

PLAYERS_FILE = "players.ods"
SHEET_NAME = "Players"

REQUIRED = ["ID", "Surname", "First name", "Rank", "GoR"]

_NO = {"", "0", "-", "no", "n", "nein"}


def round_column(n: int) -> str:
    return f"R{n}"


BUILTIN_COLUMNS = ["ID", "Surname", "First name", "Rank", "GoR", "EGD PIN", "Country", "Club",
                   "Joker", "EGD GoR", "Last EGD tournament", "Notes"]
_BUILTIN_KEYS = {c.lower() for c in BUILTIN_COLUMNS}


def is_builtin_column(name: str) -> bool:
    """Columns the tools manage themselves (including round columns R1, R2, ...)."""
    n = name.strip().lower()
    return n in _BUILTIN_KEYS or bool(re.fullmatch(r"r\d+", n))


def merge_fields(*groups) -> list[str]:
    """Field names in order of first appearance, without (case-insensitive) duplicates."""
    result, seen = [], set()
    for group in groups:
        for name in group:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(name.strip())
    return result


def columns(rounds: int, extra_fields=()) -> list[Column]:
    return (
        [
            Column("ID", 1.2),
            Column("Surname", 4.0),
            Column("First name", 3.5),
            Column("Rank", 1.4),
            Column("GoR", 1.6),
            Column("EGD PIN", 2.3),
            Column("Country", 1.7),
            Column("Club", 1.7),
            Column("Joker", 1.4),
        ]
        + [Column(round_column(i), 1.0) for i in range(1, rounds + 1)]
        + [
            Column("EGD GoR", 1.9),
            Column("Last EGD tournament", 3.8),
        ]
        + [Column(f, max(2.5, min(6.0, 0.25 * len(f) + 1.0))) for f in extra_fields]
        + [Column("Notes", 6.0)]
    )


@dataclass
class PlayerList:
    players: list[Player]
    warnings: list[str]
    extra_fields: list[str] = field(default_factory=list)   # the configured additional fields
    other_fields: list[str] = field(default_factory=list)   # other columns in the file (kept, not shown)

    def by_id(self) -> dict[int, Player]:
        return {p.id: p for p in self.players}


def _flag(text: str) -> bool:
    return text.strip().lower() not in _NO


def _number(text: str, what: str, where: str) -> float | None:
    if text == "":
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        raise OdsError(f"{where}: {what} {text!r} is not a number") from None


def load_players(directory: Path, rounds: int, extra_fields=()) -> PlayerList:
    """Read players.ods. Raises OdsError on problems that make the file unusable.

    ``extra_fields`` are the additional fields from the settings; only these are shown and used.
    Data in other unknown columns (e.g. a field removed from the settings) is kept in
    ``Player.extra`` so it survives saving; those columns are listed in ``other_fields``.
    """
    path = Path(directory) / PLAYERS_FILE
    sheet = read_sheet(path)
    require_columns(sheet, path, REQUIRED)
    players: list[Player] = []
    warnings: list[str] = []
    errors: list[str] = []
    seen_ids: dict[int, int] = {}
    headers = {h.strip().upper() for h in sheet.header}
    extra = sorted(
        (h for h in headers if h[:1] == "R" and h[1:].isdigit() and int(h[1:]) > rounds),
        key=lambda h: int(h[1:]),
    )
    if extra:
        warnings.append(
            f"{path.name}: column(s) {', '.join(extra)} ignored, the tournament has {rounds} rounds"
        )
    configured = merge_fields(extra_fields)
    fields = merge_fields(configured, (h for h in sheet.header if h.strip() and not is_builtin_column(h)))
    # Rounds added later (no column in the file yet) count as played by everyone.
    new_rounds = {i for i in range(1, rounds + 1) if round_column(i) not in headers}
    for row in sheet.rows:
        where = f"{path.name}, row {row.line}"
        try:
            id_text = row.text("ID")
            if id_text == "":
                raise OdsError(f"{where}: missing ID")
            try:
                pid = int(float(id_text))
            except ValueError:
                raise OdsError(f"{where}: ID {id_text!r} is not a number") from None
            if pid in seen_ids:
                raise OdsError(f"{where}: ID {pid} already used in row {seen_ids[pid]}")
            seen_ids[pid] = row.line

            rank_text = row.text("Rank")
            rank = None
            if rank_text:
                try:
                    rank = Rank.parse(rank_text)
                except RankError as e:
                    raise OdsError(f"{where}: {e}") from None
            gor = _number(row.text("GoR"), "GoR", where)
            egd_gor = _number(row.text("EGD GoR"), "EGD GoR", where)
            pin = row.text("EGD PIN")
            if pin and not (pin.isdigit() and len(pin) == 8):
                warnings.append(f"{where}: EGD PIN {pin!r} does not look like an 8-digit PIN")
            player_rounds = {i for i in range(1, rounds + 1) if _flag(row.text(round_column(i)))}
            player_rounds |= new_rounds
            players.append(
                Player(
                    id=pid,
                    surname=row.text("Surname"),
                    first_name=row.text("First name"),
                    rank=rank,
                    gor=gor,
                    pin=pin,
                    country=row.text("Country").upper(),
                    club=row.text("Club"),
                    egd_gor=egd_gor,
                    egd_last_tournament=row.text("Last EGD tournament"),
                    joker=_flag(row.text("Joker")),
                    rounds=player_rounds,
                    notes=row.text("Notes"),
                    extra={f: row.text(f) for f in fields if row.text(f)},
                )
            )
        except OdsError as e:
            errors.append(str(e))
    if errors:
        raise OdsError("\n".join(errors))
    return PlayerList(players, warnings, configured, fields[len(configured):])


def save_players(directory: Path, players: list[Player], rounds: int, extra_fields=()) -> Path:
    """Write players.ods. Additional fields: those given (configured), then any other column
    that still holds data. Empty columns of fields no longer configured disappear."""
    path = Path(directory) / PLAYERS_FILE
    fields = merge_fields(extra_fields, (k for p in players for k in p.extra))
    rows = []
    for p in sorted(players, key=lambda p: p.id):
        rows.append(
            [
                p.id,
                p.surname,
                p.first_name,
                str(p.rank) if p.rank else "",
                round(p.gor) if p.gor is not None and float(p.gor).is_integer() else p.gor,
                p.pin,
                p.country,
                p.club,
                "x" if p.joker else "",
            ]
            + ["x" if p.plays(i) else "" for i in range(1, rounds + 1)]
            + [p.egd_gor, p.egd_last_tournament]
            + [extra_value(p, f) for f in fields]
            + [p.notes]
        )
    write_sheet(path, SHEET_NAME, columns(rounds, fields), rows)
    return path


def extra_value(player: Player, name: str) -> str:
    """Value of an additional field (field names match case-insensitively)."""
    if name in player.extra:
        return player.extra[name]
    key = name.strip().lower()
    return next((v for k, v in player.extra.items() if k.strip().lower() == key), "")


def field_value(player: Player, name: str) -> str:
    """Value of a column usable in pairing rules: Club, Country, Rank or an additional field."""
    key = name.strip().lower()
    if key == "club":
        return player.club
    if key == "country":
        return player.country
    if key == "rank":
        return str(player.rank or "")
    return extra_value(player, name)


def starting_rating(player: Player) -> float:
    """Starting TGoR: the GoR column, or the value of the declared rank."""
    if player.gor is not None:
        return float(player.gor)
    if player.rank is not None:
        return float(player.rank.to_gor())
    raise ValueError(f"player {player.id} ({player.name}) has neither GoR nor rank")

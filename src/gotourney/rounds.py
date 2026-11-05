"""Loading and saving round files ``round_<r>.ods``.

Sheet "Pairing": one row per board. Sheet "Not playing": players of the tournament who do not
play this round (joker, not registered) - for information only, it is not read back.
A third sheet "Participants" (written by ``pair --template``) lists the players of the round
to help with manual pairings; it is not read back either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import Game, Result, ResultError
from .ods import Column, OdsError, read_sheet, require_columns, write_sheets

PAIRING_SHEET = "Pairing"
REQUIRED = ["White ID", "Black ID", "Result"]

COLUMNS = [
    Column("Board", 1.4), Column("White ID", 1.8), Column("White name", 5.0),
    Column("White TGoR", 2.1), Column("Black ID", 1.8), Column("Black name", 5.0),
    Column("Black TGoR", 2.1), Column("Handicap", 1.9), Column("Komi", 1.4),
    Column("Manual", 1.6), Column("Result", 2.0),
]


def round_file(directory: Path, r: int) -> Path:
    return Path(directory) / f"round_{r}.ods"


@dataclass
class RoundGames:
    number: int
    games: list[Game]
    path: Path
    missing_handicap: set[int] = field(default_factory=set)   # boards (index) with empty handicap
    missing_komi: set[int] = field(default_factory=set)

    @property
    def has_results(self) -> bool:
        return any(g.result is not None for g in self.games)

    @property
    def complete(self) -> bool:
        return all(g.result is not None for g in self.games)


def _int(text: str, what: str, where: str) -> int | None:
    if text == "":
        return None
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise OdsError(f"{where}: {what} {text!r} is not a number") from None
    if not value.is_integer():
        raise OdsError(f"{where}: {what} {text!r} must be a whole number")
    return int(value)


def load_round(directory: Path, r: int, default_komi: float = 6.5) -> RoundGames:
    path = round_file(directory, r)
    sheet = read_sheet(path, PAIRING_SHEET, fallback_first=True)
    require_columns(sheet, path, REQUIRED)
    games: list[Game] = []
    missing_h: set[int] = set()
    missing_k: set[int] = set()
    errors: list[str] = []
    for row in sheet.rows:
        where = f"{path.name}, row {row.line}"
        try:
            white = _int(row.text("White ID"), "White ID", where)
            black = _int(row.text("Black ID"), "Black ID", where)
            if white is None and black is None:
                continue      # e.g. a row with only notes
            if white is None or black is None:
                raise OdsError(f"{where}: both White ID and Black ID are needed")
            if white == black:
                raise OdsError(f"{where}: player {white} cannot play against themselves")
            handicap = _int(row.text("Handicap"), "Handicap", where)
            if handicap is not None and not 0 <= handicap <= 9:
                raise OdsError(f"{where}: handicap must be between 0 and 9")
            komi_text = row.text("Komi").replace(",", ".")
            try:
                komi = float(komi_text) if komi_text else None
            except ValueError:
                raise OdsError(f"{where}: komi {komi_text!r} is not a number") from None
            try:
                result = _parse_result(row.get("Result"))
            except ResultError as e:
                raise OdsError(f"{where}: {e}") from None
            board = _int(row.text("Board"), "Board", where)
            idx = len(games)
            if handicap is None:
                missing_h.add(idx)
            if komi is None:
                missing_k.add(idx)
            games.append(Game(
                board=board if board is not None else idx + 1,
                white=white, black=black,
                handicap=handicap or 0,
                komi=komi if komi is not None else default_komi,
                result=result,
                manual=row.text("Manual").strip().lower() not in ("", "0", "-", "no"),
            ))
        except OdsError as e:
            errors.append(str(e))
    seen: dict[int, int] = {}
    for g in games:
        for pid in g.players():
            if pid in seen:
                errors.append(f"{path.name}: player {pid} is on board {seen[pid]} and board {g.board}")
            seen[pid] = g.board
    if errors:
        raise OdsError("\n".join(errors))
    return RoundGames(r, games, path, missing_h, missing_k)


def _parse_result(value) -> Result | None:
    if isinstance(value, float):
        # LibreOffice may turn "1:0" into a time or "1-0" into a number; reject clearly
        raise ResultError(f"result cell contains a number ({value:g}); enter e.g. 1-0 as text")
    return Result.parse(value or "")


def save_round(path: Path, games: list[Game], names: dict[int, str], tgor: dict[int, float],
               not_playing: list[tuple[int, str, str]] = (),
               participants: list[tuple[int, str, float, str]] | None = None) -> None:
    rows = []
    for g in games:
        rows.append([
            g.board, g.white, names.get(g.white, "?"), round(tgor[g.white]) if g.white in tgor else None,
            g.black, names.get(g.black, "?"), round(tgor[g.black]) if g.black in tgor else None,
            g.handicap, g.komi, "x" if g.manual else "", g.result.value if g.result else "",
        ])
    sheets = [(PAIRING_SHEET, COLUMNS, rows)]
    sheets.append(("Not playing", [Column("ID", 1.4), Column("Name", 5.5), Column("Reason", 5.0)],
                   [list(x) for x in not_playing]))
    if participants is not None:
        sheets.append(("Participants",
                       [Column("ID", 1.4), Column("Name", 5.5), Column("TGoR", 2.0), Column("Club", 2.0)],
                       [[pid, name, round(t), club] for pid, name, t, club in participants]))
    write_sheets(path, sheets)

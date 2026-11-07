"""Loading and saving round files ``round_<r>.ods``.

Sheet "Pairing": one row per board. Results are entered with an ``x`` in the "White win",
"Draw" or "Black win" column. Forfeits: ``x!`` for the winner, ``!`` in both win columns if
both lose. Only the IDs are read back; the player columns
(colour circle, rank and name) are for reading only. Sheet "Not playing": players of the tournament who do not
play this round (joker, not registered) - for information only, it is not read back.
A third sheet "Participants" (written by ``pair --template``) lists the players of the round
to help with manual pairings; it is not read back either.

Boards with an "x" in the Finalized column are never changed by ``gotourney pair``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import Game, Player, Result, ResultError
from .ods import Column, OdsError, read_sheet, require_columns, write_sheets
from .rank import Rank

PAIRING_SHEET = "Pairing"
REQUIRED = ["White ID", "Black ID", "White win", "Draw", "Black win"]
WHITE_STONE = "\u25cb"   # ○
BLACK_STONE = "\u25cf"   # ●

COLUMNS = [
    Column("Board", 1.4, "center"), Column("White ID", 1.8), Column("White TGoR", 2.1),
    Column("White", 5.8), Column("White win", 2.0, "center"), Column("Draw", 1.6, "center"),
    Column("Black win", 2.0, "center"),
    Column("Black", 5.8), Column("Black TGoR", 2.1), Column("Black ID", 1.8),
    Column("Handicap", 1.9, "center"), Column("Komi", 1.4, "center"), Column("Finalized", 2.0, "center"),
]

# result -> (white win, draw, black win) marks
MARKS = {
    Result.WHITE_WINS: ("x", "", ""),
    Result.BLACK_WINS: ("", "", "x"),
    Result.JIGO: ("", "x", ""),
    Result.WHITE_WINS_FORFEIT: ("x!", "", ""),
    Result.BLACK_WINS_FORFEIT: ("", "", "x!"),
    Result.BOTH_LOSE_FORFEIT: ("!", "", "!"),
}
_FROM_MARKS = {v: k for k, v in MARKS.items()}
_ALIASES = {"x": "x", "\u2713": "x", "\u2714": "x", "x!": "x!", "!x": "x!", "!": "!"}


def player_label(p: Player) -> str:
    """'5d Maekawa Kaku' - registered rank in front of the name."""
    rank = p.rank
    if rank is None and p.gor is not None:
        rank = Rank.from_gor(p.gor)
    return f"{rank or ''} {p.name}".strip()


def parse_marks(white_cell, draw_cell, black_cell) -> Result | None:
    """Result from the White win / Draw / Black win columns; None if all are empty."""
    marks = []
    for cell in (white_cell, draw_cell, black_cell):
        if isinstance(cell, float):
            raise ResultError(f"result column contains a number ({cell:g}); mark with x")
        t = str(cell or "").strip().lower().replace(" ", "")
        if t and t not in _ALIASES:
            raise ResultError(f"invalid mark {cell!r} (use x; x! / ! for forfeits)")
        marks.append(_ALIASES.get(t, ""))
    if marks == ["", "", ""]:
        return None
    result = _FROM_MARKS.get(tuple(marks))
    if result is None:
        shown = " / ".join(m or "empty" for m in marks)
        raise ResultError(
            f"marks {shown} (White win / Draw / Black win) do not give a result: put one x in "
            f"White win, Draw or Black win; forfeits: x! for the winner, ! in both win columns if both lose")
    return result


def round_file(directory: Path, r: int) -> Path:
    return Path(directory) / f"round_{r}.ods"


@dataclass
class UnresolvedBoard:
    """A manual board where the director typed (part of) a name instead of a player ID."""

    line: int                  # row in the sheet
    white: int | None          # ID if given
    black: int | None
    white_text: str            # what was typed in the White / Black column
    black_text: str
    handicap: int | None
    komi: float | None


@dataclass
class RoundGames:
    number: int
    games: list[Game]
    path: Path
    missing_handicap: set[int] = field(default_factory=set)   # boards (index) with empty handicap
    missing_komi: set[int] = field(default_factory=set)
    missing_board: set[int] = field(default_factory=set)       # boards (index) without a board number
    unresolved: list[UnresolvedBoard] = field(default_factory=list)

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
    missing_b: set[int] = set()
    unresolved: list[UnresolvedBoard] = []
    errors: list[str] = []
    for row in sheet.rows:
        where = f"{path.name}, row {row.line}"
        try:
            white = _int(row.text("White ID"), "White ID", where)
            black = _int(row.text("Black ID"), "Black ID", where)
            white_text, black_text = name_text(row.text("White")), name_text(row.text("Black"))
            if white is None and black is None and not white_text and not black_text:
                continue      # e.g. a row with only notes
            handicap = _int(row.text("Handicap"), "Handicap", where)
            if handicap is not None and not 0 <= handicap <= 9:
                raise OdsError(f"{where}: handicap must be between 0 and 9")
            komi_text = row.text("Komi").replace(",", ".")
            try:
                komi = float(komi_text) if komi_text else None
            except ValueError:
                raise OdsError(f"{where}: komi {komi_text!r} is not a number") from None
            if white is None or black is None:
                if (white is None and not white_text) or (black is None and not black_text):
                    raise OdsError(f"{where}: give both players (ID, or a name in the White / Black column)")
                unresolved.append(UnresolvedBoard(row.line, white, black, white_text, black_text,
                                                  handicap, komi))
                continue
            if white == black:
                raise OdsError(f"{where}: player {white} cannot play against themselves")
            try:
                result = parse_marks(row.get("White win"), row.get("Draw"), row.get("Black win"))
            except ResultError as e:
                raise OdsError(f"{where}: {e}") from None
            board = _int(row.text("Board"), "Board", where)
            idx = len(games)
            if handicap is None:
                missing_h.add(idx)
            if komi is None:
                missing_k.add(idx)
            if board is None:
                missing_b.add(idx)
            games.append(Game(
                board=board if board is not None else idx + 1,
                white=white, black=black,
                handicap=handicap or 0,
                komi=komi if komi is not None else default_komi,
                result=result,
                finalized=_flag(row.text("Finalized") or row.text("Manual")),   # "Manual": older files
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
    return RoundGames(r, games, path, missing_h, missing_k, missing_b, unresolved)


def read_not_playing(path: Path) -> list[tuple[int, str, str]]:
    """The 'Not playing' sheet of a round file (for rewriting the file unchanged)."""
    try:
        sheet = read_sheet(path, "Not playing")
    except OdsError:
        return []
    rows = []
    for row in sheet.rows:
        try:
            rows.append((int(float(row.text("ID"))), row.text("Name"), row.text("Reason")))
        except ValueError:
            continue
    return rows


def _flag(text: str) -> bool:
    return text.strip().lower() not in ("", "0", "-", "no", "n")


def name_text(text: str) -> str:
    """A player cell without the colour stone: '○ 5d Becker Anna' -> '5d Becker Anna'."""
    return text.replace(WHITE_STONE, " ").replace(BLACK_STONE, " ").strip()


def save_round(path: Path, games: list[Game], labels: dict[int, str], tgor: dict[int, float],
               not_playing: list[tuple[int, str, str]] = (),
               participants: list[tuple[int, str, float, str]] | None = None) -> None:
    """Write a round file. ``labels`` = player ID -> 'rank name' (see player_label)."""
    rows = []
    for g in games:
        w_mark, d_mark, b_mark = MARKS[g.result] if g.result else ("", "", "")
        rows.append([
            g.board,
            g.white, round(tgor[g.white]) if g.white in tgor else None,
            f"{WHITE_STONE} {labels.get(g.white, '?')}", w_mark, d_mark,
            b_mark, f"{BLACK_STONE} {labels.get(g.black, '?')}",
            round(tgor[g.black]) if g.black in tgor else None, g.black,
            g.handicap, g.komi, "x" if g.finalized else "",
        ])
    sheets = [(PAIRING_SHEET, COLUMNS, rows)]
    sheets.append(("Not playing", [Column("ID", 1.4), Column("Name", 5.5), Column("Reason", 5.0)],
                   [list(x) for x in not_playing]))
    if participants is not None:
        sheets.append(("Participants",
                       [Column("ID", 1.4), Column("Name", 5.5), Column("TGoR", 2.0), Column("Club", 2.0)],
                       [[pid, name, round(t), club] for pid, name, t, club in participants]))
    write_sheets(path, sheets, landscape=True)

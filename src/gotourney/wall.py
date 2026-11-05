"""Standings, the wall list (wall_list.ods) and the EGD result file (.h9)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .ods import Column, read_sheet, require_columns, write_sheets
from .pairing import rng_for
from .rank import Rank
from .tournament import Tournament

WALL_FILE = "wall_list.ods"
STANDINGS_FILE = "standings.ods"
WALL_SHEET = "Wall list"
NO_COUNTRY = "XX"
NO_CLUB = "XXXX"


class WallError(Exception):
    pass


# ---------------------------------------------------------------- places

def ranking(t: Tournament, after_round: int | None = None) -> list[int]:
    """Player IDs in order of place: higher TGoR (rounded), then lower starting GoR, then random."""
    r = t.last_round if after_round is None else after_round
    ratings = t.ratings[r]
    rng = rng_for(t.cfg, r, "final-tiebreak")
    draw = {pid: rng.random() for pid in sorted(t.players)}
    return sorted(t.players, key=lambda pid: (-round(ratings[pid]), t.start[pid], draw[pid]))


def format_wins(w: float) -> str:
    return f"{w:g}" if w != int(w) else str(int(w))


# ---------------------------------------------------------------- standings

def standings_rows(t: Tournament, after_round: int) -> tuple[list[Column], list[list]]:
    order = ranking(t, after_round)
    cols = [Column("Place", 1.4), Column("ID", 1.2), Column("Name", 5.5), Column("Rank", 1.4),
            Column("Club", 1.6), Column("Start GoR", 2.0)]
    cols += [Column(f"after R{r}", 2.0) for r in range(1, after_round + 1)]
    cols += [Column("Games", 1.6), Column("Wins", 1.4), Column("TGoR", 1.8)]
    rows = []
    for place, pid in enumerate(order, start=1):
        p = t.players[pid]
        games = sum(1 for h in t.history[pid] if h.round <= after_round and h.counts_as_played)
        wins = sum(h.score for h in t.history[pid]
                   if h.round <= after_round and h.counts_as_played and h.score is not None)
        rows.append([place, pid, p.name, str(p.rank or ""), p.club, round(t.start[pid])]
                    + [round(t.ratings[r][pid]) for r in range(1, after_round + 1)]
                    + [games, wins, round(t.ratings[after_round][pid])])
    return cols, rows


def write_standings(t: Tournament, after_round: int) -> Path:
    cols, rows = standings_rows(t, after_round)
    path = t.directory / STANDINGS_FILE
    write_sheets(path, [(f"After round {after_round}", cols, rows)])
    return path


# ---------------------------------------------------------------- wall list

def round_cell(t: Tournament, pid: int, r: int, place_of: dict[int, int]) -> str:
    """EGD notation for one round: '12+/w2', '3-/b', '7=/w', or '0=' (not played / forfeit)."""
    game = next((h for h in t.history[pid] if h.round == r), None)
    if game is None or game.forfeit:
        return "0="
    if not game.has_result:
        raise WallError(f"round {r}: result missing for {t.name(pid)}")
    sign = {1.0: "+", 0.0: "-", 0.5: "="}[game.score]
    return f"{place_of[game.opponent]}{sign}/{game.colour}{game.handicap or ''}"


WALL_BASE_COLUMNS = ["Place", "Surname", "First name", "Rank", "Country", "Club",
                     "Wins", "Start GoR", "Final TGoR"]


def write_wall_list(t: Tournament) -> Path:
    if t.last_round < t.cfg.tournament.rounds:
        t.warnings.append(f"only {t.last_round} of {t.cfg.tournament.rounds} rounds have been played")
    for r, rg in t.rounds.items():
        if not rg.complete:
            raise WallError(f"round {r} has missing results; enter them first")
    order = ranking(t)
    place_of = {pid: i for i, pid in enumerate(order, start=1)}
    n = t.last_round
    final = t.final_ratings()
    cols = [Column("Place", 1.4), Column("Surname", 4.0), Column("First name", 3.5),
            Column("Rank", 1.4), Column("Country", 1.7), Column("Club", 1.7), Column("Wins", 1.4),
            Column("Start GoR", 2.0), Column("Final TGoR", 2.2)]
    cols += [Column(f"R{r}", 1.9) for r in range(1, n + 1)]
    cols += [Column("EGD PIN", 2.3)]
    rows = []
    for pid in order:
        p = t.players[pid]
        rank = p.rank or Rank.from_gor(t.start[pid])
        rows.append([place_of[pid], p.surname, p.first_name, str(rank), p.country, p.club,
                     t.wins(pid), round(t.start[pid]), round(final[pid])]
                    + [round_cell(t, pid, r, place_of) for r in range(1, n + 1)]
                    + [p.pin])
    hist_cols = [Column("Place", 1.4), Column("Name", 5.5), Column("Start", 1.8)] + \
        [Column(f"after R{r}", 2.0) for r in range(1, n + 1)]
    hist = [[place_of[pid], t.players[pid].name, round(t.start[pid])]
            + [round(t.ratings[r][pid]) for r in range(1, n + 1)] for pid in order]
    path = t.directory / WALL_FILE
    write_sheets(path, [(WALL_SHEET, cols, rows), ("TGoR history", hist_cols, hist)])
    return path


# ---------------------------------------------------------------- .h9 export

@dataclass
class WallLine:
    place: int
    surname: str
    first_name: str
    rank: str
    country: str
    club: str
    wins: str
    start: str
    final: str
    results: list[str]
    pin: str


_CELL_RE = re.compile(r"^(0=|\d+[+\-=]/[wb]\d?)$")


def read_wall_list(directory: Path) -> tuple[list[WallLine], list[str]]:
    path = Path(directory) / WALL_FILE
    sheet = read_sheet(path, WALL_SHEET, fallback_first=True)
    require_columns(sheet, path, WALL_BASE_COLUMNS)
    round_cols = sorted((h for h in sheet.header if re.fullmatch(r"R\d+", h.strip(), re.I)),
                        key=lambda h: int(h.strip()[1:]))
    lines, errors, warnings = [], [], []
    for row in sheet.rows:
        where = f"{path.name}, row {row.line}"
        try:
            place = int(float(row.text("Place")))
        except ValueError:
            errors.append(f"{where}: invalid place {row.text('Place')!r}")
            continue
        results = []
        for c in round_cols:
            cell = row.text(c).replace(" ", "") or "0="
            if not _CELL_RE.match(cell):
                errors.append(f"{where}, column {c}: invalid result {cell!r} (e.g. 12+/w2, 3-/b, 0=)")
            results.append(cell)
        wins = row.get("Wins")
        lines.append(WallLine(
            place=place, surname=row.text("Surname"), first_name=row.text("First name"),
            rank=row.text("Rank"), country=row.text("Country"), club=row.text("Club"),
            wins=format_wins(wins) if isinstance(wins, float) else row.text("Wins"),
            start=row.text("Start GoR"), final=row.text("Final TGoR"), results=results,
            pin=row.text("EGD PIN"),
        ))
    places = [ln.place for ln in lines]
    if sorted(places) != list(range(1, len(lines) + 1)):
        errors.append(f"{path.name}: places must be 1 to {len(lines)}, each exactly once")
    valid = set(places)
    for ln in lines:
        for i, cell in enumerate(ln.results, start=1):
            m = re.match(r"^(\d+)", cell)
            if m and cell != "0=" and int(m.group(1)) not in valid:
                errors.append(f"{path.name}: place {ln.place}, round {i}: opponent place {m.group(1)} does not exist")
        if not ln.country:
            warnings.append(f"place {ln.place} {ln.surname}: no country, written as {NO_COUNTRY}")
    if errors:
        raise WallError("\n".join(errors))
    return sorted(lines, key=lambda ln: ln.place), warnings


def _name_part(s: str) -> str:
    return re.sub(r"\s+", "_", s.strip())


def h9_text(cfg: Config, lines: list[WallLine]) -> str:
    t = cfg.tournament
    header = [
        f"; TC[{t.code}]",
        f"; CL[{t.klass}]",
        f"; EV[{t.name}]",
        f"; PC[{t.place}]",
        f"; DT[{','.join(t.dates)}]",
        f"; HA[h{cfg.handicap.reduction}]",
        f"; KM[{cfg.handicap.komi_even:g}]",
        f"; TM[{t.time}]",
        f"; CM[{t.comment}]",
        ";.",
    ]
    names = [f"{_name_part(ln.surname)} {_name_part(ln.first_name)}".strip() for ln in lines]
    clubs = [_name_part(ln.club) or NO_CLUB for ln in lines]
    w_place = max((len(str(ln.place)) for ln in lines), default=1)
    w_name = max((len(n) for n in names), default=4)
    w_rank = max((len(ln.rank) for ln in lines), default=2)
    w_club = max((len(c) for c in clubs), default=4)
    w_wins = max((len(ln.wins) for ln in lines), default=1)
    w_start = max((len(ln.start) for ln in lines), default=4)
    w_final = max((len(ln.final) for ln in lines), default=4)
    w_cell = max((len(c) for ln in lines for c in ln.results), default=2)
    out = list(header)
    for ln, name, club in zip(lines, names, clubs):
        cells = " ".join(f"{c:<{w_cell}}" for c in ln.results)
        text = (f"{ln.place:>{w_place}} {name:<{w_name}} {ln.rank:>{w_rank}} "
                f"{(ln.country or NO_COUNTRY):<2} {club:<{w_club}} "
                f"{ln.wins:>{w_wins}} {ln.start:>{w_start}} {ln.final:>{w_final}}  {cells}")
        if ln.pin:
            text += f" |{ln.pin}"
        out.append(text.rstrip())
    return "\n".join(out) + "\n"


def h9_filename(cfg: Config) -> str:
    if cfg.tournament.code:
        return f"{cfg.tournament.code}.h9"
    base = re.sub(r"[^A-Za-z0-9]+", "_", cfg.tournament.name).strip("_") or "tournament"
    return f"{base}.h9"

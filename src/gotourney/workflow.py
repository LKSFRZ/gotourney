"""The tournament workflow without any user interface.

Used by the command line and the web interface. Functions report problems as ``Problem``
exceptions with a machine-readable ``code`` (so each interface can explain them in its own way)
and ask questions (e.g. "is 'Becker' Becker Anna?") through a ``Resolver`` callback.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import ConfigError
from .i18n import TranslationError, Translator, get_translator
from .models import Game, Player
from .ods import OdsError
from .rounds import RoundGames, player_label, read_not_playing, round_file, save_round
from .tournament import Tournament, TournamentError


# ---------------------------------------------------------------- problems

@dataclass
class Problem(Exception):
    """Something that stops a step. ``code`` identifies the situation, ``data`` holds details."""

    code: str
    message: str
    data: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def lock_file(path: Path) -> Path:
    return path.with_name(f".~lock.{path.name}#")


def is_open_in_libreoffice(path: Path) -> bool:
    return lock_file(path).exists()


def check_writable(path: Path) -> None:
    if is_open_in_libreoffice(path):
        raise Problem("file_open", f"{path} is open in LibreOffice. Save and close it first, then try again.",
                      {"path": path})


def load(directory: Path, names_allowed_in_round: int | None = None) -> Tournament:
    try:
        return Tournament.load(directory, names_allowed_in_round=names_allowed_in_round)
    except (ConfigError, OdsError, TournamentError) as e:
        raise Problem("load", str(e)) from None


def load_for_display(directory: Path) -> Tournament:
    """Like load(), but allows boards given by name in the newest round file (to show them)."""
    try:
        return load(directory)
    except Problem:
        last = max((r for r in range(1, 100) if round_file(directory, r).exists()), default=0)
        if not last:
            raise
        return load(directory, names_allowed_in_round=last)


def translator(t: Tournament) -> tuple[Translator, list[str]]:
    try:
        return get_translator(t.cfg, t.directory)
    except TranslationError as e:
        raise Problem("translation", str(e)) from None


# ---------------------------------------------------------------- tournament status

@dataclass
class Status:
    """Where the tournament stands, for 'next step' hints and the dashboard.

    phase: no_players | registration | names_pending | paired | running | round_complete | finished
    """

    phase: str
    round: int = 0                  # the round the phase refers to
    rounds: int = 0                 # number of rounds of the tournament
    players: int = 0
    boards: int = 0
    missing: int = 0                # missing results in that round
    started: bool = False


def round_started(t: Tournament, r: int) -> bool:
    rg = t.rounds.get(r)
    return bool(rg and rg.games and all(g.finalized for g in rg.games))


def status(t: Tournament) -> Status:
    s = Status("registration", rounds=t.cfg.tournament.rounds, players=len(t.players))
    if not t.players:
        s.phase = "no_players"
        return s
    r = t.last_round
    if r == 0:
        return s
    rg = t.rounds[r]
    s.round, s.boards, s.started = r, len(rg.games), round_started(t, r)
    s.missing = sum(1 for g in rg.games if g.result is None)
    if rg.unresolved:
        s.phase = "names_pending"
    elif not s.started and not rg.has_results:
        s.phase = "paired"
    elif s.missing:
        s.phase = "running"
    elif r < s.rounds:
        s.phase = "round_complete"
    else:
        s.phase = "finished"
    return s


# ---------------------------------------------------------------- pairing

class Resolver(Protocol):
    """Asks which player is meant by a name typed into a round file.

    Gets the place ('row 3, White'), the typed text and the candidates (best first); returns the
    chosen player, or None to cancel."""

    def __call__(self, where: str, text: str, candidates: list[Player], round_no: int) -> Player | None: ...


@dataclass
class PairOutcome:
    tournament: Tournament
    round: int
    games: list[Game]
    sitting_out: list[tuple[int, str]]
    rule_hits: Counter
    ratings: dict[int, float]
    kept: int                       # finalized boards kept unchanged
    repaired: int                   # boards without 'Finalized' that were paired again
    new_boards: list[int]           # board numbers of the boards paired now
    started_before: bool            # the round had been started (latecomers were paired)
    warnings: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)      # "row 3: A - B" for boards given by name
    pdfs: list[Path] = field(default_factory=list)
    pdf_error: str = ""


def _check_can_pair(t: Tournament, round_no: int, force: bool) -> None:
    rounds = t.cfg.tournament.rounds
    if not 1 <= round_no <= rounds:
        raise Problem("round_range", f"the tournament has rounds 1 to {rounds}", {"rounds": rounds})
    if round_no > t.last_round + 1:
        nxt = t.last_round + 1
        raise Problem("not_next", f"Round {nxt} has not been paired yet; rounds are paired one after the other.",
                      {"next": nxt})
    for r in range(1, round_no):
        rg = t.rounds.get(r)
        missing = [g for g in rg.games if g.result is None] if rg else []
        if missing:
            raise Problem(
                "previous_incomplete",
                f"Round {round_no} cannot be paired yet: round {r} still has {len(missing)} missing "
                f"result(s). The pairing depends on the TGoR after round {r}.",
                {"round": r, "boards": [(g.board, t.players[g.white].name, t.players[g.black].name)
                                        for g in missing]})
    later = [r for r in t.rounds if r > round_no]
    if later:
        raise Problem("later_exists", f"round {later[0]} already exists; re-pairing round {round_no} is not "
                      f"possible", {"round": later[0]})
    existing = t.rounds.get(round_no)
    if existing:
        open_results = [g.board for g in existing.games if g.result is not None and not g.finalized]
        if open_results and not force:
            raise Problem(
                "open_results",
                f"round_{round_no}.ods: board(s) {', '.join(map(str, open_results))} have results but are not "
                f"finalized. Start the round (or put an x in the Finalized column) to keep them, or pair "
                f"again with force (their results are lost).", {"boards": open_results})


def finalized_boards(t: Tournament, rg: RoundGames, round_no: int, ratings: dict[int, float],
                     warnings: list[str] | None = None) -> list[Game]:
    """The finalized boards of a round file, with default handicap/komi/colours filled in where the
    handicap was left empty. Boards without a board number get one later (number_boards)."""
    from .pairing import PairingError, check_rule_fields, pair_rules, rng_for, setup_game

    rng = rng_for(t.cfg, round_no, "manual")
    kept = []
    for i, g in enumerate(rg.games):
        if not g.finalized:
            continue
        if i in rg.missing_handicap:
            d = setup_game(t, round_no, g.white, g.black, ratings, rng, finalized=True)
            g.white, g.black, g.handicap, g.komi = d.white, d.black, d.handicap, d.komi
        elif i in rg.missing_komi:
            g.komi = t.cfg.handicap.komi_handicap if g.handicap > 0 else t.cfg.handicap.komi_even
        if i in rg.missing_board:
            g.board = 0
        kept.append(g)
        if warnings is None:
            continue
        a, b = t.players[g.white].name, t.players[g.black].name
        if frozenset(g.players()) in t.played_pairs(before_round=round_no):
            warnings.append(f"finalized board: {a} and {b} already played each other")
        try:
            check_rule_fields(t)
            hard = [r.describe() for r in pair_rules(t, g.white, g.black)[2] if r.hard]
        except PairingError:
            hard = []
        if hard:
            warnings.append(f"finalized board: {a} - {b} breaks rule {'; '.join(hard)}")
    return kept


def describe_candidate(p: Player, round_no: int) -> str:
    extra = "" if p.plays(round_no) else f", not registered for round {round_no}"
    return f"{p.name} ({p.rank or '?'}, ID {p.id}{', ' + p.club if p.club else ''}{extra})"


def resolve_names(t: Tournament, rg: RoundGames, round_no: int, resolver: Resolver | None) -> list[str]:
    """Look up players typed by name and add those boards (finalized) to rg.games."""
    from .resolve import match_players

    if rg.unresolved and resolver is None:
        raise Problem("names_need_confirmation", f"round_{round_no}.ods has players given by name; they must be "
                      f"confirmed", {"rows": [u.line for u in rg.unresolved]})
    used = {pid for g in rg.games for pid in g.players()}
    done = []

    def choose(text: str, where: str) -> int:
        candidates = [p for p in match_players(text, list(t.players.values())) if p.id not in used]
        if not candidates:
            raise Problem("name_not_found", f"{where}: no player matches {text!r}. Enter the player's ID or "
                          f"more of the name.", {"where": where, "text": text})
        candidates = [p for p in candidates if p.plays(round_no)] or candidates
        chosen = resolver(where, text, candidates, round_no)
        if chosen is None:
            raise Problem("name_cancelled", f"{where}: cancelled. Enter the player's ID or more of the name in "
                          f"the round file.", {"where": where, "text": text})
        return chosen.id

    for u in rg.unresolved:
        if u.white is None:
            u.white = choose(u.white_text, f"row {u.line}, White")
        used.add(u.white)
        if u.black is None:
            u.black = choose(u.black_text, f"row {u.line}, Black")
        used.add(u.black)
        if u.white == u.black:
            raise Problem("same_player", f"row {u.line}: White and Black are the same player", {"row": u.line})
        idx = len(rg.games)
        if u.handicap is None:
            rg.missing_handicap.add(idx)
        if u.komi is None:
            rg.missing_komi.add(idx)
        rg.missing_board.add(idx)
        rg.games.append(Game(board=0, white=u.white, black=u.black, handicap=u.handicap or 0,
                             komi=u.komi if u.komi is not None else t.cfg.handicap.komi_even, finalized=True))
        done.append(f"row {u.line}: {t.players[u.white].name} - {t.players[u.black].name}")
    rg.unresolved = []
    return done


def pair(directory: Path, round_no: int, *, force: bool = False,
         resolver: Resolver | None = None) -> PairOutcome:
    """Pair a round: finalized boards stay unchanged, everybody else registered for the round is paired.
    Writes round_<r>.ods and the pairing PDFs."""
    from .pairing import PairingError, pair_round

    t = load(directory, names_allowed_in_round=round_no)
    path = round_file(directory, round_no)
    check_writable(path)
    _check_can_pair(t, round_no, force)
    try:
        ratings = t.rating_before(round_no)
    except TournamentError as e:
        raise Problem("load", str(e)) from None
    existing = t.rounds.get(round_no)
    warnings: list[str] = [w for w in t.warnings if not w.startswith(f"round {round_no}:")]
    resolved: list[str] = []
    kept: list[Game] = []
    started_before = bool(existing and existing.games and all(g.finalized for g in existing.games))
    if existing:
        resolved = resolve_names(t, existing, round_no, resolver)
        kept = finalized_boards(t, existing, round_no, ratings, warnings)
    try:
        result = pair_round(t, round_no, kept)
    except PairingError as e:
        raise Problem("pairing", str(e)) from None
    labels = {pid: player_label(p) for pid, p in t.players.items()}
    save_round(path, result.games, labels, ratings,
               not_playing=[(pid, labels[pid], reason) for pid, reason in result.sitting_out])
    outcome = PairOutcome(
        t, round_no, result.games, result.sitting_out, result.rule_hits, ratings, kept=len(kept),
        repaired=(len(existing.games) - len(kept)) if existing else 0,
        new_boards=[g.board for g in result.games if not g.finalized],
        started_before=started_before, warnings=warnings, resolved=resolved)
    outcome.pdfs, outcome.pdf_error, pdf_warnings = pairing_pdfs(directory, round_no)
    outcome.warnings += pdf_warnings
    return outcome


def pairing_pdfs(directory: Path, round_no: int) -> tuple[list[Path], str, list[str]]:
    """Write round_<r>.pdf and round_<r>_alphabetical.pdf. Returns (paths, error, warnings)."""
    from .printing import PrintError, alphabetical_pdf, alphabetical_pdf_path, pairing_pdf, pdf_path

    t = load(directory)
    rg = t.rounds.get(round_no)
    if rg is None:
        raise Problem("no_round", f"{round_file(directory, round_no).name} not found", {"round": round_no})
    tr, warnings = translator(t)
    try:
        paths = [pairing_pdf(t, rg, pdf_path(directory, round_no), tr),
                 alphabetical_pdf(t, rg, alphabetical_pdf_path(directory, round_no), tr)]
    except (PrintError, OSError) as e:
        return [], str(e), warnings
    return paths, "", warnings


def template(directory: Path, round_no: int, *, force: bool = False) -> Path:
    """An empty round file for boards the director pairs by hand (with a 'Participants' sheet)."""
    t = load(directory, names_allowed_in_round=round_no)
    path = round_file(directory, round_no)
    check_writable(path)
    _check_can_pair(t, round_no, force)
    if path.exists() and not force:
        raise Problem("exists", f"{path.name} already exists. Use force to replace it with an empty template.",
                      {"path": path})
    ratings = t.rating_before(round_no)
    labels = {pid: player_label(p) for pid, p in t.players.items()}
    parts = [(pid, labels[pid], ratings[pid], p.club)
             for pid, p in sorted(t.players.items(), key=lambda x: -ratings[x[0]]) if p.plays(round_no)]
    save_round(path, [], labels, ratings, participants=parts)
    return path


@dataclass
class StartOutcome:
    round: int
    boards: int
    newly: int


def start(directory: Path, round_no: int) -> StartOutcome:
    """Mark all boards of a round as finalized."""
    from .pairing import number_boards

    t = load(directory)
    rg = t.rounds.get(round_no)
    path = round_file(directory, round_no)
    if rg is None or not rg.games:
        raise Problem("not_paired", f"{path.name} {'has no boards' if rg else 'not found'}. Pair the round first.",
                      {"round": round_no})
    check_writable(path)
    ratings = t.rating_before(round_no)
    newly = sum(1 for g in rg.games if not g.finalized)
    for g in rg.games:
        g.finalized = True
    finalized_boards(t, rg, round_no, ratings)          # fills an empty handicap / board number
    number_boards(rg.games, ratings)
    labels = {pid: player_label(p) for pid, p in t.players.items()}
    save_round(path, rg.games, labels, ratings, not_playing=read_not_playing(path))
    return StartOutcome(round_no, len(rg.games), newly)


# ---------------------------------------------------------------- results

@dataclass
class ResultsCheck:
    round: int
    boards: int
    missing: list[tuple[int, str, str]]          # (board, white name, black name)
    rematches: list[tuple[int, str, str]]
    unpaired: list[tuple[int, str]]              # registered but not on a board (id, name)
    warnings: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing


def check_results(t: Tournament, round_no: int) -> ResultsCheck:
    rg = t.rounds.get(round_no)
    if rg is None:
        raise Problem("no_round", f"{round_file(t.directory, round_no).name} not found", {"round": round_no})
    name = lambda pid: t.players[pid].name
    missing = [(g.board, name(g.white), name(g.black)) for g in rg.games if g.result is None]
    earlier = t.played_pairs(before_round=round_no)
    rematches = [(g.board, name(g.white), name(g.black)) for g in rg.games if frozenset(g.players()) in earlier]
    on_board = {pid for g in rg.games for pid in g.players()}
    unpaired = [(pid, p.name) for pid, p in sorted(t.players.items())
                if p.plays(round_no) and pid not in on_board and not p.joker]
    warnings = [w for w in t.warnings if w.startswith(f"round {round_no}, ")]
    return ResultsCheck(round_no, len(rg.games), missing, rematches, unpaired, warnings)


# ---------------------------------------------------------------- standings, wall list, EGD file, awards

@dataclass
class StandingsOutcome:
    tournament: Tournament
    round: int
    columns: list
    rows: list
    ods: Path
    pdf: Path | None
    pdf_error: str = ""
    warnings: list[str] = field(default_factory=list)


def make_standings(directory: Path, round_no: int | None = None) -> StandingsOutcome:
    """standings.ods and standings.pdf after a round (default: the last round paired)."""
    from .printing import PrintError, standings_pdf
    from .wall import STANDINGS_FILE, standings_rows, write_standings

    t = load(directory)
    r = t.last_round if round_no is None else round_no
    if not 0 <= r <= t.last_round:
        raise Problem("round_range", f"round {r} has not been played (last round: {t.last_round})",
                      {"rounds": t.last_round})
    check_writable(Path(directory) / STANDINGS_FILE)
    cols, rows = standings_rows(t, r)
    ods = write_standings(t, r)
    tr, warnings = translator(t)
    out = StandingsOutcome(t, r, cols, rows, ods, None, warnings=list(t.warnings) + warnings)
    try:
        out.pdf = standings_pdf(t, r, Path(directory) / "standings.pdf", tr)
    except (PrintError, OSError) as e:
        out.pdf_error = str(e)
    return out


def make_wall(directory: Path) -> tuple[Path, Tournament]:
    from .wall import WALL_FILE, WallError, write_wall_list

    t = load(directory)
    check_writable(Path(directory) / WALL_FILE)
    try:
        return write_wall_list(t), t
    except WallError as e:
        raise Problem("wall", str(e)) from None


def make_h9(directory: Path, output: Path | None = None) -> tuple[Path, int, list[str]]:
    """The EGD result file from wall_list.ods. Returns (path, number of players, warnings)."""
    from .config import load_config
    from .wall import WallError, h9_filename, h9_text, read_wall_list

    try:
        cfg = load_config(directory)
        lines, warnings = read_wall_list(directory)
    except (ConfigError, OdsError, WallError) as e:
        raise Problem("h9", str(e)) from None
    for name, value in [("name", cfg.tournament.name), ("place", cfg.tournament.place),
                        ("dates", cfg.tournament.dates)]:
        if not value:
            warnings.append(f"tournament.{name} is empty in tournament.toml")
    path = Path(output) if output else Path(directory) / h9_filename(cfg)
    path.write_text(h9_text(cfg, lines), encoding="utf-8")
    return path, len(lines), warnings


@dataclass
class AwardsOutcome:
    tournament: Tournament
    path: Path
    winners: list
    slides: int
    notes: list[str]
    warnings: list[str]


def make_awards(directory: Path, output: Path | None = None) -> AwardsOutcome:
    from .awards import AWARDS_FILE, AwardError, awards_pdf, compute_awards
    from .printing import PrintError

    t = load(directory)
    warnings = []
    if t.last_round < t.cfg.tournament.rounds:
        warnings.append(f"only {t.last_round} of {t.cfg.tournament.rounds} rounds have been played")
    tr, tw = translator(t)
    try:
        winners, notes = compute_awards(t, tr)
    except AwardError as e:
        raise Problem("awards", str(e)) from None
    path = Path(output) if output else Path(directory) / AWARDS_FILE
    try:
        awards_pdf(t, winners, path, tr)
    except (PrintError, OSError) as e:
        raise Problem("pdf", f"PDF not written: {e}") from None
    slides = len(winners) + (1 if t.cfg.awards.title_slide else 0)
    return AwardsOutcome(t, path, winners, slides, notes, warnings + tw)


# ---------------------------------------------------------------- creating a tournament

def create_tournament(directory: Path, name: str, rounds: int = 5, language: str = "en"):
    """A new tournament folder: tournament.toml, an empty players.ods and translation.toml."""
    from .config import CONFIG_FILE, load_config, write_template
    from .i18n import TRANSLATION_FILE, translation_template
    from .players import PLAYERS_FILE, save_players

    directory = Path(directory)
    existing = [f for f in (CONFIG_FILE, PLAYERS_FILE) if (directory / f).exists()]
    if existing:
        raise Problem("exists", f"{directory} already contains {', '.join(existing)}; not overwriting.",
                      {"path": directory})
    try:
        directory.mkdir(parents=True, exist_ok=True)
        write_template(directory, name or directory.resolve().name, rounds, language)
        cfg = load_config(directory)
        save_players(directory, [], cfg.tournament.rounds, cfg.registration.extra_fields)
    except (ConfigError, OdsError, OSError) as e:
        raise Problem("create", str(e)) from None
    if not (directory / TRANSLATION_FILE).exists():
        (directory / TRANSLATION_FILE).write_text(translation_template("de"), encoding="utf-8")
    return cfg


# ---------------------------------------------------------------- entering a single result

RESULT_VALUES = {
    "white": "WHITE_WINS", "black": "BLACK_WINS", "jigo": "JIGO",
    "white_forfeit": "WHITE_WINS_FORFEIT", "black_forfeit": "BLACK_WINS_FORFEIT",
    "both_forfeit": "BOTH_LOSE_FORFEIT", "": None,
}


def result_value(result) -> str:
    """The short name of a Result for forms ('white', 'jigo', ...; '' = no result)."""
    if result is None:
        return ""
    return next(k for k, v in RESULT_VALUES.items() if v == result.name)


@dataclass
class SetResultOutcome:
    tournament: Tournament
    round: int
    game: Game
    boards: int
    missing: int
    finalized_now: bool          # the board was fixed because a result was entered
    later_rounds: bool           # later rounds exist (they keep their pairing)


def set_result(directory: Path, round_no: int, board: int, value: str) -> SetResultOutcome:
    """Enter (or clear, value '') the result of one board and save the round file.

    A board that gets a result is finalized: a game that is played must never be paired again."""
    from .models import Result

    if value not in RESULT_VALUES:
        raise Problem("bad_result", f"unknown result {value!r}", {"value": value})
    t = load(directory)
    rg = t.rounds.get(round_no)
    path = round_file(directory, round_no)
    if rg is None:
        raise Problem("no_round", f"{path.name} not found", {"round": round_no})
    check_writable(path)
    game = next((g for g in rg.games if g.board == board), None)
    if game is None:
        raise Problem("no_board", f"round {round_no} has no board {board}", {"board": board})
    name = RESULT_VALUES[value]
    game.result = Result[name] if name else None
    finalized_now = game.result is not None and not game.finalized
    if finalized_now:
        game.finalized = True
    labels = {pid: player_label(p) for pid, p in t.players.items()}
    save_round(path, rg.games, labels, t.rating_before(round_no), not_playing=read_not_playing(path))
    return SetResultOutcome(t, round_no, game, len(rg.games), sum(1 for g in rg.games if g.result is None),
                            finalized_now, any(r > round_no for r in t.rounds))


# ---------------------------------------------------------------- registration

@dataclass
class PlayerData:
    """What a registration form sends. ``gor`` and ``rank`` are text as typed."""

    surname: str
    first_name: str = ""
    rank: str = ""
    gor: str = ""
    pin: str = ""
    country: str = ""
    club: str = ""
    joker: bool = False
    rounds: set[int] = field(default_factory=set)
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    egd_gor: float | None = None
    egd_last_tournament: str = ""


def load_registration(directory: Path):
    """(config, player list) of a tournament folder."""
    from .config import load_config
    from .players import load_players

    try:
        cfg = load_config(directory)
        return cfg, load_players(directory, cfg.tournament.rounds, cfg.registration.extra_fields)
    except (ConfigError, OdsError) as e:
        raise Problem("load", str(e)) from None


def save_player(directory: Path, data: PlayerData, player_id: int | None = None):
    """Add a player (player_id None) or change one. Returns (player, issues about this player)."""
    from .players import PLAYERS_FILE, merge_fields, save_players
    from .rank import RankError
    from .registration import RegistrationError, check_players, new_player

    cfg, pl = load_registration(directory)
    check_writable(Path(directory) / PLAYERS_FILE)
    old = None
    if player_id is not None:
        old = next((p for p in pl.players if p.id == player_id), None)
        if old is None:
            raise Problem("no_player", f"there is no player with ID {player_id}", {"id": player_id})
    others = [p for p in pl.players if p.id != player_id]
    gor_text = data.gor.strip().replace(",", ".")
    try:
        gor = float(gor_text) if gor_text else None
    except ValueError:
        raise Problem("invalid", f"GoR {data.gor!r} is not a number", {"field": "gor"}) from None
    extra = {}
    for name, value in data.extra.items():
        value = value.strip()
        allowed = cfg.registration.values_for(name)
        if allowed is not None and value:
            match = next((v for v in allowed if v.casefold() == value.casefold()), None)
            if match is None:
                raise Problem("invalid", f"{name}: {value!r} is not allowed (choose one of: {', '.join(allowed)})",
                              {"field": name})
            value = match
        if value:
            extra[name] = value
    try:
        player = new_player(others, surname=data.surname, first_name=data.first_name,
                            rank=data.rank.strip() or None, gor=gor, pin=data.pin, country=data.country,
                            club=data.club, rounds=set(data.rounds), joker=data.joker, notes=data.notes.strip())
    except (RegistrationError, RankError) as e:
        raise Problem("invalid", str(e)) from None
    if old is not None:
        player.id = old.id
        # keep data of columns the form does not show (e.g. added to players.ods meanwhile)
        player.extra = {**{k: v for k, v in old.extra.items()
                           if k.casefold() not in {n.casefold() for n in data.extra}}, **extra}
    else:
        player.extra = extra
    player.egd_gor = data.egd_gor if data.egd_gor is not None else (old.egd_gor if old else None)
    player.egd_last_tournament = data.egd_last_tournament or (old.egd_last_tournament if old else "")
    players = others + [player]
    save_players(directory, players, cfg.tournament.rounds, merge_fields(pl.extra_fields, extra))
    issues = [i for i in check_players(players, cfg) if f"ID {player.id} (" in i.message]
    return player, issues


def remove_player(directory: Path, player_id: int):
    """Remove a player who does not appear in any round file."""
    from .players import PLAYERS_FILE, save_players
    from .rounds import load_round

    cfg, pl = load_registration(directory)
    check_writable(Path(directory) / PLAYERS_FILE)
    player = next((p for p in pl.players if p.id == player_id), None)
    if player is None:
        raise Problem("no_player", f"there is no player with ID {player_id}", {"id": player_id})
    for r in range(1, cfg.tournament.rounds + 1):
        if not round_file(directory, r).exists():
            continue
        try:
            rg = load_round(directory, r, cfg.handicap.komi_even)
        except OdsError:
            continue
        if any(player_id in g.players() for g in rg.games):
            raise Problem("in_round", f"{player.name} plays in round {r} and cannot be removed. Unregister them "
                          f"from later rounds instead.", {"round": r, "name": player.name})
    save_players(directory, [p for p in pl.players if p.id != player_id], cfg.tournament.rounds, pl.extra_fields)
    return player


# ---------------------------------------------------------------- changing boards by hand

def _load_round_for_change(directory: Path, round_no: int):
    t = load(directory)
    rg = t.rounds.get(round_no)
    path = round_file(directory, round_no)
    if rg is None:
        raise Problem("no_round", f"{path.name} not found", {"round": round_no})
    check_writable(path)
    return t, rg, path


def _save_round(t: Tournament, rg: RoundGames, path: Path, round_no: int) -> None:
    labels = {pid: player_label(p) for pid, p in t.players.items()}
    save_round(path, rg.games, labels, t.rating_before(round_no), not_playing=read_not_playing(path))


def _board(rg: RoundGames, board: int) -> Game:
    game = next((g for g in rg.games if g.board == board), None)
    if game is None:
        raise Problem("no_board", f"round {rg.number} has no board {board}", {"board": board})
    return game


def update_board(directory: Path, round_no: int, board: int, *, finalized: bool | None = None,
                 swap: bool = False, handicap: int | None = None) -> Game:
    """Fix or release a board, swap its colours or set its handicap (and the matching komi)."""
    t, rg, path = _load_round_for_change(directory, round_no)
    g = _board(rg, board)
    if (swap or handicap is not None) and g.result is not None:
        raise Problem("has_result", f"board {board} already has a result; clear it first to change the board",
                      {"board": board})
    if swap:
        g.white, g.black = g.black, g.white
    if handicap is not None:
        if not 0 <= handicap <= 9:
            raise Problem("invalid", "the handicap must be between 0 and 9", {"board": board})
        g.handicap = handicap
        g.komi = t.cfg.handicap.komi_handicap if handicap > 0 else t.cfg.handicap.komi_even
        ratings = t.rating_before(round_no)
        if handicap > 0 and ratings[g.white] < ratings[g.black]:
            g.white, g.black = g.black, g.white          # the weaker player takes black and the stones
    if finalized is not None:
        if not finalized and g.result is not None:
            raise Problem("has_result", f"board {board} has a result and stays fixed", {"board": board})
        g.finalized = finalized
    _save_round(t, rg, path, round_no)
    return g


def dissolve_board(directory: Path, round_no: int, board: int) -> Game:
    """Remove a board without result; both players are paired again by the next pairing."""
    t, rg, path = _load_round_for_change(directory, round_no)
    g = _board(rg, board)
    if g.result is not None:
        raise Problem("has_result", f"board {board} already has a result", {"board": board})
    rg.games.remove(g)
    _save_round(t, rg, path, round_no)
    return g


def pair_by_hand(directory: Path, round_no: int, white: int, black: int, handicap: int | None = None) -> PairOutcome:
    """Put two players on a fixed board (removing the boards they were on) and pair the rest again."""
    from .pairing import number_boards, setup_game, rng_for

    t, rg, path = _load_round_for_change(directory, round_no)
    for pid in (white, black):
        if pid not in t.players:
            raise Problem("no_player", f"there is no player with ID {pid}", {"id": pid})
    if white == black:
        raise Problem("same_player", "White and Black are the same player", {})
    ratings = t.rating_before(round_no)
    for g in list(rg.games):
        if white in g.players() or black in g.players():
            if g.finalized or g.result is not None:
                other = t.players[white if white in g.players() else black].name
                raise Problem("on_fixed_board", f"{other} is on board {g.board}, which is fixed. Release that board "
                              f"first.", {"board": g.board, "name": other})
            rg.games.remove(g)
    if handicap is None:
        game = setup_game(t, round_no, white, black, ratings, rng_for(t.cfg, round_no, "manual"), finalized=True)
    else:
        game = Game(0, white, black, handicap,
                    t.cfg.handicap.komi_handicap if handicap > 0 else t.cfg.handicap.komi_even, finalized=True)
    rg.games.append(game)
    number_boards(rg.games, ratings)
    _save_round(t, rg, path, round_no)
    return pair(directory, round_no)


def name_candidates(directory: Path, round_no: int) -> list[dict]:
    """For boards given by name: each typed name with its candidates (best first)."""
    from .resolve import match_players

    t = load(directory, names_allowed_in_round=round_no)
    rg = t.rounds.get(round_no)
    if rg is None:
        return []
    out = []
    for u in rg.unresolved:
        for side, pid, text in (("White", u.white, u.white_text), ("Black", u.black, u.black_text)):
            if pid is not None:
                continue
            cands = match_players(text, list(t.players.values()))
            cands = [p for p in cands if p.plays(round_no)] + [p for p in cands if not p.plays(round_no)]
            out.append({"where": f"row {u.line}, {side}", "text": text,
                        "candidates": [(p.id, describe_candidate(p, round_no)) for p in cands[:12]]})
    return out

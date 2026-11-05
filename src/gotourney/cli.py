"""Command line entry point: ``gotourney``."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__, egd
from .config import CONFIG_FILE, Config, ConfigError, load_config, write_template
from .ods import OdsError
from .players import PLAYERS_FILE, PlayerList, load_players, save_players, starting_rating
from .rank import RankError
from .registration import RegistrationError, check_players, new_player, parse_rounds, sync_player
from .rounds import player_label, round_file, save_round
from .tournament import Tournament, TournamentError

app = typer.Typer(
    help="Tools for organising a Go tournament with tournament ratings (TGoR).",
    no_args_is_help=True,
    add_completion=False,
)
players_app = typer.Typer(help="Player registration (players.ods).", no_args_is_help=True)
app.add_typer(players_app, name="players")
egd_app = typer.Typer(help="European Go Database: player list and lookups.", no_args_is_help=True)
app.add_typer(egd_app, name="egd")
results_app = typer.Typer(help="Results of a round.", no_args_is_help=True)
app.add_typer(results_app, name="results")

DIR_HELP = "Tournament directory."


def fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def warn(message: str) -> None:
    typer.secho(f"Warning: {message}", fg=typer.colors.YELLOW, err=True)


def ensure_not_open(path: Path) -> None:
    """Refuse to overwrite a file that is open in LibreOffice (its changes would be lost)."""
    lock = path.with_name(f".~lock.{path.name}#")
    if lock.exists():
        fail(f"{path} is open in LibreOffice. Save and close it first, then run the command again.")


def load_tournament(directory: Path) -> Tournament:
    try:
        t = Tournament.load(directory)
    except (ConfigError, OdsError, TournamentError) as e:
        fail(str(e))
    return t


def show_warnings(t: Tournament, skip: tuple[str, ...] = ()) -> None:
    for w in t.warnings:
        if not any(s in w for s in skip):
            warn(w)


def load(directory: Path) -> tuple[Config, PlayerList]:
    try:
        cfg = load_config(directory)
        players = load_players(directory, cfg.tournament.rounds)
    except (ConfigError, OdsError) as e:
        fail(str(e))
    for w in players.warnings:
        warn(w)
    return cfg, players


def lookup_pin(pin: str) -> "egd.EGDPlayer | None":
    """Latest data for a PIN: live from the EGD, else from the cached player list."""
    try:
        return egd.fetch_by_pin(pin)
    except egd.EGDError as e:
        warn(f"{e}; trying the cached EGD player list")
    try:
        return egd.PlayerIndex.load(refresh=False).by_pin.get(pin)
    except egd.EGDError as e:
        warn(str(e))
        return None


@app.callback()
def main() -> None:
    pass


@app.command()
def version() -> None:
    """Show the version."""
    typer.echo(__version__)


@app.command()
def init(
    directory: Path = typer.Argument(..., help="Directory for the new tournament (created if needed)."),
    name: str = typer.Option("", "--name", "-n", help="Tournament name."),
    rounds: int = typer.Option(5, "--rounds", "-r", min=1, help="Number of rounds."),
) -> None:
    """Create a new tournament: tournament.toml and an empty players.ods."""
    directory.mkdir(parents=True, exist_ok=True)
    existing = [f for f in (CONFIG_FILE, PLAYERS_FILE) if (directory / f).exists()]
    if existing:
        fail(f"{directory} already contains {', '.join(existing)}; not overwriting.")
    write_template(directory, name or directory.resolve().name, rounds)
    try:
        cfg = load_config(directory)
        save_players(directory, [], cfg.tournament.rounds)
    except (ConfigError, OdsError) as e:
        fail(str(e))
    typer.echo(f"Created {directory / CONFIG_FILE} and {directory / PLAYERS_FILE} "
               f"({cfg.tournament.rounds} rounds).")
    typer.echo(f"Edit {CONFIG_FILE} (name, place, dates, rounds, k_factor, ...) before registering players.")


# ---------------------------------------------------------------- players

@players_app.command("add")
def players_add(
    surname: str = typer.Argument("", help="Surname (family name). Optional with --pin."),
    first_name: str = typer.Argument("", help="First name."),
    rank: str = typer.Option(None, "--rank", "-r", help="Declared rank, e.g. 5k or 1d."),
    gor: float = typer.Option(None, "--gor", "-g", help="Starting GoR. Default: value of the rank."),
    pin: str = typer.Option("", "--pin", "-p", help="EGD PIN (8 digits)."),
    country: str = typer.Option("", "--country", "-c", help="Country code, e.g. DE."),
    club: str = typer.Option("", "--club", help="EGD club code, e.g. HH."),
    rounds: str = typer.Option("all", "--rounds", help="Rounds to play: all, none, 1,2,4 or 1-3."),
    joker: bool = typer.Option(False, "--joker", help="Player may sit out odd rounds."),
    notes: str = typer.Option("", "--notes", help="Free text."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Register a player in players.ods.

    With --pin, missing data (name, rank, GoR, country, club) is taken from the EGD.
    """
    cfg, pl = load(directory)
    path = directory / PLAYERS_FILE
    ensure_not_open(path)
    egd_player = None
    if pin:
        egd_player = lookup_pin(pin.strip())
        if egd_player is None:
            warn(f"PIN {pin} not found in the EGD")
        else:
            surname = surname or egd_player.surname
            first_name = first_name or egd_player.first_name
            rank = rank or egd_player.grade
            gor = egd_player.gor if gor is None else gor
            country = country or egd_player.country
            club = club or egd_player.club
    if not surname:
        fail("Give the player's surname, or an EGD PIN.")
    try:
        player = new_player(
            pl.players, surname=surname, first_name=first_name, rank=rank, gor=gor, pin=pin,
            country=country, club=club, rounds=parse_rounds(rounds, cfg.tournament.rounds),
            joker=joker, notes=notes,
        )
    except (RegistrationError, RankError) as e:
        fail(str(e))
    if egd_player is not None:
        player.egd_gor = float(egd_player.gor)
        player.egd_last_tournament = egd_player.last_appearance
    save_players(directory, pl.players + [player], cfg.tournament.rounds)
    rounds_text = ",".join(map(str, sorted(player.rounds))) or "none"
    typer.echo(f"Added ID {player.id}: {player.name}, {player.rank}, GoR {player.gor:.0f}, "
               f"rounds {rounds_text}{', joker' if player.joker else ''}.")


@players_app.command("list")
def players_list(directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP)) -> None:
    """Show the registered players."""
    cfg, pl = load(directory)
    n = cfg.tournament.rounds
    typer.echo(f"{'ID':>3}  {'Name':<28} {'Rank':>4} {'GoR':>5}  {'Club':<6} {'Rounds':<{max(n, 6)}}  Joker")
    for p in sorted(pl.players, key=lambda p: p.id):
        try:
            gor = f"{starting_rating(p):5.0f}"
        except ValueError:
            gor = "    ?"
        marks = "".join(str(r % 10) if p.plays(r) else "." for r in range(1, n + 1))
        typer.echo(f"{p.id:>3}  {p.name[:28]:<28} {str(p.rank or ''):>4} {gor}  {p.club[:6]:<6} "
                   f"{marks:<{max(n, 6)}}  {'x' if p.joker else ''}")
    typer.echo(f"{len(pl.players)} players.")


@players_app.command("check")
def players_check(directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP)) -> None:
    """Check players.ods for problems (duplicates, missing ratings, odd rounds without joker, ...)."""
    cfg, pl = load(directory)
    issues = check_players(pl.players, cfg)
    colours = {"error": typer.colors.RED, "warning": typer.colors.YELLOW, "info": None}
    for i in issues:
        typer.secho(f"{i.level.capitalize()}: {i.message}", fg=colours[i.level])
    errors = sum(i.level == "error" for i in issues)
    warnings = sum(i.level == "warning" for i in issues)
    typer.echo(f"{len(pl.players)} players, {errors} error(s), {warnings} warning(s).")
    if errors:
        raise typer.Exit(1)


@app.command()
def gui(
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
    update_list: bool = typer.Option(False, "--update-list", help="Download a fresh EGD player list first."),
) -> None:
    """Open the registration window (search the EGD with autocomplete)."""
    cfg, _ = load(directory)
    from . import gui as gui_module  # Tkinter is only needed here
    gui_module.run(directory, cfg, refresh_list=True if update_list else None)


# ---------------------------------------------------------------- egd

@egd_app.command("update")
def egd_update() -> None:
    """Download the current EGD player list (used for search and offline lookups)."""
    try:
        path = egd.download_player_list()
    except egd.EGDError as e:
        fail(str(e))
    index = egd.PlayerIndex.load(refresh=False)
    typer.echo(f"Saved {len(index.players)} players to {path}.")


@egd_app.command("search")
def egd_search(
    query: str = typer.Argument(..., help="Name (parts, e.g. 'luethke h') or PIN."),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Search the EGD player list."""
    try:
        index = egd.PlayerIndex.load()
    except egd.EGDError as e:
        fail(str(e))
    hits = index.search(query, limit=limit)
    for p in hits:
        typer.echo(f"{p.pin}  {p.name[:30]:<30} {p.country:<3} {p.club or '-':<6} {p.grade:>4} "
                   f"{p.gor:>5}  {p.last_appearance}")
    if not hits:
        typer.echo("No players found.")


@players_app.command("sync")
def players_sync(
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
    offline: bool = typer.Option(False, "--offline", help="Use only the cached EGD player list."),
) -> None:
    """Refresh EGD data (name, country, club, EGD GoR, last tournament) of all players with a PIN.

    The GoR column is only filled where it is empty, and only before round 1 is paired.
    The declared rank is never changed.
    """
    cfg, pl = load(directory)
    ensure_not_open(directory / PLAYERS_FILE)
    frozen = round_file(directory, 1).exists()
    index = None
    try:
        index = egd.PlayerIndex.load(refresh=False if offline else None)
    except egd.EGDError as e:
        if offline:
            fail(str(e))
        warn(str(e))
    changed = 0
    for p in pl.players:
        if not p.pin:
            continue
        data = None
        if not offline:
            try:
                data = egd.fetch_by_pin(p.pin)
            except egd.EGDError:
                pass
        if data is None and index is not None:
            data = index.by_pin.get(p.pin)
        if data is None:
            warn(f"ID {p.id} {p.name}: PIN {p.pin} not found in the EGD")
            continue
        changes = sync_player(p, data, fill_gor=not frozen)
        if changes:
            changed += 1
            typer.echo(f"ID {p.id} {p.name}: " + "; ".join(changes))
    if changed:
        save_players(directory, pl.players, cfg.tournament.rounds)
    typer.echo(f"{changed} player(s) updated.")
    if frozen:
        typer.echo("Round 1 is already paired: starting GoRs were not changed.")
    issues = [i for i in check_players(pl.players, cfg) if i.level == "warning"]
    for i in issues:
        warn(i.message)


# ---------------------------------------------------------------- pairing

def _print_round(t: Tournament, games, ratings, sitting_out) -> None:
    from .rounds import BLACK_STONE, WHITE_STONE
    for g in games:
        hk = f"H{g.handicap} komi {g.komi:g}"
        w, b = player_label(t.players[g.white]), player_label(t.players[g.black])
        typer.echo(f"{g.board:>3}  {WHITE_STONE} {w[:28]:<28} {ratings[g.white]:5.0f}  -  "
                   f"{BLACK_STONE} {b[:28]:<28} {ratings[g.black]:5.0f}   {hk:<14}"
                   f"{'manual' if g.manual else ''}")
    for pid, reason in sitting_out:
        if "joker" in reason:
            typer.echo(f"     Not playing: {t.players[pid].name} ({reason})")


@app.command()
def pair(
    round_no: int = typer.Argument(..., metavar="ROUND", help="Round number."),
    template: bool = typer.Option(False, "--template", help="Only write an empty round file for manual pairings."),
    force: bool = typer.Option(False, "--force", help="Overwrite a round file that already has results."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Pair a round. Boards marked 'x' in the Manual column of an existing round file are kept."""
    from .pairing import PairingError, pair_round, rng_for, setup_game

    t = load_tournament(directory)
    show_warnings(t, skip=(f"round {round_no}:",))
    path = round_file(directory, round_no)
    ensure_not_open(path)
    if not 1 <= round_no <= t.cfg.tournament.rounds:
        fail(f"the tournament has rounds 1 to {t.cfg.tournament.rounds}")
    if round_no > t.last_round + 1:
        fail(f"round {t.last_round + 1} has to be paired first")
    later = [r for r in t.rounds if r > round_no]
    if later:
        fail(f"round {later[0]} already exists; re-pairing round {round_no} is not possible")
    existing = t.rounds.get(round_no)
    if existing and existing.has_results and not force:
        fail(f"{path.name} already contains results. Use --force to pair the round again.")
    try:
        ratings = t.rating_before(round_no)
    except TournamentError as e:
        fail(str(e))
    names = {pid: p.name for pid, p in t.players.items()}
    labels = {pid: player_label(p) for pid, p in t.players.items()}

    if template:
        if path.exists() and not force:
            fail(f"{path.name} already exists. Use --force to replace it with an empty template.")
        parts = [(pid, labels[pid], ratings[pid], p.club) for pid, p in sorted(t.players.items(), key=lambda x: -ratings[x[0]])
                 if p.plays(round_no)]
        save_round(path, [], labels, ratings, participants=parts)
        typer.echo(f"Wrote {path}. Enter manual boards (White ID, Black ID, 'x' in Manual), save, close, "
                   f"then run 'gotourney pair {round_no}'. Players of the round are listed on the "
                   f"'Participants' sheet.")
        return

    manual = []
    if existing:
        rng = rng_for(t.cfg, round_no, "manual")
        for i, g in enumerate(existing.games):
            if not g.manual:
                continue
            if i in existing.missing_handicap:
                d = setup_game(t, round_no, g.white, g.black, ratings, rng, manual=True)
                g.white, g.black, g.handicap, g.komi = d.white, d.black, d.handicap, d.komi
            elif i in existing.missing_komi:
                g.komi = t.cfg.handicap.komi_handicap if g.handicap > 0 else t.cfg.handicap.komi_even
            g.result = None if force else g.result
            manual.append(g)
            if frozenset(g.players()) in t.played_pairs(before_round=round_no):
                warn(f"manual board: {names[g.white]} and {names[g.black]} already played each other")
        dropped = len(existing.games) - len(manual)
        if dropped:
            typer.echo(f"{dropped} board(s) without 'x' in the Manual column are paired again.")
    try:
        result = pair_round(t, round_no, manual)
    except PairingError as e:
        fail(str(e))
    save_round(path, result.games, labels, ratings, not_playing=[
        (pid, labels[pid], reason) for pid, reason in result.sitting_out])
    _print_round(t, result.games, ratings, result.sitting_out)
    typer.echo(f"Wrote {path} ({len(result.games)} boards).")
    _write_pairing_pdf(directory, round_no)


def _write_pairing_pdf(directory: Path, round_no: int) -> None:
    from .printing import PrintError, pairing_pdf, pdf_path

    t = load_tournament(directory)
    rg = t.rounds.get(round_no)
    if rg is None:
        fail(f"{round_file(directory, round_no).name} not found")
    try:
        path = pairing_pdf(t, rg, pdf_path(directory, round_no))
    except (PrintError, OSError) as e:
        warn(f"PDF not written: {e}")
        return
    typer.echo(f"Wrote {path} (printable pairing).")


@app.command("pairing-pdf")
def pairing_pdf_command(
    round_no: int = typer.Argument(..., metavar="ROUND"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write a printable PDF of a round's pairing (round_<r>.pdf), e.g. after editing round_<r>.ods."""
    _write_pairing_pdf(directory, round_no)


# ---------------------------------------------------------------- results and standings

@results_app.command("check")
def results_check(
    round_no: int = typer.Argument(..., metavar="ROUND"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Check the results of a round (missing or invalid results, rematches, players)."""
    t = load_tournament(directory)
    rg = t.rounds.get(round_no)
    if rg is None:
        fail(f"{round_file(directory, round_no).name} not found")
    problems = 0
    for g in rg.games:
        if g.result is None:
            problems += 1
            typer.secho(f"Board {g.board}: result missing ({t.players[g.white].name} - "
                        f"{t.players[g.black].name})", fg=typer.colors.RED)
    earlier = t.played_pairs(before_round=round_no)
    for g in rg.games:
        if frozenset(g.players()) in earlier:
            warn(f"board {g.board}: rematch of {t.players[g.white].name} and {t.players[g.black].name}")
    on_board = {pid for g in rg.games for pid in g.players()}
    for pid, p in sorted(t.players.items()):
        if p.plays(round_no) and pid not in on_board and not p.joker:
            warn(f"{p.name} (ID {pid}) is registered for round {round_no} but not paired")
    for w in t.warnings:
        if w.startswith(f"round {round_no}, ") :
            warn(w)
    done = len(rg.games) - problems
    typer.echo(f"Round {round_no}: {done} of {len(rg.games)} results entered.")
    if problems:
        raise typer.Exit(1)


@app.command()
def standings(
    round_no: int = typer.Option(None, "--round", "-r", help="Standings after this round (default: last)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Show the TGoR standings and write standings.ods."""
    from .wall import STANDINGS_FILE, standings_rows, write_standings

    t = load_tournament(directory)
    show_warnings(t)
    r = t.last_round if round_no is None else round_no
    if not 0 <= r <= t.last_round:
        fail(f"round {r} has not been played (last round: {t.last_round})")
    ensure_not_open(directory / STANDINGS_FILE)
    cols, rows = standings_rows(t, r)
    typer.echo(f"Standings after round {r}:" if r else "Starting ratings:")
    typer.echo(f"{'Pl':>3}  {'Name':<28} {'Rank':>4} {'Start':>5}  {'Games':>5} {'Wins':>4}  {'TGoR':>5}")
    for row in rows:
        place, pid, name, rank, club, start = row[:6]
        games, wins, tgor = row[-3:]
        typer.echo(f"{place:>3}  {name[:28]:<28} {rank:>4} {start:>5}  {games:>5} {wins:>4g}  {tgor:>5}")
    path = write_standings(t, r)
    typer.echo(f"Wrote {path}.")


@app.command()
def wall(directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP)) -> None:
    """Compute the final places and write wall_list.ods (editable; used by 'gotourney h9')."""
    from .wall import WALL_FILE, WallError, write_wall_list

    t = load_tournament(directory)
    ensure_not_open(directory / WALL_FILE)
    try:
        path = write_wall_list(t)
    except WallError as e:
        fail(str(e))
    show_warnings(t)
    typer.echo(f"Wrote {path} ({len(t.players)} players, {t.last_round} rounds).")


@app.command()
def h9(
    output: Path = typer.Option(None, "--output", "-o", help="Output file (default: <code or name>.h9)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write the EGD result file (.h9) from wall_list.ods."""
    from .wall import WallError, h9_filename, h9_text, read_wall_list

    try:
        cfg = load_config(directory)
        lines, warnings = read_wall_list(directory)
    except (ConfigError, OdsError, WallError) as e:
        fail(str(e))
    for w in warnings:
        warn(w)
    for field, value in [("name", cfg.tournament.name), ("place", cfg.tournament.place),
                         ("dates", cfg.tournament.dates)]:
        if not value:
            warn(f"tournament.{field} is empty in {CONFIG_FILE}")
    path = output or directory / h9_filename(cfg)
    path.write_text(h9_text(cfg, lines), encoding="utf-8")
    typer.echo(f"Wrote {path} ({len(lines)} players).")

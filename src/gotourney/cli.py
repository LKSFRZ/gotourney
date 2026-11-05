"""Command line entry point: ``gotourney``."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__
from .config import CONFIG_FILE, Config, ConfigError, load_config, write_template
from .ods import OdsError
from .players import PLAYERS_FILE, PlayerList, load_players, save_players, starting_rating
from .rank import RankError
from .registration import RegistrationError, check_players, new_player, parse_rounds

app = typer.Typer(
    help="Tools for organising a Go tournament with tournament ratings (TGoR).",
    no_args_is_help=True,
    add_completion=False,
)
players_app = typer.Typer(help="Player registration (players.ods).", no_args_is_help=True)
app.add_typer(players_app, name="players")

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


def load(directory: Path) -> tuple[Config, PlayerList]:
    try:
        cfg = load_config(directory)
        players = load_players(directory, cfg.tournament.rounds)
    except (ConfigError, OdsError) as e:
        fail(str(e))
    for w in players.warnings:
        warn(w)
    return cfg, players


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
) -> None:
    """Create a new tournament: tournament.toml and an empty players.ods."""
    directory.mkdir(parents=True, exist_ok=True)
    existing = [f for f in (CONFIG_FILE, PLAYERS_FILE) if (directory / f).exists()]
    if existing:
        fail(f"{directory} already contains {', '.join(existing)}; not overwriting.")
    write_template(directory, name or directory.resolve().name)
    try:
        cfg = load_config(directory)
        save_players(directory, [], cfg.tournament.rounds)
    except (ConfigError, OdsError) as e:
        fail(str(e))
    typer.echo(f"Created {directory / CONFIG_FILE} and {directory / PLAYERS_FILE}.")
    typer.echo(f"Edit {CONFIG_FILE} (name, place, dates, rounds, k_factor, ...) before registering players.")


# ---------------------------------------------------------------- players

@players_app.command("add")
def players_add(
    surname: str = typer.Argument(..., help="Surname (family name)."),
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
    """Register a player in players.ods."""
    cfg, pl = load(directory)
    path = directory / PLAYERS_FILE
    ensure_not_open(path)
    try:
        player = new_player(
            pl.players, surname=surname, first_name=first_name, rank=rank, gor=gor, pin=pin,
            country=country, club=club, rounds=parse_rounds(rounds, cfg.tournament.rounds),
            joker=joker, notes=notes,
        )
    except (RegistrationError, RankError) as e:
        fail(str(e))
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

"""Command line entry point: ``gotourney``."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__, egd, hints
from .hints import cmd
from .config import CONFIG_FILE, Config, ConfigError, load_config
from .ods import OdsError
from .players import PLAYERS_FILE, PlayerList, load_players, save_players, starting_rating
from .rank import RankError
from .registration import RegistrationError, check_players, new_player, parse_rounds, sync_player
from .rounds import player_label, round_file
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


def load_tournament(directory: Path, names_allowed_in_round: int | None = None) -> Tournament:
    try:
        t = Tournament.load(directory, names_allowed_in_round=names_allowed_in_round)
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
        players = load_players(directory, cfg.tournament.rounds, cfg.registration.extra_fields)
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


def parse_extra(items: list[str], fields: list[str], cfg: Config) -> dict[str, str]:
    """'-x Field=value' options -> {field: value}; the field must be a known additional field
    and, for a field with a list of values (dropdown), the value must be one of them."""
    by_key = {f.lower(): f for f in fields}
    data = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep:
            fail(f"--extra {item!r}: use FIELD=VALUE")
        field = by_key.get(name.strip().lower())
        if field is None:
            known = ", ".join(fields) if fields else "none defined"
            fail(f"unknown field {name.strip()!r} (additional fields: {known}). "
                 f"Add it to extra_fields in {CONFIG_FILE}.")
        value = value.strip()
        allowed = cfg.registration.values_for(field)
        if allowed is not None and value:
            match = next((v for v in allowed if v.casefold() == value.casefold()), None)
            if match is None:
                fail(f"{field}: {value!r} is not allowed (choose one of: {', '.join(allowed)})")
            value = match
        data[field] = value
    return data


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
    language: str = typer.Option("en", "--language", "-l",
                                 help="Language of the PDFs: en, de or fr (custom: edit tournament.toml)."),
) -> None:
    """Create a new tournament: tournament.toml, an empty players.ods and translation.toml."""
    from . import workflow
    from .i18n import TRANSLATION_FILE

    try:
        cfg = workflow.create_tournament(directory, name, rounds, language)
    except workflow.Problem as e:
        fail(str(e))
    typer.echo(f"Created {directory / CONFIG_FILE}, {directory / PLAYERS_FILE} and "
               f"{directory / TRANSLATION_FILE} ({cfg.tournament.rounds} rounds, "
               f"language {cfg.output.language}).")
    hints.show([
        f"Open {directory / CONFIG_FILE} in a text editor and fill in the tournament data: place, dates,\n"
        f"time, rating and handicap settings, pairing rules, prizes (see section 4 of the guide).",
        "Download the EGD player list once (needs internet): gotourney egd update",
        f"Register the players in the registration window: {cmd(directory, 'gui')}",
    ])


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
    extra: list[str] = typer.Option(None, "--extra", "-x", metavar="FIELD=VALUE",
                                    help="Additional data, e.g. -x 'Fee paid=yes' (repeatable)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Register a player in players.ods.

    With --pin, missing data (name, rank, GoR, country, club) is taken from the EGD.
    Additional fields are defined in tournament.toml (registration.extra_fields).
    """
    cfg, pl = load(directory)
    path = directory / PLAYERS_FILE
    ensure_not_open(path)
    extra_data = parse_extra(extra or [], pl.extra_fields, cfg)
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
    player.extra = extra_data
    save_players(directory, pl.players + [player], cfg.tournament.rounds, pl.extra_fields)
    rounds_text = ",".join(map(str, sorted(player.rounds))) or "none"
    typer.echo(f"Added ID {player.id}: {player.name}, {player.rank}, GoR {player.gor:.0f}, "
               f"rounds {rounds_text}{', joker' if player.joker else ''}.")
    t = Tournament.load(directory)
    steps = [f"Add more players the same way, or use the registration window: {cmd(directory, 'gui')}"]
    if t.last_round and t.last_round in player.rounds and t.rounds[t.last_round].games:
        steps.append(f"Round {t.last_round} is already paired. To let {player.name} play it as a latecomer:\n"
                     f"{cmd(directory, f'pair {t.last_round}')}")
    hints.show(steps + hints.overall(t, directory))


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
        hints.show([f"Fix the errors listed above in the registration window ({cmd(directory, 'gui')})\n"
                    f"or in players.ods, then check again: {cmd(directory, 'players check')}"])
        raise typer.Exit(1)
    steps = ["Look at the warnings above; they do not stop the tournament."] if warnings else []
    t = Tournament.load(directory)
    if t.last_round == 0:
        steps.append(f"Registration is OK. Pair round 1: {cmd(directory, 'pair 1')}")
        hints.show(steps)
    else:
        hints.show(steps + hints.overall(t, directory))


@app.command()
def web(
    directory: Path = typer.Option(None, "--dir", "-d", help="Tournament folder to open (optional)."),
    port: int = typer.Option(8765, "--port", help="Port of the local web server."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open the browser automatically."),
) -> None:
    """Open the web interface in the browser (runs only on this computer)."""
    from .web import run

    if directory is None and Path(CONFIG_FILE).exists():
        directory = Path(".")
    run(directory, port, open_browser=not no_browser)


@app.command()
def gui(
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
    update_list: bool = typer.Option(False, "--update-list", help="Download a fresh EGD player list first."),
    classic: bool = typer.Option(False, "--classic", help="Use the old registration window instead of the browser."),
    port: int = typer.Option(8765, "--port", help="Port of the local web server."),
) -> None:
    """Register players: opens the players page of the web interface in the browser."""
    cfg, _ = load(directory)
    if not classic:
        from .web import run
        if update_list:
            egd.PlayerIndex.load(refresh=True)
        run(directory, port, open_browser=True, start_path="/players")
        return
    from . import gui as gui_module  # Tkinter is only needed here
    gui_module.run(directory, cfg, refresh_list=True if update_list else None)
    try:
        t = Tournament.load(directory)
    except (ConfigError, OdsError, TournamentError):
        return
    hints.show(hints.overall(t, directory))


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
    hints.show(["The list is now available offline. Register players with the registration window:\n"
                "gotourney gui -d <tournament folder>"])


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
        save_players(directory, pl.players, cfg.tournament.rounds, pl.extra_fields)
    typer.echo(f"{changed} player(s) updated.")
    if frozen:
        typer.echo("Round 1 is already paired: starting GoRs were not changed.")
    t = Tournament.load(directory)
    hints.show(([f"Check the registration: {cmd(directory, 'players check')}"] if t.last_round == 0 else [])
               + hints.overall(t, directory))
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
                   f"{'finalized' if g.finalized else ''}")
    for pid, reason in sitting_out:
        if "joker" in reason:
            typer.echo(f"     Not playing: {t.players[pid].name} ({reason})")


@app.command()
def pair(
    round_no: int = typer.Argument(..., metavar="ROUND", help="Round number."),
    template: bool = typer.Option(False, "--template", help="Only write an empty round file for boards you pair yourself."),
    force: bool = typer.Option(False, "--force", help="Overwrite a round file that already has results."),
    yes: bool = typer.Option(False, "--yes", "-y",
                             help="Accept unambiguous name matches on finalized boards without asking."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Pair a round. Boards marked 'x' in the Finalized column are never changed.

    All other players registered for the round are paired; after 'gotourney start' this pairs only
    latecomers, on new boards. On boards you enter yourself, players can be given by (part of) their
    name instead of the ID; the tool looks them up and asks for confirmation.
    """
    from . import workflow

    if template:
        try:
            path = workflow.template(directory, round_no, force=force)
        except workflow.Problem as e:
            explain(e, directory, round_no)
        typer.echo(f"Wrote {path}.")
        hints.show([
            f"Open {path.name} and enter the boards you want to pair yourself, one per row:\n"
            f"White ID and Black ID (or names in the White / Black columns) and an x in 'Finalized'.\n"
            f"The sheet 'Participants' lists the players of the round.",
            "Save the file in .ods format and close it.",
            f"Then pair all other players: {cmd(directory, f'pair {round_no}')}",
        ])
        return

    try:
        out = workflow.pair(directory, round_no, force=force, resolver=_cli_resolver(yes))
    except workflow.Problem as e:
        explain(e, directory, round_no)
    t = out.tournament
    for w in out.warnings:
        warn(w)
    for line in out.resolved:
        typer.echo(f"Board ({line})")
    if out.repaired:
        typer.echo(f"{out.repaired} board(s) without 'x' in the Finalized column are paired again.")
    if out.kept and not out.new_boards:
        typer.echo(f"All players of round {round_no} are on finalized boards; nothing new to pair.")
    elif out.kept:
        typer.echo(f"Kept {out.kept} finalized board(s). New board(s): {', '.join(map(str, out.new_boards))}.")
    _print_round(t, out.games, out.ratings, out.sitting_out)
    for rule, n in sorted(out.rule_hits.items()):
        typer.echo(f"Rule {rule}: applies to {n} board{'s' if n != 1 else ''}")
    typer.echo(f"Wrote {round_file(directory, round_no)} ({len(out.games)} boards).")
    _report_pdfs(out.pdfs, out.pdf_error)
    r = round_no
    if out.started_before and out.new_boards:          # latecomers were paired in a running round
        steps = [f"Print the updated {hints.fpath(directory, f'round_{r}.pdf')} / round_{r}_alphabetical.pdf and tell the players their\n"
                 f"new board(s): {', '.join(map(str, out.new_boards))}.",
                 f"When these games begin, finalize them too: {cmd(directory, f'start {r}')}"]
    else:
        steps = [f"Print {hints.fpath(directory, f'round_{r}.pdf')} (by board) and round_{r}_alphabetical.pdf "
                 f"(players A-Z)\nand put them up.",
                 f"To change a board: edit {hints.fpath(directory, f'round_{r}.ods')} (an x in 'Finalized' keeps a board as it is),\n"
                 f"save, close and run {cmd(directory, f'pair {r}')} again.",
                 f"When the games begin: {cmd(directory, f'start {r}')}"]
    hints.show(steps + hints.results_steps(t, directory, r))


def explain(e, directory: Path, round_no: int | None = None) -> None:
    """Print a workflow problem with what to do about it, then stop."""
    typer.secho(str(e), fg=typer.colors.RED, err=True)
    d = e.data
    if e.code == "not_next":
        nxt = d["next"]
        hints.show([f"Pair round {nxt} first: {cmd(directory, f'pair {nxt}')}"])
    elif e.code == "previous_incomplete":
        r = d["round"]
        for board, white, black in d["boards"]:
            typer.echo(f"  board {board}: {white} - {black}", err=True)
        hints.show([
            f"Enter the missing results in {hints.fpath(directory, f'round_{r}.ods')} (an x under "
            f"'White win', 'Draw' or 'Black win').",
            "A game that will not be played (e.g. a player left): enter a forfeit, x! for the winner,\n"
            "or ! under both 'White win' and 'Black win' if both lose. Forfeits are not rated.",
            f"Save and close the file, check with {cmd(directory, f'results check {r}')},\n"
            f"then run {cmd(directory, f'pair {round_no}')} again.",
        ])
    elif e.code == "open_results":
        hints.show([f"Keep the boards with results: {cmd(directory, f'start {round_no}')}",
                    f"Or pair them again, losing their results: {cmd(directory, f'pair {round_no} --force')}"])
    elif e.code == "not_paired":
        hints.show([f"Pair the round first: {cmd(directory, f'pair {round_no}')}"])
    raise typer.Exit(1)


def _cli_resolver(yes: bool):
    """Ask in the terminal which player is meant by a name typed into a round file."""
    from .workflow import describe_candidate

    def resolve(where, text, candidates, round_no):
        if len(candidates) == 1:
            p = candidates[0]
            if yes or typer.confirm(f"{where}: {text!r} -> {describe_candidate(p, round_no)}?", default=True):
                return p
            return None
        if yes:
            fail(f"{where}: {text!r} matches several players: "
                 + "; ".join(describe_candidate(p, round_no) for p in candidates[:9])
                 + ". Enter more of the name or the ID.")
        shown = candidates[:9]
        typer.echo(f"{where}: {text!r} matches several players:")
        for i, p in enumerate(shown, start=1):
            typer.echo(f"  {i}) {describe_candidate(p, round_no)}")
        if len(candidates) > len(shown):
            typer.echo(f"  ... and {len(candidates) - len(shown)} more (type more of the name to narrow it down)")
        choice = typer.prompt(f"Which player? (1-{len(shown)}, 0 = cancel)", type=int, default=1)
        return shown[choice - 1] if 1 <= choice <= len(shown) else None

    return resolve


def translator(t: Tournament):
    """Texts for the PDFs in the configured output language."""
    from . import workflow
    try:
        tr, warnings = workflow.translator(t)
    except workflow.Problem as e:
        fail(str(e))
    for w in warnings:
        warn(w)
    return tr


def _report_pdfs(paths, error: str) -> None:
    if error:
        warn(f"PDF not written: {error}")
        return
    typer.echo(f"Wrote {paths[0]} (printable pairing, by board).")
    typer.echo(f"Wrote {paths[1]} (printable pairing, players in alphabetical order).")


@app.command("pairing-pdf")
def pairing_pdf_command(
    round_no: int = typer.Argument(..., metavar="ROUND"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write the printable pairing PDFs of a round, e.g. after editing round_<r>.ods.

    round_<r>.pdf: by board, with result columns and handicap.
    round_<r>_alphabetical.pdf: all players by surname, with board, colour, opponent and handicap.
    """
    from . import workflow
    try:
        paths, error, warnings = workflow.pairing_pdfs(directory, round_no)
    except workflow.Problem as e:
        explain(e, directory, round_no)
    for w in warnings:
        warn(w)
    _report_pdfs(paths, error)
    hints.show([f"Print {hints.fpath(directory, f'round_{round_no}.pdf')} and round_{round_no}_alphabetical.pdf "
                f"and put them up."])


# ---------------------------------------------------------------- results and standings

@results_app.command("check")
def results_check(
    round_no: int = typer.Argument(..., metavar="ROUND"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Check the results of a round (missing or invalid results, rematches, players)."""
    from . import workflow

    t = load_tournament(directory)
    try:
        check = workflow.check_results(t, round_no)
    except workflow.Problem as e:
        explain(e, directory, round_no)
    for board, white, black in check.missing:
        typer.secho(f"Board {board}: result missing ({white} - {black})", fg=typer.colors.RED)
    for board, white, black in check.rematches:
        warn(f"board {board}: rematch of {white} and {black}")
    for pid, name in check.unpaired:
        warn(f"{name} (ID {pid}) is registered for round {round_no} but not paired "
             f"(latecomer? 'gotourney pair {round_no}' pairs them on new boards)")
    for w in check.warnings:
        warn(w)
    typer.echo(f"Round {round_no}: {check.boards - len(check.missing)} of {check.boards} results entered.")
    if check.missing:
        hints.show([f"Enter the missing results in {hints.fpath(directory, f'round_{round_no}.ods')} (an x under 'White win', 'Draw' or\n"
                    f"'Black win'), save in .ods format, close the file and check again:\n"
                    f"{cmd(directory, f'results check {round_no}')}"])
        raise typer.Exit(1)
    if round_no == t.last_round:
        hints.show(hints.after_complete_round(t, directory, round_no))
    else:
        hints.show(hints.overall(t, directory))


@app.command()
def standings(
    round_no: int = typer.Option(None, "--round", "-r", help="Standings after this round (default: last)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Show the TGoR standings and write standings.ods and standings.pdf."""
    from . import workflow

    try:
        out = workflow.make_standings(directory, round_no)
    except workflow.Problem as e:
        explain(e, directory)
    t, r = out.tournament, out.round
    for w in out.warnings:
        warn(w)
    typer.echo(f"Standings after round {r}:" if r else "Starting ratings:")
    typer.echo(f"{'Pl':>3}  {'Name':<28} {'Rank':>4} {'Start':>5}  {'Games':>5} {'Wins':>4}  {'TGoR':>5}")
    idx = {c.title: i for i, c in enumerate(out.columns)}
    for row in out.rows:
        place, name, rank, start = (row[idx[k]] for k in ("Place", "Name", "Rank", "Start TGoR"))
        games, wins, tgor = (row[idx[k]] for k in ("Games", "Wins", "TGoR"))
        typer.echo(f"{place:>3}  {name[:28]:<28} {rank:>4} {start:>5}  {games:>5} {wins:>4g}  {tgor:>5}")
    typer.echo(f"Wrote {out.ods}.")
    if out.pdf_error:
        warn(f"PDF not written: {out.pdf_error}")
        return
    typer.echo(f"Wrote {out.pdf} (printable standings).")
    last = t.last_round
    if r == last and last and t.rounds[last].complete:
        if last < t.cfg.tournament.rounds:
            hints.show([f"Print {hints.fpath(directory, 'standings.pdf')} and put it up.",
                        f"Pair the next round: {cmd(directory, f'pair {last + 1}')}"])
        else:
            hints.show([f"Print {hints.fpath(directory, 'standings.pdf')} and put it up."]
                       + hints.after_complete_round(t, directory, last))
    else:
        hints.show(hints.overall(t, directory))


@app.command()
def wall(directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP)) -> None:
    """Compute the final places and write wall_list.ods (editable; used by 'gotourney h9')."""
    from . import workflow

    try:
        path, t = workflow.make_wall(directory)
    except workflow.Problem as e:
        explain(e, directory)
    show_warnings(t)
    typer.echo(f"Wrote {path} ({len(t.players)} players, {t.last_round} rounds).")
    hints.show([
        f"Check {hints.fpath(directory, path.name)} (e.g. the spelling of names) and correct it by hand if needed;\n"
        f"save in .ods format and close it.",
        f"Create the result file for the EGD: {cmd(directory, 'h9')}",
        f"Create the slides for the award ceremony: {cmd(directory, 'awards')}",
    ])


@app.command()
def h9(
    output: Path = typer.Option(None, "--output", "-o", help="Output file (default: <code or name>.h9)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write the EGD result file (.h9) from wall_list.ods."""
    from . import workflow

    try:
        path, count, warnings = workflow.make_h9(directory, output)
    except workflow.Problem as e:
        explain(e, directory)
    for w in warnings:
        warn(w)
    typer.echo(f"Wrote {path} ({count} players).")
    steps = [f"Send {path} to the EGD: usually to your national rating officer, who uploads it\n"
             f"(see europeangodatabase.eu). If you correct wall_list.ods later, run this command again."]
    if not (directory / "awards.pdf").exists():
        steps.append(f"Create the slides for the award ceremony: {cmd(directory, 'awards')}")
    hints.show(steps)


# ---------------------------------------------------------------- award ceremony

@app.command()
def awards(
    output: Path = typer.Option(None, "--output", "-o", help="Output file (default: awards.pdf)."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write the award ceremony presentation (awards.pdf): one slide per prize winner.

    The prizes are configured in the [awards] section of tournament.toml.
    """
    from . import workflow

    try:
        out = workflow.make_awards(directory, output)
    except workflow.Problem as e:
        explain(e, directory)
    for w in out.warnings + out.notes:
        warn(w)
    for a in out.winners:
        typer.echo(f"{a.title:<32} {out.tournament.players[a.player].name:<28} place {a.place}")
    typer.echo(f"Wrote {out.path} ({out.slides} slides).")
    steps = [f"Open {out.path} in a PDF viewer and switch to full-screen / presentation mode for the\n"
             f"ceremony. Prizes are set in the [awards] section of {CONFIG_FILE}; run this command again\n"
             f"after changing them."]
    if not any(directory.glob("*.h9")):
        steps.append(f"Don't forget the EGD result file: {cmd(directory, 'wall')}, then {cmd(directory, 'h9')}")
    hints.show(steps)


@app.command("translation-file")
def translation_file(
    language: str = typer.Option("de", "--language", "-l", help="Texts to start from: de, en or fr."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Write an example translation file for [output] language = "custom" (default: German texts)."""
    from .i18n import TEXTS, normalize_language, translation_template

    lang = normalize_language(language)
    if lang not in TEXTS:
        fail("choose de, en or fr as the starting point")
    name = "translation.toml"
    try:
        name = load_config(directory).output.translation_file
    except ConfigError:
        pass
    path = directory / name
    if path.exists() and not force:
        fail(f"{path} already exists. Use --force to overwrite it.")
    path.write_text(translation_template(lang), encoding="utf-8")
    typer.echo(f"Wrote {path}. Set  language = \"custom\"  in the [output] section of {CONFIG_FILE} to use it.")


@app.command()
def start(
    round_no: int = typer.Argument(..., metavar="ROUND", help="Round number."),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help=DIR_HELP),
) -> None:
    """Start a round: mark all its boards as finalized.

    'gotourney pair' never changes finalized boards; afterwards it only pairs latecomers (players
    registered for the round who are not on a board yet) on new boards.
    """
    from . import workflow

    try:
        out = workflow.start(directory, round_no)
    except workflow.Problem as e:
        explain(e, directory, round_no)
    t = load_tournament(directory)
    typer.echo(f"Round {round_no} started: {out.boards} board(s) finalized ({out.newly} newly).")
    hints.show([
        f"Latecomers: register them for round {round_no} (registration window, or an x in column R{round_no}\n"
        f"of {hints.fpath(directory, 'players.ods')}), then run {cmd(directory, f'pair {round_no}')} - they are paired among each\n"
        f"other on new boards; the running boards stay as they are.",
    ] + hints.results_steps(t, directory, round_no))

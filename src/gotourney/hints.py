"""'Next steps' shown at the end of a command, so that a first-time tournament director always
knows what to do next. Switch off with the environment variable GOTOURNEY_NO_HINTS=1."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from .tournament import Tournament

HINTS_ENV = "GOTOURNEY_NO_HINTS"


def cmd(directory: Path, args: str) -> str:
    """A command line to copy, with -d when the tournament folder is not the current folder."""
    d = Path(directory)
    suffix = "" if d.resolve() == Path.cwd().resolve() else f' -d "{d}"' if " " in str(d) else f" -d {d}"
    return f"gotourney {args}{suffix}"


def fpath(directory: Path, name: str) -> str:
    """A file of the tournament, with its folder when that is not the current folder."""
    d = Path(directory)
    return name if d.resolve() == Path.cwd().resolve() else str(d / name)


def show(steps: list[str]) -> None:
    if not steps or os.environ.get(HINTS_ENV, "").strip() not in ("", "0"):
        return
    typer.echo("")
    typer.secho("Next steps:", fg=typer.colors.CYAN, bold=True)
    for step in steps:
        lines = step.split("\n")
        typer.echo(f"  → {lines[0]}")
        for line in lines[1:]:
            typer.echo(f"    {line}")


# ---------------------------------------------------------------- overall state

def results_steps(t: Tournament, d: Path, r: int) -> list[str]:
    return [f"Enter the results in {fpath(d, f'round_{r}.ods')}: an x under 'White win', 'Draw' or 'Black win'\n"
            f"(save in .ods format and close the file afterwards).",
            f"Check them: {cmd(d, f'results check {r}')}"]


def after_complete_round(t: Tournament, d: Path, r: int) -> list[str]:
    last = t.cfg.tournament.rounds
    if r < last:
        return [f"Round {r} is complete. Show the standings (also written as standings.pdf to put up):\n"
                f"{cmd(d, 'standings')}",
                f"Pair the next round: {cmd(d, f'pair {r + 1}')}"]
    return [f"That was the last round. Make the final wall list: {cmd(d, 'wall')}",
            f"Then create the EGD result file and the award ceremony slides:\n"
            f"{cmd(d, 'h9')}   and   {cmd(d, 'awards')}"]


def overall(t: Tournament, d: Path) -> list[str]:
    """What to do next, judged from the files of the tournament."""
    from .workflow import status

    s = status(t)
    r = s.round
    if s.phase == "no_players":
        return [f"Register the players: {cmd(d, 'gui')}  (or {cmd(d, 'players add')} ...)"]
    if s.phase == "registration":
        return [f"When registration is complete, check it: {cmd(d, 'players check')}",
                f"Then pair round 1: {cmd(d, 'pair 1')}"]
    if s.phase == "names_pending":
        return [f"Round {r} has boards with names instead of IDs. Look them up: {cmd(d, f'pair {r}')}"]
    if s.phase == "paired":
        return [f"Round {r} is paired. Print {fpath(d, f'round_{r}.pdf')} and round_{r}_alphabetical.pdf "
                f"and put them up.",
                f"When the games begin: {cmd(d, f'start {r}')}"] + results_steps(t, d, r)
    if s.phase == "running":
        return [f"Round {r} is running; {s.missing} result(s) still missing."] + results_steps(t, d, r)
    return after_complete_round(t, d, r)

"""Player registration: adding players and checking the registration list."""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass

from .config import Config
from .models import Player
from .rank import Rank


class RegistrationError(ValueError):
    pass


def parse_rounds(text: str, rounds: int) -> set[int]:
    """Parse a round selection like ``all``, ``1,2,4`` or ``1-3,5``."""
    t = text.strip().lower()
    if t in ("", "all"):
        return set(range(1, rounds + 1))
    if t == "none":
        return set()
    result: set[int] = set()
    for part in t.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            raise RegistrationError(f"invalid round selection {text!r} (e.g. all, 1,2,4 or 1-3)")
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        if lo > hi or lo < 1 or hi > rounds:
            raise RegistrationError(f"rounds must be between 1 and {rounds}: {part!r}")
        result.update(range(lo, hi + 1))
    return result


def next_id(players: list[Player]) -> int:
    return max((p.id for p in players), default=0) + 1


def new_player(players: list[Player], *, surname: str, first_name: str, rank: str | None,
               gor: float | None, pin: str = "", country: str = "", club: str = "",
               rounds: set[int], joker: bool = False, notes: str = "") -> Player:
    """Create a player for the list. A missing GoR is filled in from the rank."""
    if not surname.strip():
        raise RegistrationError("surname is required")
    parsed_rank = Rank.parse(rank) if rank else None
    if gor is None:
        if parsed_rank is None:
            raise RegistrationError("give a rank or a GoR")
        gor = parsed_rank.to_gor()
    if parsed_rank is None:
        parsed_rank = Rank.from_gor(gor)
    pin = pin.strip()
    if pin:
        if not (pin.isdigit() and len(pin) == 8):
            raise RegistrationError(f"EGD PIN {pin!r} must have 8 digits")
        for p in players:
            if p.pin == pin:
                raise RegistrationError(f"EGD PIN {pin} is already registered (ID {p.id}, {p.name})")
    return Player(
        id=next_id(players),
        surname=surname.strip(),
        first_name=first_name.strip(),
        rank=parsed_rank,
        gor=gor,
        pin=pin,
        country=country.strip().upper(),
        club=club.strip(),
        joker=joker,
        rounds=rounds,
        notes=notes,
    )


# ---------------------------------------------------------------- checks

@dataclass
class Issue:
    level: str        # "error" = must be fixed before pairing, "warning" = please check, "info"
    message: str


def tournament_date(code: str) -> dt.date | None:
    """Date of an EGD tournament code like ``T261003A`` (YYMMDD)."""
    m = re.fullmatch(r"[A-Z](\d{2})(\d{2})(\d{2})[A-Z]?", code.strip().upper())
    if not m:
        return None
    yy, mm, dd = (int(g) for g in m.groups())
    year = 2000 + yy if yy < 90 else 1900 + yy
    try:
        return dt.date(year, mm, dd)
    except ValueError:
        return None


def check_players(players: list[Player], cfg: Config, today: dt.date | None = None) -> list[Issue]:
    today = today or dt.date.today()
    issues: list[Issue] = []
    reg = cfg.registration

    def err(msg): issues.append(Issue("error", msg))
    def warn(msg): issues.append(Issue("warning", msg))
    def info(msg): issues.append(Issue("info", msg))

    by_pin: dict[str, list[Player]] = defaultdict(list)
    by_name: dict[str, list[Player]] = defaultdict(list)
    for p in players:
        label = f"ID {p.id} ({p.name or 'no name'})"
        if p.pin:
            by_pin[p.pin].append(p)
        by_name[p.name.lower()].append(p)
        if not p.surname:
            err(f"{label}: surname missing")
        if p.gor is None and p.rank is None:
            err(f"{label}: neither GoR nor rank given, no starting rating")
        elif p.gor is None:
            warn(f"{label}: no GoR, starting rating taken from rank {p.rank} ({p.rank.to_gor()})")
        if p.gor is not None and p.rank is not None and p.rank.kind != "p":
            diff = abs(p.gor - p.rank.to_gor())
            if diff > reg.rank_gor_tolerance:
                warn(f"{label}: declared rank {p.rank} and GoR {p.gor:.0f} differ by {diff:.0f} points "
                     f"- check which one is right")
        if p.pin and p.egd_last_tournament:
            last = tournament_date(p.egd_last_tournament)
            if last is not None:
                years = (today - last).days / 365.25
                if years > reg.gor_outdated_years:
                    warn(f"{label}: last EGD tournament {p.egd_last_tournament} is {years:.0f} years ago "
                         f"- GoR may be outdated, overwrite the GoR column if needed")
        if not p.rounds:
            warn(f"{label}: not registered for any round")
    for pin, ps in by_pin.items():
        if len(ps) > 1:
            err(f"EGD PIN {pin} used by IDs {', '.join(str(p.id) for p in ps)}")
    for name, ps in by_name.items():
        if name and len(ps) > 1:
            warn(f"same name for IDs {', '.join(str(p.id) for p in ps)} ({ps[0].name})")

    bar = cfg.rating.top_bar
    if bar is not None:
        above = [p for p in players if p.gor is not None and p.gor > bar]
        if above:
            info(f"top bar {bar:.0f}: {len(above)} player(s) start with TGoR {bar:.0f} "
                 f"({', '.join(p.name for p in above[:6])}{', ...' if len(above) > 6 else ''})")
    for r in range(1, cfg.tournament.rounds + 1):
        playing = [p for p in players if p.plays(r)]
        if len(playing) % 2 == 1:
            jokers = [p for p in playing if p.joker]
            if jokers:
                info(f"round {r}: {len(playing)} players, one of the jokers "
                     f"({', '.join(p.name for p in jokers)}) will sit out")
            else:
                err(f"round {r}: {len(playing)} players (odd) and no joker registered for this round "
                    f"- nominate a joker")
    return issues


# ---------------------------------------------------------------- EGD sync

def sync_player(player: Player, data, fill_gor: bool) -> list[str]:
    """Update a player from EGD data (an egd.EGDPlayer). Returns a description of the changes.

    Name, country, club, EGD GoR and last tournament are refreshed. The GoR column (starting
    TGoR) is only filled when empty and ``fill_gor`` is set; the declared rank is never changed.
    """
    changes = []

    def update(attr, value, label):
        old = getattr(player, attr)
        if value != old and value not in (None, ""):
            changes.append(f"{label}: {old if old not in (None, '') else '-'} -> {value}")
            setattr(player, attr, value)

    update("surname", data.surname, "surname")
    update("first_name", data.first_name, "first name")
    update("country", data.country, "country")
    update("club", data.club, "club")
    update("egd_gor", float(data.gor), "EGD GoR")
    update("egd_last_tournament", data.last_appearance, "last EGD tournament")
    if player.gor is None and fill_gor:
        update("gor", float(data.gor), "GoR")
    return changes

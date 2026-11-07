"""Completing players typed into players.ods by hand (e.g. only a name or only an EGD PIN).

``plan()`` looks at every such row and decides, without changing anything, what will happen:

* EGD PIN given            -> data from the EGD (name in EGD spelling, country, club, rank, GoR, ...)
* name given, one EGD player with exactly this surname and first name -> data from that player
* name given, several possible EGD players -> the director chooses (or "not in the EGD")
* name given, not in the EGD -> registered as a player without EGD data; needs a rank or a GoR

``apply()`` carries out a plan: new IDs, empty cells filled. What the director typed is kept
(only the name is replaced by the EGD spelling when the player was identified).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .egd import EGDPlayer, plain
from .models import Player
from .rank import Rank, RankError
from .registration import next_id, tournament_date

NOT_IN_EGD = "none"          # choice: the player is not in the EGD
MAX_CANDIDATES = 12


@dataclass
class RowPlan:
    line: int                               # row in players.ods
    player: Player                          # as read from the file (id 0)
    action: str                             # "egd" | "choose" | "local" | "missing" | "duplicate"
    egd: EGDPlayer | None = None            # for "egd"
    candidates: list[EGDPlayer] = field(default_factory=list)   # for "choose"
    message: str = ""                       # for "missing" / "duplicate"

    @property
    def typed(self) -> str:
        """What the director typed, to show which row is meant."""
        p = self.player
        parts = [p.name, f"PIN {p.pin}" if p.pin else "", str(p.rank) if p.rank else ""]
        return " · ".join(x for x in parts if x) or f"row {self.line}"


def _matches(candidate: EGDPlayer, surname: str, first_name: str) -> bool:
    return (plain(candidate.surname) == plain(surname)
            and (not first_name or plain(candidate.first_name) == plain(first_name)))


def plan(unfinished: list[tuple[int, Player]], registered: list[Player], index, lookup_pin=None,
         choices: dict[int, str] | None = None) -> list[RowPlan]:
    """What will happen to each row. ``index`` is an egd.PlayerIndex (or None when the EGD list is not
    available); ``lookup_pin(pin)`` may return fresher data than the index; ``choices`` maps a row's
    line to the chosen PIN or NOT_IN_EGD."""
    choices = choices or {}
    by_pin = dict(index.by_pin) if index is not None else {}
    known_pins = {p.pin: p for p in registered if p.pin}
    plans = []
    for line, p in unfinished:
        def egd_data(pin):
            data = lookup_pin(pin) if lookup_pin else None
            return data or by_pin.get(pin)

        if p.pin:
            data = egd_data(p.pin)
            if p.pin in known_pins:
                other = known_pins[p.pin]
                plans.append(RowPlan(line, p, "duplicate", message=f"ID {other.id} {other.name}"))
            elif data is not None:
                plans.append(RowPlan(line, p, "egd", egd=data))
            elif p.surname and (p.rank or p.gor is not None):
                plans.append(RowPlan(line, p, "local"))
            else:
                plans.append(RowPlan(line, p, "missing", message="pin_unknown"))
            continue
        if not p.surname:
            plans.append(RowPlan(line, p, "missing", message="no_name"))
            continue
        choice = choices.get(line)
        if choice == NOT_IN_EGD:
            plans.append(RowPlan(line, p, "local") if (p.rank or p.gor is not None)
                         else RowPlan(line, p, "missing", message="no_rank"))
            continue
        if choice:
            data = egd_data(choice)
            if data is not None:
                if data.pin in known_pins:
                    other = known_pins[data.pin]
                    plans.append(RowPlan(line, p, "duplicate", egd=data, message=f"ID {other.id} {other.name}"))
                else:
                    plans.append(RowPlan(line, p, "egd", egd=data))
                continue
        if index is None:          # EGD list not available: nobody may silently be taken as "not in the EGD"
            plans.append(RowPlan(line, p, "choose", message="egd_unavailable"))
            continue
        candidates = index.search(f"{p.surname} {p.first_name}".strip(), limit=50)
        exact = [c for c in candidates if _matches(c, p.surname, p.first_name)]
        if p.first_name and len(exact) == 1 and exact[0].pin not in known_pins:
            plans.append(RowPlan(line, p, "egd", egd=exact[0]))
        elif candidates:
            # exact name matches first, then the players who played most recently
            def recent(c):
                return tournament_date(c.last_appearance or "") or dt.date.min
            ordered = sorted(exact, key=recent, reverse=True) + sorted(
                (c for c in candidates if c not in exact), key=recent, reverse=True)
            plans.append(RowPlan(line, p, "choose", candidates=ordered[:MAX_CANDIDATES],
                                 message="more" if len(ordered) > MAX_CANDIDATES else ""))
        elif p.rank or p.gor is not None:
            plans.append(RowPlan(line, p, "local"))
        else:
            plans.append(RowPlan(line, p, "missing", message="not_in_egd_no_rank"))
    return plans


def _fill_from_egd(p: Player, data: EGDPlayer, fill_gor: bool) -> list[str]:
    changes = []

    def put(attr, value, label, overwrite=False):
        old = getattr(p, attr)
        if value in (None, "") or value == old:
            return
        if old in (None, "") or overwrite:
            setattr(p, attr, value)
            changes.append(f"{label} {value:g}" if isinstance(value, float) else f"{label} {value}")

    put("pin", data.pin, "PIN")
    if (p.surname, p.first_name) != (data.surname, data.first_name):   # the EGD spelling
        p.surname, p.first_name = data.surname, data.first_name
        changes.append(f"name {data.name}")
    put("country", data.country.upper(), "country")
    put("club", data.club, "club")
    if p.rank is None and data.grade:
        try:
            p.rank = Rank.parse(data.grade)
            changes.append(f"rank {p.rank}")
        except RankError:
            pass
    put("egd_gor", float(data.gor), "EGD GoR")
    put("egd_last_tournament", data.last_appearance, "last EGD tournament")
    if p.gor is None and fill_gor:
        p.gor = float(data.gor)
        changes.append(f"GoR {data.gor}")
    return [c.strip() for c in changes if c.strip()]


@dataclass
class Completed:
    player: Player
    line: int
    changes: list[str]


def apply(plans: list[RowPlan], registered: list[Player], fill_gor: bool) -> tuple[list[Completed], list[RowPlan]]:
    """Complete the rows whose plan is "egd" or "local". Returns (completed, rows left as they are)."""
    done, left = [], []
    taken = list(registered)
    for rp in plans:
        if rp.action not in ("egd", "local"):
            left.append(rp)
            continue
        p = rp.player
        changes = _fill_from_egd(p, rp.egd, fill_gor) if rp.action == "egd" else []
        if p.rank is None and p.gor is not None:
            p.rank = Rank.from_gor(p.gor)
            changes.append(f"rank {p.rank} (from GoR)")
        if p.gor is None and p.rank is not None and p.rank.kind != "p":
            p.gor = float(p.rank.to_gor())
            changes.append(f"GoR {p.gor:.0f} (from rank)")
        p.id = next_id(taken)
        taken.append(p)
        done.append(Completed(p, rp.line, changes))
    return done, left

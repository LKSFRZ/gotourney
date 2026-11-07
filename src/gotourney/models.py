"""Core data model: players, games and results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .rank import Rank


class ResultError(ValueError):
    pass


class Result(Enum):
    WHITE_WINS = "1-0"
    BLACK_WINS = "0-1"
    JIGO = "jigo"
    WHITE_WINS_FORFEIT = "1-0!"
    BLACK_WINS_FORFEIT = "0-1!"
    BOTH_LOSE_FORFEIT = "0-0!"

    @property
    def is_forfeit(self) -> bool:
        return self.value.endswith("!")

    @property
    def white_score(self) -> float | None:
        """Score of White for rating, or None if the game is not rated (forfeit)."""
        return {"1-0": 1.0, "0-1": 0.0, "jigo": 0.5}.get(self.value)

    @classmethod
    def parse(cls, text: str) -> "Result | None":
        """Parse a result cell. Empty cell -> None (result not yet entered)."""
        t = re.sub(r"\s+", "", str(text or "")).lower()
        if not t:
            return None
        t = t.replace(":", "-").replace("½", "0.5")
        aliases = {
            "1-0": cls.WHITE_WINS, "w+": cls.WHITE_WINS,
            "0-1": cls.BLACK_WINS, "b+": cls.BLACK_WINS,
            "jigo": cls.JIGO, "0.5-0.5": cls.JIGO, "=": cls.JIGO,
            "1-0!": cls.WHITE_WINS_FORFEIT, "0-1!": cls.BLACK_WINS_FORFEIT,
            "0-0!": cls.BOTH_LOSE_FORFEIT,
        }
        if t not in aliases:
            raise ResultError(
                f"invalid result {text!r} (use 1-0, 0-1, jigo, or 1-0! / 0-1! / 0-0! for forfeits)"
            )
        return aliases[t]


@dataclass
class Player:
    id: int
    surname: str
    first_name: str
    rank: Rank | None
    gor: float | None              # starting TGoR (editable in players.ods)
    pin: str = ""
    country: str = ""
    club: str = ""
    egd_gor: float | None = None
    egd_last_tournament: str = ""
    joker: bool = False
    rounds: set[int] = field(default_factory=set)
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)   # additional registration data, by field name

    @property
    def name(self) -> str:
        return f"{self.surname} {self.first_name}".strip()

    def plays(self, round_no: int) -> bool:
        return round_no in self.rounds


@dataclass
class Game:
    board: int
    white: int                     # player IDs
    black: int
    handicap: int = 0              # stones received by Black
    komi: float = 6.5
    result: Result | None = None
    finalized: bool = False        # never changed by pair (manual boards, started rounds)

    def players(self) -> tuple[int, int]:
        return self.white, self.black

    def opponent(self, pid: int) -> int:
        if pid == self.white:
            return self.black
        if pid == self.black:
            return self.white
        raise ValueError(f"player {pid} not in game")

"""Go ranks (``5k``, ``1d``, ``2p``) and their conversion to and from GoR.

EGD convention: 1k = 2000, 1d = 2100, 100 GoR points per rank, 30k = -900.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RANK_RE = re.compile(r"^\s*(\d{1,2})\s*([kdp])\s*$", re.IGNORECASE)

MIN_KYU = 30
MAX_DAN = 9
MAX_PRO = 9


class RankError(ValueError):
    pass


@dataclass(frozen=True, order=False)
class Rank:
    number: int
    kind: str  # "k", "d" or "p"

    @classmethod
    def parse(cls, text: str) -> "Rank":
        m = _RANK_RE.match(str(text))
        if not m:
            raise RankError(f"invalid rank {text!r} (expected e.g. 5k, 1d, 2p)")
        number, kind = int(m.group(1)), m.group(2).lower()
        limit = {"k": MIN_KYU, "d": MAX_DAN, "p": MAX_PRO}[kind]
        if not 1 <= number <= limit:
            raise RankError(f"invalid rank {text!r}")
        return cls(number, kind)

    def __str__(self) -> str:
        return f"{self.number}{self.kind}"

    def to_gor(self) -> int:
        """GoR at the middle of this rank (1k = 2000, 1d = 2100)."""
        if self.kind == "k":
            return 2100 - 100 * self.number
        if self.kind == "d":
            return 2000 + 100 * self.number
        raise RankError(f"no automatic GoR for professional rank {self}; enter the GoR by hand")

    @classmethod
    def from_gor(cls, gor: float) -> "Rank":
        """Rank whose band contains ``gor`` (e.g. 2050-2149 = 1d, 1950-2049 = 1k)."""
        center = 100 * int((gor + 50) // 100)
        if center >= 2100:
            return cls(min((center - 2000) // 100, MAX_DAN), "d")
        return cls(min((2100 - center) // 100, MIN_KYU), "k")

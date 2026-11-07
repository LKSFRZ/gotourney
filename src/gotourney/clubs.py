"""Full club names for EGD club codes (e.g. DE/K -> Köln, DE/BGV1 -> Badischer Go-Verein e. V., ...).

The list ships with the tool (data/clubs.csv). A clubs.csv in the tournament folder adds entries or
overrides shipped ones (same columns: country, code, name, city, region; lines starting with # are
comments).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

CLUBS_FILE = "clubs.csv"


class ClubsError(Exception):
    pass


@dataclass(frozen=True)
class Club:
    country: str
    code: str
    name: str
    city: str = ""
    region: str = ""


def _parse(text: str, where: str) -> list[Club]:
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    needed = {"country", "code", "name"}
    if not reader.fieldnames or not needed <= {f.strip().lower() for f in reader.fieldnames}:
        raise ClubsError(f"{where}: needs the columns country, code, name (city, region optional)")
    clubs = []
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if row.get("code") and row.get("name"):
            clubs.append(Club(row.get("country", "").upper(), row["code"], row["name"],
                              row.get("city", ""), row.get("region", "")))
    return clubs


class ClubList:
    def __init__(self, clubs: list[Club]):
        self.exact: dict[tuple[str, str], Club] = {}
        self.folded: dict[tuple[str, str], Club] = {}
        self.by_code: dict[str, list[Club]] = {}
        for c in clubs:                       # later entries override earlier ones
            self.exact[(c.country, c.code)] = c
            self.folded[(c.country, c.code.casefold())] = c
        for c in self.exact.values():
            self.by_code.setdefault(c.code.casefold(), []).append(c)

    @classmethod
    def load(cls, directory: Path | None = None) -> "ClubList":
        text = resources.files("gotourney").joinpath("data", CLUBS_FILE).read_text(encoding="utf-8")
        clubs = _parse(text, "built-in clubs.csv")
        if directory is not None:
            own = Path(directory) / CLUBS_FILE
            if own.exists():
                clubs += _parse(own.read_text(encoding="utf-8-sig"), str(own))
        return cls(clubs)

    def find(self, country: str, code: str) -> Club | None:
        """The club for an EGD club code. Without a country, only an unambiguous code is found."""
        country, code = (country or "").strip().upper(), (code or "").strip()
        if not code:
            return None
        club = self.exact.get((country, code)) or self.folded.get((country, code.casefold()))
        if club or country:
            return club
        candidates = self.by_code.get(code.casefold(), [])
        return candidates[0] if len(candidates) == 1 else None

    def name(self, country: str, code: str) -> str:
        """Full club name, or the code itself if the club is not in the list."""
        club = self.find(country, code)
        return club.name if club else (code or "").strip()

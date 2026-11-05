"""Access to the European Go Database (EGD).

Two sources:
- the full player list (``allworld_lp.zip``, updated daily by the EGD), downloaded once a day
  and searched locally - fast enough for autocomplete and usable offline;
- the JSON API, for the latest data of a single player (by PIN) or a name search.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

BASE_URL = "https://www.europeangodatabase.eu/EGD"
PLAYER_LIST_URL = "https://europeangodatabase.eu/EGD/EGD_2_0/downloads/allworld_lp.zip"
USER_AGENT = "gotourney/0.1 (Go tournament organisation tool)"
TIMEOUT = 15
LIST_MAX_AGE = 24 * 3600   # seconds

NO_CLUB = {"XXXX", "xxxx", "-", ""}


class EGDError(Exception):
    pass


@dataclass(frozen=True)
class EGDPlayer:
    pin: str
    surname: str
    first_name: str
    country: str
    club: str
    grade: str
    gor: int
    tournaments: int
    last_appearance: str

    @property
    def name(self) -> str:
        return f"{self.surname} {self.first_name}".strip()

    def describe(self) -> str:
        return (f"{self.name}  {self.country} {self.club or '-'}  {self.grade}  "
                f"GoR {self.gor}  PIN {self.pin}")


# ---------------------------------------------------------------- name normalisation

def plain(text: str) -> str:
    """Lower case, no accents, '_'/'-' as spaces (keeps the spelling, used for ranking)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\s_\-]+", " ", text).strip()


def normalize(text: str) -> str:
    """Search key: lower case, no accents, umlaut spellings unified, '_'/'-' as spaces.

    'Lühtke_Hans' and 'Luehtke Hans' both become 'luhtke hans'.
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ß", "ss").replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return re.sub(r"[\s_\-]+", " ", text).strip()


def egd_name_part(text: str) -> str:
    """EGD writes spaces inside a name part as underscores."""
    return text.replace("_", " ").strip()


# ---------------------------------------------------------------- player list

_LINE_RE = re.compile(
    r"^\s*(?P<pin>\d{8})\s+(?P<name>.+?)\s+(?P<country>[A-Za-z]{2})\s+(?P<club>\S+)\s+"
    r"(?P<grade>\d{1,2}[kdpKDP])\s+(?P<pd>\S+)\s+(?P<gor>-?\d+)\s+(?P<nt>\d+)(?:\s+(?P<last>\S+))?\s*$"
)


def parse_player_list(text: str) -> list[EGDPlayer]:
    players = []
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        surname, _, first = m.group("name").partition(" ")
        club = m.group("club")
        players.append(EGDPlayer(
            pin=m.group("pin"),
            surname=egd_name_part(surname),
            first_name=egd_name_part(first),
            country=m.group("country").upper(),
            club="" if club in NO_CLUB else club,
            grade=m.group("grade").lower(),
            gor=int(m.group("gor")),
            tournaments=int(m.group("nt")),
            last_appearance=m.group("last") or "",
        ))
    return players


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "gotourney"


def list_path(directory: Path | None = None) -> Path:
    return (directory or cache_dir()) / "allworld_lp.html"


def download_player_list(directory: Path | None = None) -> Path:
    path = list_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(PLAYER_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            names = [n for n in z.namelist() if n.endswith(".html")]
            if not names:
                raise EGDError("player list archive has an unexpected content")
            data = z.read(names[0])
    except (requests.RequestException, zipfile.BadZipFile) as e:
        raise EGDError(f"cannot download the EGD player list: {e}") from e
    if not parse_player_list(data.decode("utf-8", errors="replace")[:20000]):
        raise EGDError("downloaded EGD player list has an unexpected format")
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def list_age(directory: Path | None = None) -> float | None:
    path = list_path(directory)
    return time.time() - path.stat().st_mtime if path.exists() else None


class PlayerIndex:
    """The EGD player list with a fast local search."""

    def __init__(self, players: list[EGDPlayer]):
        self.players = players
        self.by_pin = {p.pin: p for p in players}
        self._words = [normalize(f"{p.surname} {p.first_name}").split() for p in players]
        self._surnames = [normalize(p.surname) for p in players]
        self._plain_surnames = [plain(p.surname) for p in players]

    @classmethod
    def load(cls, directory: Path | None = None, refresh: bool | None = None) -> "PlayerIndex":
        """Load the cached list; download it first if missing or (when refresh is None) older than a day.

        If a refresh fails but an old list exists, the old list is used.
        """
        path = list_path(directory)
        age = list_age(directory)
        if refresh or age is None or (refresh is None and age > LIST_MAX_AGE):
            try:
                download_player_list(directory)
            except EGDError:
                if not path.exists():
                    raise
        return cls(parse_player_list(path.read_text(encoding="utf-8", errors="replace")))

    def search(self, query: str, limit: int = 50) -> list[EGDPlayer]:
        """Players matching all words of the query (each word = prefix of a name word).

        A query of digits searches PINs. Results whose surname starts with the query come first.
        """
        q = query.strip()
        if not q:
            return []
        if q.isdigit():
            return [p for p in self.players if p.pin.startswith(q)][:limit]
        tokens = normalize(q).split()
        if not tokens:
            return []
        joined = " ".join(tokens)
        plain_query = plain(q)
        hits = []
        for i, words in enumerate(self._words):
            if all(any(w.startswith(t) for w in words) for t in tokens):
                surname = self._surnames[i]
                if self._plain_surnames[i].startswith(plain_query):
                    score = 0
                elif surname.startswith(joined):
                    score = 1
                elif surname.startswith(tokens[0]):
                    score = 2
                else:
                    score = 3
                hits.append((score, -self.players[i].tournaments, i))
        hits.sort()
        return [self.players[i] for _, _, i in hits[:limit]]


# ---------------------------------------------------------------- JSON API

def _api_player(d: dict) -> EGDPlayer:
    def num(key):
        try:
            return int(d.get(key) or 0)
        except ValueError:
            return 0
    club = (d.get("Club") or "").strip()
    return EGDPlayer(
        pin=str(d.get("Pin_Player", "")),
        surname=egd_name_part(d.get("Real_Last_Name") or d.get("Last_Name") or ""),
        first_name=egd_name_part(d.get("Real_Name") or d.get("Name") or ""),
        country=(d.get("Country_Code") or "").upper(),
        club="" if club in NO_CLUB else club,
        grade=(d.get("Grade") or "").lower(),
        gor=num("Gor"),
        tournaments=num("Tot_Tournaments"),
        last_appearance=d.get("Last_Appearance") or "",
    )


def _get_json(endpoint: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        raise EGDError(f"EGD request failed: {e}") from e


def fetch_by_pin(pin: str) -> EGDPlayer:
    data = _get_json("GetPlayerDataByPIN.php", {"pin": pin})
    if data.get("retcode") != "Ok":
        raise EGDError(f"EGD PIN {pin} not found")
    return _api_player(data)


def search_by_name(surname: str, first_name: str = "") -> list[EGDPlayer]:
    params = {"lastname": surname}
    if first_name:
        params["name"] = first_name
    data = _get_json("GetPlayerDataByData.php", params)
    if data.get("retcode") != "Ok":
        return []
    return [_api_player(p) for p in data.get("players", [])]

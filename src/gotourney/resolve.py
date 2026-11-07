"""Finding players from (incomplete) names typed into a round file, e.g. 'Becker' or 'becker a'."""

from __future__ import annotations

import re

from .egd import normalize
from .models import Player

_RANK = re.compile(r"^\d{1,2}\s*[kdp]\b", re.IGNORECASE)


def clean(text: str) -> str:
    """Remove a leading rank and a rank in brackets: '5d Becker Anna (5d)' -> 'Becker Anna'."""
    t = re.sub(r"\(\s*\d{1,2}\s*[kdp]\s*\)", " ", text, flags=re.IGNORECASE).strip()
    t = _RANK.sub("", t).strip()
    return re.sub(r"\s+", " ", t)


def _assign(tokens: list[str], words: list[str]) -> bool:
    """Can every token be matched to a *different* word that starts with it?"""
    if not tokens:
        return True
    first, rest = tokens[0], tokens[1:]
    for i, w in enumerate(words):
        if w.startswith(first) and _assign(rest, words[:i] + words[i + 1:]):
            return True
    return False


def match_players(text: str, players: list[Player]) -> list[Player]:
    """Players whose name matches the text, best matches first.

    Every word of the text must be the beginning of a word of 'surname first name' (case,
    accents and umlaut spellings are ignored). A number is taken as a player ID.
    """
    t = clean(text)
    if not t:
        return []
    if t.isdigit():
        return [p for p in players if p.id == int(t)]
    tokens = normalize(t).split()
    hits = []
    for p in players:
        surname = normalize(p.surname)
        words = normalize(f"{p.surname} {p.first_name}").split()
        if not _assign(tokens, words):
            continue
        joined = " ".join(tokens)
        if surname == joined or surname == tokens[0]:
            score = 0                           # surname typed in full
        elif surname.startswith(tokens[0]):
            score = 1                           # beginning of the surname
        else:
            score = 2                           # e.g. only the first name
        hits.append((score, normalize(p.surname), normalize(p.first_name), p.id, p))
    hits.sort(key=lambda h: h[:4])
    return [h[4] for h in hits]

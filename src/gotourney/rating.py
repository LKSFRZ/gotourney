"""Tournament rating (TGoR) updates.

Based on the EGF rating system as revised in 2021:

    h(H)    = 0 if H == 0 else 100 * (H - 0.5)      # handicap stones, received by Black
    beta(r) = -7 * ln(3300 - h - r)
    SE_A    = 1 / (1 + exp(beta_B - beta_A))
    con(r)  = ((3300 - r) / 200) ** 1.6
    r'      = max(r + k_factor * con(r) * (S - SE), -900)

Differences to the EGD: ``con`` is multiplied by the tournament's ``k_factor`` and the
EGD anti-deflation bonus term is not used. Komi does not enter the formula.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Hashable, Iterable, Mapping

MIN_RATING = -900.0


def handicap_points(handicap: int) -> float:
    """Rating points a handicap is worth for the player receiving it."""
    if handicap < 0:
        raise ValueError("handicap must not be negative")
    return 0.0 if handicap == 0 else 100.0 * (handicap - 0.5)


def beta(rating: float, handicap: int = 0) -> float:
    effective = rating + handicap_points(handicap)
    if effective >= 3300:
        raise ValueError(f"rating {rating} with handicap {handicap} is out of range")
    return -7.0 * math.log(3300.0 - effective)


def expected_score(rating_a: float, rating_b: float, handicap_a: int = 0, handicap_b: int = 0) -> float:
    """Expected score of A against B. ``handicap_x`` = stones received by that player."""
    return 1.0 / (1.0 + math.exp(beta(rating_b, handicap_b) - beta(rating_a, handicap_a)))


def con(rating: float) -> float:
    return ((3300.0 - rating) / 200.0) ** 1.6


@dataclass(frozen=True)
class RatedGame:
    """A game to be rated. Black receives ``handicap`` stones; ``white_score`` is 1, 0.5 or 0."""

    white: Hashable
    black: Hashable
    handicap: int
    white_score: float


def game_changes(r_white: float, r_black: float, handicap: int, white_score: float,
                 k_factor: float) -> tuple[float, float]:
    """Rating changes (white, black) for one game."""
    if white_score not in (0.0, 0.5, 1.0):
        raise ValueError(f"invalid score {white_score}")
    se_white = expected_score(r_white, r_black, 0, handicap)
    se_black = 1.0 - se_white
    d_white = k_factor * con(r_white) * (white_score - se_white)
    d_black = k_factor * con(r_black) * ((1.0 - white_score) - se_black)
    return d_white, d_black


def rate_round(ratings: Mapping[Hashable, float], games: Iterable[RatedGame],
               k_factor: float) -> dict[Hashable, float]:
    """New ratings after one round.

    All games are rated from the ratings *before* the round; the changes are applied
    together. Players without a game keep their rating.
    """
    changes: dict[Hashable, float] = {}
    seen: set[Hashable] = set()
    for g in games:
        for pid in (g.white, g.black):
            if pid in seen:
                raise ValueError(f"player {pid} has more than one game in this round")
            if pid not in ratings:
                raise KeyError(f"no rating for player {pid}")
            seen.add(pid)
        dw, db = game_changes(ratings[g.white], ratings[g.black], g.handicap, g.white_score, k_factor)
        changes[g.white] = dw
        changes[g.black] = db
    return {pid: max(r + changes.get(pid, 0.0), MIN_RATING) for pid, r in ratings.items()}

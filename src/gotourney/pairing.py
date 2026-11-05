"""Pairing a round with the blossom algorithm (maximum weight matching)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import networkx as nx

from .config import Config
from .models import Game
from .tournament import Tournament, TournamentError

MAX_HANDICAP = 9


class PairingError(Exception):
    pass


def full_handicap(diff: float) -> int:
    """Stones for a TGoR difference: one per 100 points, exact halves rounded down (150 -> 1)."""
    return max(0, math.ceil(abs(diff) / 100.0 - 0.5))


def default_handicap(diff: float, reduction: int) -> int:
    return max(min(full_handicap(diff), MAX_HANDICAP) - reduction, 0)


def pair_cost(r_a: float, r_b: float, same_club: bool, club_penalty: float) -> float:
    return (abs(r_a - r_b) + (club_penalty if same_club else 0.0)) ** 2


def same_club(t: Tournament, a: int, b: int) -> bool:
    ca, cb = t.players[a].club.strip().lower(), t.players[b].club.strip().lower()
    return bool(ca) and ca == cb


def rng_for(cfg: Config, round_no: int, purpose: str) -> random.Random:
    """Reproducible random numbers: the same seed, round and purpose always give the same draw."""
    return random.Random(f"{cfg.pairing.random_seed}-{round_no}-{purpose}")


@dataclass
class PairingResult:
    games: list[Game]
    sitting_out: list[tuple[int, str]]        # (player ID, reason)
    total_cost: float


def setup_game(t: Tournament, round_no: int, a: int, b: int, ratings: dict[int, float],
               rng: random.Random, manual: bool = False) -> Game:
    """Default handicap, komi and colours for a pair."""
    cfg = t.cfg
    h = default_handicap(ratings[a] - ratings[b], cfg.handicap.reduction)
    if h > 0:
        white, black = (a, b) if ratings[a] >= ratings[b] else (b, a)
    else:
        ba, bb = t.colour_balance(a, round_no), t.colour_balance(b, round_no)
        if ba != bb:
            white, black = (b, a) if ba > bb else (a, b)
        else:
            white, black = (a, b) if rng.random() < 0.5 else (b, a)
    komi = cfg.handicap.komi_handicap if h > 0 else cfg.handicap.komi_even
    return Game(board=0, white=white, black=black, handicap=h, komi=komi, manual=manual)


def choose_joker(t: Tournament, round_no: int, candidates: list[int]) -> int:
    """The joker with the most games played sits out; ties are drawn at random."""
    most = max(t.games_played(p, round_no) for p in candidates)
    best = sorted(p for p in candidates if t.games_played(p, round_no) == most)
    return rng_for(t.cfg, round_no, "joker").choice(best)


def pair_round(t: Tournament, round_no: int, manual_games: list[Game] | None = None) -> PairingResult:
    cfg = t.cfg
    if round_no < 1 or round_no > cfg.tournament.rounds:
        raise PairingError(f"the tournament has rounds 1 to {cfg.tournament.rounds}")
    try:
        ratings = t.rating_before(round_no)
    except TournamentError as e:
        raise PairingError(f"cannot pair round {round_no}: {e}") from None
    for r in range(1, round_no):
        if r in t.rounds and not t.rounds[r].complete:
            raise PairingError(f"round {r} is not complete; enter all results first")
    manual_games = list(manual_games or [])
    rng = rng_for(cfg, round_no, "colours")

    # manual boards: keep, fill in defaults where handicap was left empty (done by caller)
    on_manual = {pid for g in manual_games for pid in g.players()}
    registered = sorted(pid for pid, p in t.players.items() if p.plays(round_no))
    for pid in on_manual:
        if pid not in t.players:
            raise PairingError(f"manual board: unknown player ID {pid}")
    participants = [pid for pid in registered if pid not in on_manual]
    sitting_out = [(pid, "not registered for this round")
                   for pid in sorted(t.players) if not t.players[pid].plays(round_no) and pid not in on_manual]

    if len(participants) % 2 == 1:
        jokers = [pid for pid in participants if t.players[pid].joker]
        if not jokers:
            raise PairingError(
                f"round {round_no} has an odd number of players to pair ({len(participants)}) and no "
                f"joker among them. Mark a joker in players.ods (Joker column) and try again.")
        joker = choose_joker(t, round_no, jokers)
        participants.remove(joker)
        sitting_out.insert(0, (joker, "joker (odd number of players)"))

    played = t.played_pairs(before_round=round_no)
    graph = nx.Graph()
    graph.add_nodes_from(participants)
    costs = {}
    for i, a in enumerate(participants):
        for b in participants[i + 1:]:
            if frozenset((a, b)) in played:
                continue
            costs[(a, b)] = pair_cost(ratings[a], ratings[b], same_club(t, a, b), cfg.pairing.club_penalty)
    big = max(costs.values(), default=0.0) + 1.0
    for (a, b), c in costs.items():
        graph.add_edge(a, b, weight=big - c)
    matching = nx.max_weight_matching(graph, maxcardinality=True) if participants else set()
    if 2 * len(matching) != len(participants):
        matched = {p for pair in matching for p in pair}
        unmatched = [t.name(p) for p in participants if p not in matched]
        raise PairingError(
            "no complete pairing without rematches is possible. Unpaired: " + ", ".join(unmatched)
            + ". Pair some players by hand as manual boards (pair --template) and run pair again.")

    games = list(manual_games)
    total = 0.0
    for a, b in sorted((tuple(sorted(pair)) for pair in matching)):
        games.append(setup_game(t, round_no, a, b, ratings, rng))
        total += costs[(a, b)] if (a, b) in costs else costs[(b, a)]
    games.sort(key=lambda g: (-max(ratings[g.white], ratings[g.black]),
                              -min(ratings[g.white], ratings[g.black]), g.white))
    for i, g in enumerate(games, start=1):
        g.board = i
    return PairingResult(games, sitting_out, total)

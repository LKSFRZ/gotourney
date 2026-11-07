"""Pairing a round with the blossom algorithm (maximum weight matching)."""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

import networkx as nx

from .config import RULE_BUILTIN_FIELDS, Config, PairingRule
from .models import Game
from .players import field_value
from .tournament import Tournament, TournamentError

MAX_HANDICAP = 9


class PairingError(Exception):
    pass


def full_handicap(diff: float) -> int:
    """Stones for a TGoR difference: one per full 100 points, always rounded down (199 -> 1, 200 -> 2)."""
    return int(math.floor(abs(diff) / 100.0))


def default_handicap(diff: float, reduction: int) -> int:
    return max(min(full_handicap(diff), MAX_HANDICAP) - reduction, 0)


def handicap_for(cfg: Config, rating_a: float, rating_b: float) -> int:
    """Default handicap of a pair: ratings below the handicap floor count as the floor."""
    floor = cfg.handicap.floor
    if floor is not None:
        rating_a, rating_b = max(rating_a, floor), max(rating_b, floor)
    return default_handicap(rating_a - rating_b, cfg.handicap.reduction)


def pair_cost(r_a: float, r_b: float, extra_points: float = 0.0) -> float:
    """Cost of a pair: (TGoR difference + points of the rules that apply) squared."""
    return (abs(r_a - r_b) + extra_points) ** 2


def _norm(value: str) -> str:
    return value.strip().casefold()


_REST = object()     # group of all values outside the configured groups


def _group_key(rule: PairingRule, value: str):
    """The rule's group of a value: the value itself, or the index of its group (with groups)."""
    v = _norm(value)
    groups = rule.all_groups
    if not groups:
        return v
    for i, g in enumerate(groups):
        if v in {_norm(x) for x in g}:
            return i
    return _REST


def rule_applies(rule: PairingRule, value_a: str, value_b: str) -> bool:
    """Does the rule apply to a pair whose players have these values in the rule's field?

    With values / groups, values of one group count as the same value and all other values
    together form "the rest".
    """
    ka, kb = _group_key(rule, value_a), _group_key(rule, value_b)
    if rule.type in ("avoid_same", "forbid_same"):
        # an empty cell is not a value (players without a club are not "in the same club"),
        # and with groups only values inside a group count
        return ka == kb and ka not in ("", _REST)
    # prefer_same / require_same: different values / groups; two empty cells or two values
    # from "the rest" count as the same
    return ka != kb


def check_rule_fields(t: Tournament) -> None:
    known = {f.lower() for f in RULE_BUILTIN_FIELDS} | {f.lower() for f in t.extra_fields}
    for rule in t.cfg.pairing.rules:
        if rule.field.lower() not in known:
            raise PairingError(
                f"pairing rule '{rule.describe()}': there is no column {rule.field!r} in players.ods "
                f"(rules can use {', '.join(RULE_BUILTIN_FIELDS)} or an additional field)")


def pair_rules(t: Tournament, a: int, b: int) -> tuple[float, bool, list[PairingRule]]:
    """(extra points, forbidden?, rules that apply) for a pair of players."""
    points, forbidden, applied = 0.0, False, []
    pa, pb = t.players[a], t.players[b]
    for rule in t.cfg.pairing.rules:
        if rule_applies(rule, field_value(pa, rule.field), field_value(pb, rule.field)):
            applied.append(rule)
            if rule.hard:
                forbidden = True
            else:
                points += rule.points
    return points, forbidden, applied


def rng_for(cfg: Config, round_no: int, purpose: str) -> random.Random:
    """Reproducible random numbers: the same seed, round and purpose always give the same draw."""
    return random.Random(f"{cfg.pairing.random_seed}-{round_no}-{purpose}")


@dataclass
class PairingResult:
    games: list[Game]
    sitting_out: list[tuple[int, str]]        # (player ID, reason)
    total_cost: float
    rule_hits: Counter = field(default_factory=Counter)   # rule description -> number of boards


def setup_game(t: Tournament, round_no: int, a: int, b: int, ratings: dict[int, float],
               rng: random.Random, finalized: bool = False) -> Game:
    """Default handicap, komi and colours for a pair."""
    cfg = t.cfg
    h = handicap_for(cfg, ratings[a], ratings[b])
    if h > 0:
        white, black = (a, b) if ratings[a] >= ratings[b] else (b, a)
    else:
        ba, bb = t.colour_balance(a, round_no), t.colour_balance(b, round_no)
        if ba != bb:
            white, black = (b, a) if ba > bb else (a, b)
        else:
            white, black = (a, b) if rng.random() < 0.5 else (b, a)
    komi = cfg.handicap.komi_handicap if h > 0 else cfg.handicap.komi_even
    return Game(board=0, white=white, black=black, handicap=h, komi=komi, finalized=finalized)


def choose_joker(t: Tournament, round_no: int, candidates: list[int]) -> int:
    """The joker with the most games played sits out; ties are drawn at random."""
    most = max(t.games_played(p, round_no) for p in candidates)
    best = sorted(p for p in candidates if t.games_played(p, round_no) == most)
    return rng_for(t.cfg, round_no, "joker").choice(best)


def pair_round(t: Tournament, round_no: int, finalized_games: list[Game] | None = None) -> PairingResult:
    """Pair all players of the round who are not on one of the finalized boards.

    Finalized boards are returned unchanged. A finalized board with a board number keeps it; all
    other boards are sorted by TGoR and get the free board numbers (after a started round: the
    numbers after the existing boards)."""
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
    finalized_games = list(finalized_games or [])
    rng = rng_for(cfg, round_no, "colours")
    check_rule_fields(t)

    # finalized boards: kept as they are (defaults for an empty handicap are filled in by the caller)
    on_finalized = {pid for g in finalized_games for pid in g.players()}
    registered = sorted(pid for pid, p in t.players.items() if p.plays(round_no))
    for pid in on_finalized:
        if pid not in t.players:
            raise PairingError(f"finalized board: unknown player ID {pid}")
    participants = [pid for pid in registered if pid not in on_finalized]
    sitting_out = [(pid, "not registered for this round")
                   for pid in sorted(t.players) if not t.players[pid].plays(round_no) and pid not in on_finalized]

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
            points, forbidden, _ = pair_rules(t, a, b)
            if forbidden:
                continue
            costs[(a, b)] = pair_cost(ratings[a], ratings[b], points)
    big = max(costs.values(), default=0.0) + 1.0
    for (a, b), c in costs.items():
        graph.add_edge(a, b, weight=big - c)
    matching = nx.max_weight_matching(graph, maxcardinality=True) if participants else set()
    if 2 * len(matching) != len(participants):
        matched = {p for pair in matching for p in pair}
        unmatched = [t.name(p) for p in participants if p not in matched]
        hard = [r.describe() for r in cfg.pairing.rules if r.hard]
        raise PairingError(
            "no complete pairing without rematches" + (f" or forbidden pairs ({'; '.join(hard)})" if hard else "")
            + " is possible. Unpaired: " + ", ".join(unmatched)
            + ". Pair some players by hand (finalized boards) and run pair again.")

    games = list(finalized_games)
    total = 0.0
    hits: Counter = Counter()
    for a, b in sorted((tuple(sorted(pair)) for pair in matching)):
        games.append(setup_game(t, round_no, a, b, ratings, rng))
        total += costs[(a, b)] if (a, b) in costs else costs[(b, a)]
    for g in games:
        for rule in pair_rules(t, g.white, g.black)[2]:
            hits[rule.describe() + (" (finalized board)" if g.finalized else "")] += 1
    number_boards(games, ratings)
    return PairingResult(games, sitting_out, total, hits)


def number_boards(games: list[Game], ratings: dict[int, float]) -> None:
    """Finalized boards with a number keep it; the others get the free numbers in TGoR order."""
    used: set[int] = set()
    rest = []
    for g in games:
        if g.finalized and g.board > 0 and g.board not in used:
            used.add(g.board)
        else:
            rest.append(g)
    rest.sort(key=lambda g: (-max(ratings[g.white], ratings[g.black]),
                             -min(ratings[g.white], ratings[g.black]), g.white))
    n = 1
    for g in rest:
        while n in used:
            n += 1
        g.board = n
        used.add(n)
    games.sort(key=lambda g: g.board)

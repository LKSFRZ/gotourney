import pytest

from gotourney.models import Game, Result
from gotourney.pairing import (PairingError, default_handicap, full_handicap, pair_cost,
                               pair_round)
from gotourney.rounds import load_round, save_round
from gotourney.tournament import Tournament


@pytest.mark.parametrize("diff, stones", [(0, 0), (50, 0), (51, 1), (150, 1), (151, 2), (250, 2),
                                          (251, 3), (850, 8), (851, 9), (2000, 20), (-151, 2)])
def test_full_handicap_halves_round_down(diff, stones):
    assert full_handicap(diff) == stones


def test_default_handicap_reduction_and_cap():
    assert default_handicap(2000, 0) == 9
    assert default_handicap(2000, 2) == 7
    assert default_handicap(151, 1) == 1      # stays a handicap-1 game
    assert default_handicap(120, 1) == 0
    assert default_handicap(40, 3) == 0


def test_pair_cost():
    assert pair_cost(2000, 1900) == 100 ** 2
    assert pair_cost(2000, 1900, 150) == 250 ** 2


def write_results(t, r, games, results):
    for g, res in zip(games, results):
        g.result = res
    names = {pid: p.name for pid, p in t.players.items()}
    save_round(t.directory / f"round_{r}.ods", games, names, t.rating_before(r))


def test_pairs_neighbours_and_board_order(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1480,), (1000,), (1010,)])
    t = Tournament.load(d)
    res = pair_round(t, 1)
    pairs = [frozenset(g.players()) for g in res.games]
    assert pairs == [frozenset({1, 2}), frozenset({3, 4}), frozenset({5, 6})]
    assert [g.board for g in res.games] == [1, 2, 3]
    assert all(g.handicap == 0 and g.komi == 6.5 for g in res.games)


def test_club_penalty_avoids_same_club(make_tournament):
    d = make_tournament([(2000, "HH"), (1990, "HH"), (1950, "B"), (1940, "SN")])
    pairs = {frozenset(g.players()) for g in pair_round(Tournament.load(d), 1).games}
    assert frozenset({1, 2}) not in pairs
    d2 = make_tournament([(2000, "HH"), (1990, "HH"), (1950, "B"), (1940, "SN")],
                         points=0)
    pairs2 = {frozenset(g.players()) for g in pair_round(Tournament.load(d2), 1).games}
    assert frozenset({1, 2}) in pairs2


def test_squared_cost_prefers_two_medium_differences(make_tournament):
    # linear cost would be indifferent; squares avoid the 300-point pair
    d = make_tournament([(2300,), (2100,), (2000,), (1800,)])
    pairs = {frozenset(g.players()) for g in pair_round(Tournament.load(d), 1).games}
    assert pairs == {frozenset({1, 2}), frozenset({3, 4})}


def test_handicap_and_colours(make_tournament):
    d = make_tournament([(2300,), (2000,)], komi_handicap=0.5)
    g = pair_round(Tournament.load(d), 1).games[0]
    assert (g.white, g.black, g.handicap, g.komi) == (1, 2, 3, 0.5)


def test_no_rematch_and_colour_balance(make_tournament):
    d = make_tournament([(2000,), (1995,), (1990,), (1985,)])
    t = Tournament.load(d)
    r1 = pair_round(t, 1)
    write_results(t, 1, r1.games, [Result.WHITE_WINS, Result.BLACK_WINS])
    t = Tournament.load(d)
    r2 = pair_round(t, 2)
    old = {frozenset(g.players()) for g in r1.games}
    assert not old & {frozenset(g.players()) for g in r2.games}
    whites_r1 = {g.white for g in r1.games}
    for g in r2.games:          # every pair has one former white and one former black
        assert g.black in whites_r1 and g.white not in whites_r1


def test_odd_number_needs_joker(make_tournament):
    d = make_tournament([(2000,), (1990,), (1980,)])
    with pytest.raises(PairingError, match="joker"):
        pair_round(Tournament.load(d), 1)


def test_joker_with_most_games_sits_out(make_tournament):
    # round 1: 4 players (3 and 4 are jokers, 5 does not play); round 2: 5 players
    d = make_tournament([(2000,), (1990,), (1980, None, True), (1970, None, True),
                         (1960, None, True, [2])], rounds=2)
    t = Tournament.load(d)
    r1 = pair_round(t, 1)
    assert r1.sitting_out[0][0] == 5
    write_results(t, 1, r1.games, [Result.WHITE_WINS, Result.WHITE_WINS])
    t = Tournament.load(d)
    r2 = pair_round(t, 2)
    joker = [pid for pid, reason in r2.sitting_out if "joker" in reason]
    assert len(joker) == 1 and joker[0] in (3, 4)      # 5 has played no game yet


def test_impossible_without_rematch(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=2)
    t = Tournament.load(d)
    r1 = pair_round(t, 1)
    write_results(t, 1, r1.games, [Result.WHITE_WINS])
    with pytest.raises(PairingError, match="no complete pairing"):
        pair_round(Tournament.load(d), 2)


def test_previous_round_must_be_complete(make_tournament):
    d = make_tournament([(2000,), (1990,), (1980,), (1970,)])
    t = Tournament.load(d)
    r1 = pair_round(t, 1)
    write_results(t, 1, r1.games, [Result.WHITE_WINS, None])
    with pytest.raises(PairingError, match="not complete"):
        pair_round(Tournament.load(d), 2)


def test_manual_boards_are_kept(make_tournament):
    d = make_tournament([(2000,), (1990,), (1980,), (1970,), (1500,), (1490,)])
    t = Tournament.load(d)
    manual = [Game(0, 1, 6, 0, 6.5, finalized=True)]
    res = pair_round(t, 1, manual)
    pairs = {frozenset(g.players()) for g in res.games}
    assert frozenset({1, 6}) in pairs and len(res.games) == 3
    assert res.games[0].finalized            # board 1: highest TGoR

import pytest

from gotourney.config import ConfigError, parse_config
from gotourney.pairing import pair_round
from gotourney.registration import check_players
from gotourney.tournament import Tournament
from gotourney.wall import ranking


@pytest.mark.parametrize("value, bar", [(None, 2300.0), ("3d", 2300.0), ("5d", 2500.0), ("2k", 1900.0),
                                        (2350, 2350.0), ("2400", 2400.0), ("none", None), ("", None),
                                        (False, None)])
def test_top_bar_setting(value, bar):
    data = {} if value is None else {"rating": {"top_bar": value}}
    assert parse_config(data).rating.top_bar == bar


def test_top_bar_invalid():
    with pytest.raises(ConfigError, match="top_bar"):
        parse_config({"rating": {"top_bar": "strong"}})


def test_starting_tgor_capped(make_tournament):
    d = make_tournament([(2543,), (2400,), (2297,), (2100,)], rounds=1)
    t = Tournament.load(d)
    assert t.start == {1: 2300, 2: 2300, 3: 2297, 4: 2100}
    assert t.start_gor[1] == 2543
    # pairing and handicap use the capped TGoR: 2300 vs 2300 is an even game
    games = pair_round(t, 1).games
    assert {frozenset(g.players()) for g in games} == {frozenset({1, 2}), frozenset({3, 4})}
    top = next(g for g in games if 1 in g.players())
    assert top.handicap == 0


def test_no_top_bar(make_tournament):
    d = make_tournament([(2543,), (2100,)], rounds=1, top_bar='"none"')
    t = Tournament.load(d)
    assert t.start[1] == 2543
    assert pair_round(t, 1).games[0].handicap == 4


def test_tie_break_uses_real_gor(make_tournament):
    d = make_tournament([(2543,), (2400,)], rounds=1)
    t = Tournament.load(d)                      # both start (and end, without games) at 2300
    assert ranking(t) == [2, 1]                 # lower real GoR ranks higher


def test_check_reports_players_above_bar(make_tournament):
    d = make_tournament([(2543,), (2000,)], rounds=1)
    t = Tournament.load(d)
    infos = [i.message for i in check_players(list(t.players.values()), t.cfg) if i.level == "info"]
    assert any("top bar 2300" in m and "P1" in m for m in infos)

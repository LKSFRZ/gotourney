import math

import pytest

from gotourney.rating import (
    RatedGame, con, expected_score, game_changes, handicap_points, rate_round,
)


def egd_bonus(r):
    return math.log1p(math.exp((2300 - r) / 80)) / 5


# Reference values from the 'skillratings' crate (EGF 2021 implementation, k_factor = 1, with bonus).
def test_expected_score_reference_values():
    assert expected_score(1000, 1300) == pytest.approx(0.2732225596195188)
    assert expected_score(1000, 1300, 0, 1) == pytest.approx(0.23947531043217862)
    assert expected_score(1000, 1300, 1, 0) == pytest.approx(0.30481324383684405)


@pytest.mark.parametrize(
    "r1, r2, s1, new1, new2",
    [
        (1000, 1300, 1.0, 1039, 1274),
        (0, 0, 0.0, -39, 50),
        (0, 0, 0.5, 6, 6),
    ],
)
def test_egd_update_with_bonus_matches_reference(r1, r2, s1, new1, new2):
    d1, d2 = game_changes(r1, r2, 0, s1, k_factor=1.0)
    assert round(r1 + d1 + egd_bonus(r1)) == new1
    assert round(r2 + d2 + egd_bonus(r2)) == new2


def test_rating_period_reference():
    # one player at 0 plays four opponents; all games rated from the pre-period rating
    total = 0.0
    for opp, score in [(20, 1.0), (40, 0.5), (10, 0.0), (-40, 1.0)]:
        d, _ = game_changes(0, opp, 0, score, k_factor=1.0)
        total += d + egd_bonus(0)
    assert round(total) == 69


def test_handicap_points():
    assert handicap_points(0) == 0
    assert handicap_points(1) == 50
    assert handicap_points(2) == 150
    assert handicap_points(9) == 850
    with pytest.raises(ValueError):
        handicap_points(-1)


def test_handicap_compensates_rating_difference():
    # Black 50 points weaker with handicap 1, or 150 weaker with 2 stones: even chances
    assert expected_score(2000, 1950, 0, 1) == pytest.approx(0.5)
    assert expected_score(2000, 1850, 0, 2) == pytest.approx(0.5)


def test_con():
    assert con(2100) == pytest.approx(6 ** 1.6)


def test_k_factor_scales_changes():
    d1 = game_changes(2000, 1900, 0, 1.0, 1.0)
    d3 = game_changes(2000, 1900, 0, 1.0, 3.0)
    assert d3[0] == pytest.approx(3 * d1[0])
    assert d3[1] == pytest.approx(3 * d1[1])


def test_jigo_between_equals_changes_nothing():
    assert game_changes(1800, 1800, 0, 0.5, 3.0) == pytest.approx((0.0, 0.0))


def test_rate_round_uses_pre_round_ratings_and_keeps_absent():
    ratings = {1: 2000.0, 2: 2000.0, 3: 1500.0}
    new = rate_round(ratings, [RatedGame(1, 2, 0, 1.0)], k_factor=2.0)
    d = 2.0 * con(2000) * 0.5
    assert new[1] == pytest.approx(2000 + d)
    assert new[2] == pytest.approx(2000 - d)
    assert new[3] == 1500.0


def test_rate_round_rejects_double_booking():
    with pytest.raises(ValueError):
        rate_round({1: 0.0, 2: 0.0, 3: 0.0},
                   [RatedGame(1, 2, 0, 1.0), RatedGame(1, 3, 0, 1.0)], 1.0)


def test_rating_floor():
    new = rate_round({1: -890.0, 2: -890.0}, [RatedGame(2, 1, 0, 1.0)], k_factor=1.0)
    assert new[1] == -900.0

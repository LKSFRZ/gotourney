import pytest

from gotourney.models import Result, ResultError


@pytest.mark.parametrize("text, result", [
    ("1-0", Result.WHITE_WINS), (" 0 - 1 ", Result.BLACK_WINS), ("1:0", Result.WHITE_WINS),
    ("jigo", Result.JIGO), ("½-½", Result.JIGO), ("0.5-0.5", Result.JIGO),
    ("1-0!", Result.WHITE_WINS_FORFEIT), ("0-0!", Result.BOTH_LOSE_FORFEIT), ("", None),
])
def test_parse(text, result):
    assert Result.parse(text) is result


def test_invalid_result():
    with pytest.raises(ResultError):
        Result.parse("2-0")


def test_scores():
    assert Result.WHITE_WINS.white_score == 1.0
    assert Result.JIGO.white_score == 0.5
    assert Result.WHITE_WINS_FORFEIT.white_score is None
    assert Result.WHITE_WINS_FORFEIT.is_forfeit

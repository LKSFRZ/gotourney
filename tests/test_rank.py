import pytest

from gotourney.rank import Rank, RankError


@pytest.mark.parametrize("text, gor", [("1k", 2000), ("1d", 2100), ("5k", 1600),
                                       ("30k", -900), ("7d", 2700), (" 3 D ", 2300)])
def test_to_gor(text, gor):
    assert Rank.parse(text).to_gor() == gor


@pytest.mark.parametrize("gor, rank", [(2000, "1k"), (2049, "1k"), (2050, "1d"), (1950, "1k"),
                                       (1949, "2k"), (2543, "5d"), (-900, "30k"), (3000, "9d")])
def test_from_gor(gor, rank):
    assert str(Rank.from_gor(gor)) == rank


@pytest.mark.parametrize("text", ["", "0k", "31k", "10d", "5x", "k5"])
def test_invalid(text):
    with pytest.raises(RankError):
        Rank.parse(text)


def test_pro_needs_manual_gor():
    with pytest.raises(RankError):
        Rank.parse("2p").to_gor()

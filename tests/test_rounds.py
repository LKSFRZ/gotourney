import pytest

from gotourney.models import Game, Player, Result, ResultError
from gotourney.ods import OdsError, read_sheet, write_sheets
from gotourney.rank import Rank
from gotourney.rounds import COLUMNS, load_round, parse_marks, player_label, save_round


@pytest.mark.parametrize("w, d, b, result", [
    ("x", "", "", Result.WHITE_WINS), ("", "", "X", Result.BLACK_WINS), (" x ", None, None, Result.WHITE_WINS),
    ("", "x", "", Result.JIGO), ("x!", "", "", Result.WHITE_WINS_FORFEIT),
    ("", "", "x!", Result.BLACK_WINS_FORFEIT), ("!", "", "!", Result.BOTH_LOSE_FORFEIT),
    ("", "", "", None), (None, None, None, None), ("✓", "", "", Result.WHITE_WINS),
])
def test_parse_marks(w, d, b, result):
    assert parse_marks(w, d, b) is result


@pytest.mark.parametrize("w, d, b", [("x", "", "x"), ("x", "x", ""), ("", "x!", ""), ("-", "", "-"),
                                     ("1", "", ""), (1.0, None, None), ("w", "", ""), ("!", "", "")])
def test_parse_marks_invalid(w, d, b):
    with pytest.raises(ResultError):
        parse_marks(w, d, b)


def test_player_label():
    assert player_label(Player(1, "Maekawa", "Kaku", Rank.parse("5d"), 2543)) == "5d Maekawa Kaku"
    assert player_label(Player(2, "Doe", "John", None, 1600)) == "5k Doe John"


def test_round_file_roundtrip_and_layout(tmp_path):
    games = [Game(1, 1, 2, 2, 0.5, Result.WHITE_WINS), Game(2, 3, 4, 0, 6.5, Result.JIGO, finalized=True),
             Game(3, 5, 6, 0, 6.5, None), Game(4, 7, 8, 1, 0.5, Result.BLACK_WINS_FORFEIT)]
    labels = {i: f"1k P{i}" for i in range(1, 9)}
    save_round(tmp_path / "round_1.ods", games, labels, {i: 2000.0 for i in range(1, 9)})
    sheet = read_sheet(tmp_path / "round_1.ods", "Pairing")
    first = sheet.rows[0]
    assert first.text("White") == "○ 1k P1" and first.text("Black") == "● 1k P2"
    assert (first.text("White win"), first.text("Draw"), first.text("Black win")) == ("x", "", "")
    assert sheet.rows[1].text("Draw") == "x"
    rg = load_round(tmp_path, 1)
    assert [g.result for g in rg.games] == [g.result for g in games]
    assert rg.games[1].finalized and not rg.complete


def test_invalid_marks_name_the_row(tmp_path):
    write_sheets(tmp_path / "round_1.ods", [("Pairing", COLUMNS, [
        [1, 1, None, "", "x", "", "x", "", None, 2, 0, 6.5, ""]])])
    with pytest.raises(OdsError, match="row 2"):
        load_round(tmp_path, 1)

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import ConfigError, load_config, parse_config
from gotourney.models import Player
from gotourney.ods import Column, OdsError, read_sheet, write_sheet
from gotourney.players import load_players, save_players, starting_rating
from gotourney.rank import Rank


def test_ods_roundtrip(tmp_path):
    path = tmp_path / "t.ods"
    write_sheet(path, "S", [Column("A"), Column("B"), Column("C")],
                [[1, "two  spaces", None], ["x", 2.5, "multi\nline"], [None, None, None]])
    sheet = read_sheet(path)
    assert sheet.header == ["A", "B", "C"]
    assert len(sheet.rows) == 2
    assert sheet.rows[0].get("a") == 1.0
    assert sheet.rows[0].text("A") == "1"
    assert sheet.rows[0].text("B") == "two  spaces"
    assert sheet.rows[1].get("B") == 2.5
    assert sheet.rows[1].text("C") == "multi\nline"
    assert sheet.rows[1].line == 3


def test_ods_missing_file(tmp_path):
    with pytest.raises(OdsError):
        read_sheet(tmp_path / "nope.ods")


def sample_players():
    return [
        Player(1, "Maekawa", "Kaku", Rank.parse("6d"), 2543, pin="20633162", country="DE",
               club="K", rounds={1, 2, 3}),
        Player(2, "Doe", "John", Rank.parse("5k"), None, joker=True, rounds={2}),
    ]


def test_players_roundtrip(tmp_path):
    save_players(tmp_path, sample_players(), rounds=3)
    loaded = load_players(tmp_path, rounds=3)
    assert loaded.warnings == []
    a, b = loaded.players
    assert (a.id, a.name, str(a.rank), a.gor, a.pin, a.club, a.rounds, a.joker) == \
        (1, "Maekawa Kaku", "6d", 2543, "20633162", "K", {1, 2, 3}, False)
    assert b.gor is None and b.joker and b.rounds == {2}
    assert starting_rating(a) == 2543
    assert starting_rating(b) == 1600


def test_players_errors_name_the_row(tmp_path):
    from gotourney.players import columns
    write_sheet(tmp_path / "players.ods", "Players", columns(2),
                [[1, "A", "a", "3k", ""], [1, "B", "b", "xx", ""]])
    with pytest.raises(OdsError) as e:
        load_players(tmp_path, rounds=2)
    assert "row 3" in str(e.value)


def test_config_validation():
    with pytest.raises(ConfigError):
        parse_config({"handicap": {"komi_even": 5.5}})
    with pytest.raises(ConfigError):
        parse_config({"handicap": {"reduction": 10}})
    cfg = parse_config({"tournament": {"class": "B", "rounds": 4}})
    assert cfg.tournament.klass == "B" and cfg.tournament.rounds == 4


def test_cli_init(tmp_path):
    runner = CliRunner()
    target = tmp_path / "cup"
    result = runner.invoke(app, ["init", str(target), "--name", "Test Cup"])
    assert result.exit_code == 0, result.output
    cfg = load_config(target)
    assert cfg.tournament.name == "Test Cup"
    assert load_players(target, cfg.tournament.rounds).players == []
    again = runner.invoke(app, ["init", str(target)])
    assert again.exit_code == 1

import datetime as dt

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import parse_config
from gotourney.models import Player
from gotourney.players import load_players
from gotourney.rank import Rank
from gotourney.registration import (
    RegistrationError, check_players, new_player, parse_rounds, tournament_date,
)

runner = CliRunner()


def test_parse_rounds():
    assert parse_rounds("all", 5) == {1, 2, 3, 4, 5}
    assert parse_rounds("1,3-4", 5) == {1, 3, 4}
    assert parse_rounds("none", 5) == set()
    for bad in ("0", "6", "3-1", "a"):
        with pytest.raises(RegistrationError):
            parse_rounds(bad, 5)


def test_new_player_fills_gor_from_rank_and_ids():
    p1 = new_player([], surname="Doe", first_name="John", rank="5k", gor=None, rounds={1})
    assert (p1.id, p1.gor) == (1, 1600)
    p2 = new_player([p1], surname="Roe", first_name="Jane", rank=None, gor=2187, rounds={1})
    assert (p2.id, str(p2.rank)) == (2, "2d")


def test_new_player_rejects_duplicate_pin_and_missing_rating():
    p1 = new_player([], surname="A", first_name="", rank="1k", gor=None, pin="12345678", rounds=set())
    with pytest.raises(RegistrationError):
        new_player([p1], surname="B", first_name="", rank="1k", gor=None, pin="12345678", rounds=set())
    with pytest.raises(RegistrationError):
        new_player([], surname="C", first_name="", rank=None, gor=None, rounds=set())


def test_tournament_date():
    assert tournament_date("T261003A") == dt.date(2026, 10, 3)
    assert tournament_date("T960101") == dt.date(1996, 1, 1)
    assert tournament_date("xyz") is None


def make(pid, **kw):
    defaults = dict(surname=f"P{pid}", first_name="X", rank=Rank.parse("1k"), gor=2000.0,
                    club="HH", rounds={1, 2})
    defaults.update(kw)
    return Player(pid, **defaults)


def messages(issues, level):
    return [i.message for i in issues if i.level == level]


def test_check_odd_round_without_joker_is_error():
    cfg = parse_config({"tournament": {"rounds": 2}})
    players = [make(1), make(2), make(3, rounds={1})]
    errors = messages(check_players(players, cfg), "error")
    assert len(errors) == 1 and "round 1" in errors[0]
    players[0].joker = True
    assert messages(check_players(players, cfg), "error") == []


def test_check_warnings():
    cfg = parse_config({"tournament": {"rounds": 1}})
    players = [
        make(1, gor=2500.0, rank=Rank.parse("1k")),                       # rank/GoR mismatch
        make(2, pin="11111111", egd_last_tournament="T150101A"),          # outdated
        make(3, pin="11111111"),                                          # duplicate PIN
        make(4, rounds=set()),                                            # no rounds
    ]
    issues = check_players(players, cfg, today=dt.date(2026, 11, 5))
    warnings = " | ".join(messages(issues, "warning"))
    assert "differ by 500" in warnings
    assert "outdated" in warnings
    assert "not registered for any round" in warnings
    assert any("PIN 11111111" in m for m in messages(issues, "error"))


def test_cli_add_list_check(tmp_path):
    d = str(tmp_path)
    assert runner.invoke(app, ["init", d]).exit_code == 0
    r = runner.invoke(app, ["players", "add", "van den Broek", "Erik", "--rank", "1k", "--gor", "1987",
                            "--pin", "13986203", "--country", "nl", "--club", "Gron", "-d", d])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["players", "add", "Doe", "John", "-r", "5k", "--rounds", "1-3",
                            "--joker", "-d", d])
    assert r.exit_code == 0, r.output
    assert "GoR 1600" in r.output
    players = load_players(tmp_path, 5).players
    assert [p.id for p in players] == [1, 2]
    assert players[0].country == "NL" and players[1].rounds == {1, 2, 3} and players[1].joker
    r = runner.invoke(app, ["players", "list", "-d", d])
    assert "van den Broek Erik" in r.output and "2 players" in r.output
    r = runner.invoke(app, ["players", "check", "-d", d])
    # rounds 1-3 have two players; rounds 4 and 5 only one and no joker
    assert r.exit_code == 1
    assert "round 4" in r.output and "round 5" in r.output and "round 3" not in r.output


def test_init_rounds_and_changing_rounds_later(tmp_path):
    import re
    d = str(tmp_path)
    r = runner.invoke(app, ["init", d, "--rounds", "3"])
    assert r.exit_code == 0 and "3 rounds" in r.output
    runner.invoke(app, ["players", "add", "Doe", "John", "-r", "5k", "--rounds", "1,3", "-d", d])
    assert load_players(tmp_path, 3).players[0].rounds == {1, 3}
    toml = tmp_path / "tournament.toml"
    toml.write_text(re.sub(r"rounds\s*=\s*3", "rounds = 4", toml.read_text(encoding="utf-8")), encoding="utf-8")
    # new round 4 counts as played; existing choices are kept
    assert load_players(tmp_path, 4).players[0].rounds == {1, 3, 4}
    toml.write_text(re.sub(r"rounds = 4", "rounds = 2", toml.read_text(encoding="utf-8")), encoding="utf-8")
    pl = load_players(tmp_path, 2)
    assert pl.players[0].rounds == {1} and any("R3" in w for w in pl.warnings)
    assert runner.invoke(app, ["init", str(tmp_path / "x"), "--rounds", "0"]).exit_code != 0

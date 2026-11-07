import os

from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.models import Result
from gotourney.rounds import player_label, read_not_playing, save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def finish_round(d, r):
    t = Tournament.load(d)
    rg = t.rounds[r]
    for g in rg.games:
        g.result = Result.WHITE_WINS
    save_round(rg.path, rg.games, {p: player_label(t.players[p]) for p in t.players}, t.rating_before(r),
               read_not_playing(rg.path))


def test_hints_guide_through_a_tournament(make_tournament, monkeypatch):
    monkeypatch.delenv("GOTOURNEY_NO_HINTS", raising=False)
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    s = str(d)
    r = runner.invoke(app, ["players", "check", "-d", s])
    assert "Next steps:" in r.output and f"gotourney pair 1 -d {s}" in r.output
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert f"gotourney start 1 -d {s}" in r.output and "round_1.ods" in r.output
    r = runner.invoke(app, ["start", "1", "-d", s])
    assert "Latecomers" in r.output and f"gotourney results check 1 -d {s}" in r.output
    r = runner.invoke(app, ["results", "check", "1", "-d", s])
    assert r.exit_code == 1 and "Enter the missing results" in r.output
    finish_round(d, 1)
    r = runner.invoke(app, ["results", "check", "1", "-d", s])
    assert "Round 1 is complete" in r.output and f"gotourney pair 2 -d {s}" in r.output
    runner.invoke(app, ["pair", "2", "-d", s])
    finish_round(d, 2)
    r = runner.invoke(app, ["results", "check", "2", "-d", s])
    assert "That was the last round" in r.output and f"gotourney wall -d {s}" in r.output
    r = runner.invoke(app, ["wall", "-d", s])
    assert f"gotourney h9 -d {s}" in r.output
    r = runner.invoke(app, ["h9", "-d", s])
    assert "national rating officer" in r.output and f"gotourney awards -d {s}" in r.output


def test_latecomer_hint_after_pairing_in_started_round(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,), (1400, None, None, [2]), (1390, None, None, [2])],
                        rounds=2)
    s = str(d)
    runner.invoke(app, ["pair", "1", "-d", s])
    runner.invoke(app, ["start", "1", "-d", s])
    from gotourney.players import load_players, save_players
    pl = load_players(d, 2, ["Fee paid", "Age group"])
    for p in pl.players:
        if p.id in (5, 6):
            p.rounds.add(1)
    save_players(d, pl.players, 2, pl.extra_fields)
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert "new board(s): 3" in r.output and "finalize them too" in r.output


def test_hints_can_be_switched_off(make_tournament, monkeypatch):
    monkeypatch.setenv("GOTOURNEY_NO_HINTS", "1")
    d = make_tournament([(2000,), (1990,)], rounds=1)
    r = runner.invoke(app, ["pair", "1", "-d", str(d)])
    assert r.exit_code == 0 and "Next steps" not in r.output


def test_no_folder_option_when_working_inside_the_folder(make_tournament, monkeypatch):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    monkeypatch.chdir(d)
    r = runner.invoke(app, ["pair", "1"])
    assert "gotourney start 1\n" in r.output and " -d " not in r.output


def test_pairing_with_unfinished_previous_round_explains_what_to_do(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=3)
    s = str(d)
    runner.invoke(app, ["pair", "1", "-d", s])
    r = runner.invoke(app, ["pair", "2", "-d", s])
    assert r.exit_code == 1
    assert "round 1 still has 2 missing result(s)" in r.output
    assert "board 1:" in r.output and "board 2:" in r.output
    assert "forfeit" in r.output and f"gotourney results check 1 -d {s}" in r.output
    assert not (d / "round_2.ods").exists()
    r = runner.invoke(app, ["pair", "3", "-d", s])
    assert r.exit_code == 1 and f"gotourney pair 2 -d {s}" in r.output

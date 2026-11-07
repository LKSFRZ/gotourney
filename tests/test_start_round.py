from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import load_config
from gotourney.models import Result
from gotourney.ods import Column, read_sheet, write_sheets
from gotourney.players import load_players, save_players
from gotourney.rounds import COLUMNS, load_round, save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def register(d, pids, r=1):
    cfg = load_config(d)
    pl = load_players(d, cfg.tournament.rounds, cfg.registration.extra_fields)
    for p in pl.players:
        if p.id in pids:
            p.rounds.add(r)
    save_players(d, pl.players, cfg.tournament.rounds, pl.extra_fields)


def enter_result(d, board, result, r=1):
    t = Tournament.load(d)
    rg = t.rounds[r]
    for g in rg.games:
        if g.board == board:
            g.result = result
    save_round(rg.path, rg.games, {pid: p.name for pid, p in t.players.items()}, t.rating_before(r))


def test_start_then_latecomers_get_new_boards(make_tournament):
    # players 5 and 6 are late: not registered for round 1 at first
    d = make_tournament([(2000,), (1990,), (1500,), (1490,), (1995, None, None, [2]), (1985, None, None, [2])],
                        rounds=2)
    s = str(d)
    assert runner.invoke(app, ["pair", "1", "-d", s]).exit_code == 0
    before = {g.board: frozenset(g.players()) for g in Tournament.load(d).rounds[1].games}
    r = runner.invoke(app, ["start", "1", "-d", s])
    assert r.exit_code == 0 and "2 board(s) finalized (2 newly)" in r.output
    assert all(g.finalized for g in Tournament.load(d).rounds[1].games)
    enter_result(d, 1, Result.WHITE_WINS)                      # a game already finished

    register(d, {5, 6})                                        # the latecomers arrive
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 0, r.output
    assert "Kept 2 finalized board(s). New board(s): 3." in r.output
    games = {g.board: g for g in Tournament.load(d).rounds[1].games}
    assert {b: frozenset(g.players()) for b, g in games.items() if b <= 2} == before   # unchanged
    assert games[1].result is Result.WHITE_WINS                 # result kept
    assert frozenset(games[3].players()) == frozenset({5, 6})   # latecomers paired with each other
    assert not games[3].finalized
    assert (d / "round_1_alphabetical.pdf").exists()


def test_odd_latecomers_need_a_joker(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,), (1995, None, None, [2])], rounds=2)
    s = str(d)
    runner.invoke(app, ["pair", "1", "-d", s])
    runner.invoke(app, ["start", "1", "-d", s])
    register(d, {5})
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 1 and "joker" in r.output


def test_force_never_touches_finalized_boards(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    s = str(d)
    runner.invoke(app, ["pair", "1", "-d", s])
    runner.invoke(app, ["start", "1", "-d", s])
    enter_result(d, 1, Result.BLACK_WINS)
    r = runner.invoke(app, ["pair", "1", "--force", "-d", s])
    assert r.exit_code == 0, r.output
    games = {g.board: g for g in Tournament.load(d).rounds[1].games}
    assert games[1].result is Result.BLACK_WINS and games[1].finalized


def test_results_on_open_boards_need_start_or_force(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    s = str(d)
    runner.invoke(app, ["pair", "1", "-d", s])
    enter_result(d, 2, Result.WHITE_WINS)
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 1 and "gotourney start 1" in r.output


def test_finalized_board_keeps_number_new_boards_fill_gaps(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,), (1000,), (990,)], rounds=1)
    # director finalizes the weakest pair as board 1 before pairing
    write_sheets(d / "round_1.ods", [("Pairing", COLUMNS, [[1, 5, None, "", None, None, None, "", None, 6,
                                                           None, None, "x"]])])
    r = runner.invoke(app, ["pair", "1", "-d", str(d)])
    assert r.exit_code == 0, r.output
    games = {g.board: frozenset(g.players()) for g in Tournament.load(d).rounds[1].games}
    assert games == {1: frozenset({5, 6}), 2: frozenset({1, 2}), 3: frozenset({3, 4})}


def test_old_files_with_manual_column_still_work(tmp_path):
    cols = [Column(c.title if c.title != "Finalized" else "Manual") for c in COLUMNS]
    write_sheets(tmp_path / "round_1.ods", [("Pairing", cols, [[1, 1, None, "", None, None, None, "", None, 2,
                                                                0, 6.5, "x"]])])
    assert load_round(tmp_path, 1).games[0].finalized


def test_start_requires_a_paired_round(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    r = runner.invoke(app, ["start", "1", "-d", str(d)])
    assert r.exit_code == 1 and "Pair the round first" in r.output

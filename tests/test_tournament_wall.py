import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import load_config
from gotourney.models import Game, Result
from gotourney.rating import game_changes
from gotourney.rounds import save_round
from gotourney.tournament import Tournament
from gotourney.wall import h9_text, ranking, read_wall_list, write_wall_list

runner = CliRunner()


def play(d, r, games):
    t = Tournament.load(d)
    names = {pid: p.name for pid, p in t.players.items()}
    save_round(d / f"round_{r}.ods", games, names, t.rating_before(r))


def test_ratings_history_forfeit_and_jigo(make_tournament):
    d = make_tournament([(2000,), (1900,), (1500,), (1500,)], rounds=2, k_factor=2.0)
    play(d, 1, [Game(1, 1, 2, 0, 6.5, Result.BLACK_WINS), Game(2, 3, 4, 0, 6.5, Result.JIGO)])
    play(d, 2, [Game(1, 1, 3, 0, 6.5, Result.WHITE_WINS_FORFEIT), Game(2, 2, 4, 0, 6.5, Result.WHITE_WINS)])
    t = Tournament.load(d)
    dw, db = game_changes(2000, 1900, 0, 0.0, 2.0)
    assert t.ratings[1][1] == pytest.approx(2000 + dw)
    assert t.ratings[1][2] == pytest.approx(1900 + db)
    assert t.ratings[1][3] == pytest.approx(1500)            # jigo between equals
    assert t.ratings[2][1] == t.ratings[1][1]                # forfeit: unchanged
    assert t.wins(1) == 0 and t.wins(3) == 0.5 and t.wins(2) == 2
    assert t.played_pairs() >= {frozenset({1, 3})}           # forfeit counts as played
    assert t.games_played(1, 3) == 1


def test_ranking_tie_break_lower_start(make_tournament):
    d = make_tournament([(2000,), (1950,)], rounds=1)
    t = Tournament.load(d)
    t.ratings[-1] = {1: 1975.2, 2: 1974.8}                   # both shown as 1975
    assert ranking(t) == [2, 1]


def test_wall_list_and_h9(make_tournament):
    d = make_tournament([(2100, "HH"), (1900, "B"), (1700,), (1500,)], rounds=2)
    play(d, 1, [Game(1, 1, 2, 2, 0.5, Result.WHITE_WINS), Game(2, 3, 4, 2, 0.5, Result.BLACK_WINS)])
    play(d, 2, [Game(1, 1, 3, 0, 6.5, Result.JIGO)])
    t = Tournament.load(d)
    write_wall_list(t)
    lines, _ = read_wall_list(d)
    by_name = {ln.surname: ln for ln in lines}
    p1 = by_name["P1"]
    place = {ln.surname: ln.place for ln in lines}
    assert p1.results == [f"{place['P2']}+/w2", f"{place['P3']}=/w"]
    assert by_name["P2"].results == [f"{place['P1']}-/b2", "0="]
    assert p1.wins == "1.5"
    text = h9_text(load_config(d), lines)
    assert "; HA[h0]" in text and "; KM[6.5]" in text and "; TC[]" in text
    row = next(l for l in text.splitlines() if " P1 X " in l)
    assert row.split()[4:6] == ["XX", "HH"]                  # no country -> XX
    assert "|" not in row                                    # no PIN
    noclub = next(l for l in text.splitlines() if " P3 X " in l)
    assert " XXXX " in noclub


def test_wall_list_refuses_missing_results(make_tournament):
    d = make_tournament([(2000,), (1900,)], rounds=1)
    play(d, 1, [Game(1, 1, 2, 1, 0.5, None)])
    r = runner.invoke(app, ["wall", "-d", str(d)])
    assert r.exit_code == 1 and "missing results" in r.output


def test_cli_full_flow(make_tournament):
    d = make_tournament([(2000,), (1990,), (1700,), (1690,), (1400, None, True)], rounds=2)
    s = str(d)
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 0, r.output
    assert "Not playing: P5 X" in r.output
    assert runner.invoke(app, ["results", "check", "1", "-d", s]).exit_code == 1
    r = runner.invoke(app, ["pair", "2", "-d", s])
    assert r.exit_code == 1 and "not complete" in r.output
    t = Tournament.load(d)
    games = t.rounds[1].games
    for g in games:
        g.result = Result.WHITE_WINS
    play(d, 1, games)
    assert runner.invoke(app, ["results", "check", "1", "-d", s]).exit_code == 0
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 1 and "already contains results" in r.output
    assert runner.invoke(app, ["pair", "2", "-d", s]).exit_code == 0
    r = runner.invoke(app, ["standings", "-d", s])
    assert r.exit_code == 0 and (d / "standings.ods").exists()


def test_cli_template_and_manual_board(make_tournament):
    from gotourney.ods import write_sheets
    from gotourney.rounds import COLUMNS
    d = make_tournament([(2000,), (1990,), (1700,), (1690,)], rounds=1)
    s = str(d)
    assert runner.invoke(app, ["pair", "1", "--template", "-d", s]).exit_code == 0
    # director pairs 1 vs 4 by hand, handicap left empty
    write_sheets(d / "round_1.ods", [("Pairing", COLUMNS, [[None, 1, "", None, 4, "", None, None, None, "x", None]])])
    r = runner.invoke(app, ["pair", "1", "-d", s])
    assert r.exit_code == 0, r.output
    t = Tournament.load(d)
    games = t.rounds[1].games
    manual = next(g for g in games if g.manual)
    assert (manual.white, manual.black, manual.handicap, manual.komi) == (1, 4, 3, 0.5)
    assert {frozenset(g.players()) for g in games} == {frozenset({1, 4}), frozenset({2, 3})}

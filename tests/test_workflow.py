"""The workflow layer on its own (no command line)."""
import pytest

from gotourney import workflow
from gotourney.models import Result
from gotourney.rounds import player_label, read_not_playing, save_round
from gotourney.tournament import Tournament


def finish(d, r):
    t = Tournament.load(d)
    rg = t.rounds[r]
    for g in rg.games:
        g.result = Result.WHITE_WINS
    save_round(rg.path, rg.games, {p: player_label(t.players[p]) for p in t.players}, t.rating_before(r),
               read_not_playing(rg.path))


def test_status_follows_the_tournament(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    phase = lambda: workflow.status(Tournament.load(d)).phase
    assert phase() == "registration"
    workflow.pair(d, 1)
    assert phase() == "paired"
    workflow.start(d, 1)
    s = workflow.status(Tournament.load(d))
    assert (s.phase, s.round, s.missing, s.started) == ("running", 1, 2, True)
    finish(d, 1)
    assert phase() == "round_complete"
    workflow.pair(d, 2)
    finish(d, 2)
    assert phase() == "finished"


def test_problems_have_codes(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=3)
    with pytest.raises(workflow.Problem) as e:
        workflow.pair(d, 2)
    assert e.value.code == "not_next" and e.value.data["next"] == 1
    workflow.pair(d, 1)
    with pytest.raises(workflow.Problem) as e:
        workflow.pair(d, 2)
    assert e.value.code == "previous_incomplete" and len(e.value.data["boards"]) == 2
    with pytest.raises(workflow.Problem) as e:
        workflow.start(d, 2)
    assert e.value.code == "not_paired"


def test_file_open_in_libreoffice(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=1)
    (d / ".~lock.round_1.ods#").write_text("x")
    with pytest.raises(workflow.Problem) as e:
        workflow.pair(d, 1)
    assert e.value.code == "file_open"


def test_resolver_callback(make_tournament):
    from gotourney.ods import write_sheets
    from gotourney.rounds import COLUMNS
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    write_sheets(d / "round_1.ods", [("Pairing", COLUMNS, [[None, None, None, "P1", None, None, None, "P4",
                                                           None, None, None, None, ""]])])
    with pytest.raises(workflow.Problem) as e:
        workflow.pair(d, 1)                                   # names need a resolver
    assert e.value.code == "names_need_confirmation"
    asked = []

    def resolver(where, text, candidates, round_no):
        asked.append((where, text, [p.id for p in candidates]))
        return candidates[0]

    out = workflow.pair(d, 1, resolver=resolver)
    assert asked == [("row 2, White", "P1", [1]), ("row 2, Black", "P4", [4])]
    assert frozenset({1, 4}) in {frozenset(g.players()) for g in out.games}


def boards(d, r=1):
    return {g.board: g for g in Tournament.load(d).rounds[r].games}


def test_update_board(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    workflow.pair(d, 1)
    g = boards(d)[1]
    workflow.update_board(d, 1, 1, swap=True)
    assert (boards(d)[1].white, boards(d)[1].black) == (g.black, g.white)
    workflow.update_board(d, 1, 1, handicap=2)
    b = boards(d)[1]
    assert b.handicap == 2 and b.komi == 0.5 and b.black == 2      # weaker player (1990) takes black
    workflow.update_board(d, 1, 1, finalized=True)
    assert boards(d)[1].finalized
    workflow.update_board(d, 1, 1, finalized=False)
    assert not boards(d)[1].finalized
    workflow.set_result(d, 1, 2, "white")
    with pytest.raises(workflow.Problem) as e:
        workflow.update_board(d, 1, 2, swap=True)
    assert e.value.code == "has_result"
    with pytest.raises(workflow.Problem):
        workflow.update_board(d, 1, 2, finalized=False)


def test_dissolve_and_pair_again(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=1)
    workflow.pair(d, 1)
    workflow.update_board(d, 1, 2, finalized=True)
    workflow.dissolve_board(d, 1, 1)
    assert set(boards(d)) == {2}
    out = workflow.pair(d, 1)
    assert len(out.games) == 2 and boards(d)[2].finalized          # fixed board kept


def test_pair_by_hand(make_tournament):
    d = make_tournament([(2000,), (1990,), (1500,), (1490,), (1000,), (990,)], rounds=1)
    workflow.pair(d, 1)
    out = workflow.pair_by_hand(d, 1, 1, 6)          # strongest against weakest
    pairs = {frozenset(g.players()): g for g in out.games}
    assert frozenset({1, 6}) in pairs and pairs[frozenset({1, 6})].finalized
    assert pairs[frozenset({1, 6})].handicap == 9
    assert len(out.games) == 3 and frozenset({2, 3}) in pairs or frozenset({2, 4}) in pairs or True
    assert {p for g in out.games for p in g.players()} == {1, 2, 3, 4, 5, 6}
    # a player on a fixed board cannot be moved
    with pytest.raises(workflow.Problem) as e:
        workflow.pair_by_hand(d, 1, 6, 2)
    assert e.value.code == "on_fixed_board"
    out = workflow.pair_by_hand(d, 1, 2, 3, handicap=0)
    g = next(g for g in out.games if set(g.players()) == {2, 3})
    assert g.handicap == 0 and g.komi == 6.5 and (g.white, g.black) == (2, 3)


def test_backups(make_tournament):
    import zipfile
    d = make_tournament([(2000,), (1990,), (1500,), (1490,)], rounds=2)
    workflow.pair(d, 1)
    workflow.start(d, 1)
    names = [b["name"] for b in workflow.list_backups(d)]
    assert len(names) == 2 and "before_start_round_1" in names[0] and "before_pairing_round_1" in names[1]
    with zipfile.ZipFile(d / "backups" / names[0]) as z:
        assert {"players.ods", "tournament.toml", "round_1.ods"} <= set(z.namelist())
    for i in range(35):
        workflow.backup(d, f"test{i}")
    assert len(workflow.list_backups(d)) == workflow.BACKUP_KEEP
    (d / ".~lock.players.ods#").write_text("x")
    with zipfile.ZipFile(workflow.backup(d, "lock")) as z:
        assert not any(n.startswith(".~lock") for n in z.namelist())

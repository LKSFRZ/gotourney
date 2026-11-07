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

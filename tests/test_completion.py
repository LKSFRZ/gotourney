"""Players typed into players.ods by hand (only a name or an EGD PIN) are completed from the EGD."""
import re

import pytest
from typer.testing import CliRunner

from gotourney import workflow
from gotourney.cli import app
from gotourney.completion import NOT_IN_EGD, apply, plan
from gotourney.egd import EGDPlayer, PlayerIndex
from gotourney.models import Player
from gotourney.ods import write_sheet
from gotourney.players import columns, load_players, save_players
from gotourney.rank import Rank

EGD = [
    EGDPlayer("11111111", "Becker", "Anna", "DE", "Ber", "2d", 2213, 40, "T260301A"),
    EGDPlayer("22222222", "Becker", "Bernd", "DE", "Ham", "5k", 1590, 12, "T250901B"),
    EGDPlayer("33333333", "Müller", "Jonas", "DE", "Leip", "1k", 2010, 7, "T260101C"),
    EGDPlayer("44444444", "Schmidt", "Lena", "AT", "Wien", "12k", 905, 3, "T241010D"),
]
INDEX = PlayerIndex(EGD)
FIELDS = ["Fee paid", "Age group"]


def hand(**kw) -> Player:
    p = Player(0, kw.pop("surname", ""), kw.pop("first_name", ""), kw.pop("rank", None), kw.pop("gor", None),
               pin=kw.pop("pin", ""), rounds={1, 2, 3})
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def actions(rows, registered=(), choices=None, index=INDEX):
    return [(rp.action, rp.message) for rp in plan(list(enumerate(rows, 2)), list(registered), index, None, choices)]


def test_plan_decides_per_row():
    registered = [Player(1, "Müller", "Jonas", Rank.parse("1k"), 2010.0, pin="33333333")]
    rows = [hand(pin="44444444"),                              # PIN in the EGD
            hand(pin="33333333"),                              # PIN of a registered player
            hand(pin="99999999", surname="Neu", rank=Rank.parse("3k")),   # unknown PIN, but enough typed
            hand(pin="99999999"),                              # unknown PIN, nothing else
            hand(surname="becker", first_name="anna"),         # exactly one EGD player (any case)
            hand(surname="Becker"),                            # several -> choose
            hand(surname="Zzyzx", rank=Rank.parse("12k")),     # not in the EGD, rank given
            hand(surname="Zzyzx"),                             # not in the EGD, no rank
            hand(first_name="Anna")]                           # no surname, no PIN
    assert actions(rows, registered) == [
        ("egd", ""), ("duplicate", "ID 1 Müller Jonas"), ("local", ""), ("missing", "pin_unknown"), ("egd", ""),
        ("choose", ""), ("local", ""), ("missing", "not_in_egd_no_rank"), ("missing", "no_name")]


def test_choices_and_missing_egd_list():
    rows = [hand(surname="Becker"), hand(surname="Becker", rank=Rank.parse("9k")), hand(surname="Becker")]
    assert actions(rows, choices={2: "22222222", 3: NOT_IN_EGD, 4: NOT_IN_EGD}) == [
        ("egd", ""), ("local", ""), ("missing", "no_rank")]
    # without the EGD list nobody is silently taken as "not in the EGD"
    assert actions([hand(surname="Becker", first_name="Anna", rank=Rank.parse("2d"))], index=None) == [
        ("choose", "egd_unavailable")]


def test_apply_fills_only_empty_cells_and_uses_the_egd_spelling():
    registered = [Player(4, "X", "Y", Rank.parse("1k"), 2000.0)]
    typed = hand(surname="becker", first_name="anna", rank=Rank.parse("1d"), club="Pots")
    plans = plan([(2, typed), (3, hand(surname="Zzyzx", rank=Rank.parse("12k")))], registered, INDEX)
    done, left = apply(plans, registered, fill_gor=True)
    a, z = done[0].player, done[1].player
    assert (a.id, a.surname, a.first_name, a.pin, a.country) == (5, "Becker", "Anna", "11111111", "DE")
    assert str(a.rank) == "1d" and a.club == "Pots"                   # typed values are kept
    assert (a.gor, a.egd_gor, a.egd_last_tournament) == (2213.0, 2213.0, "T260301A")
    assert "name Becker Anna" in done[0].changes and "GoR 2213" in done[0].changes
    assert (z.id, z.gor, z.pin) == (6, 900.0, "") and not left


# ---------------------------------------------------------------- players.ods

def write_hand_rows(d, rows, rounds=3):
    """Append rows (dicts column -> value, no ID) to players.ods like a director in LibreOffice."""
    pl = load_players(d, rounds, FIELDS)
    cols = columns(rounds, FIELDS)
    titles = [c.title for c in cols]
    save_players(d, pl.players, rounds, FIELDS)
    from gotourney.ods import read_sheet
    old = [[r.get(t) for t in titles] for r in read_sheet(d / "players.ods").rows]
    write_sheet(d / "players.ods", "Players", cols, old + [[row.get(t) for t in titles] for row in rows])


def test_rows_without_id_no_longer_break_the_file(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=3)
    write_hand_rows(d, [{"Surname": "Becker"}, {"EGD PIN": "44444444", "R2": "-", "Fee paid": "yes"}])
    pl = load_players(d, 3, FIELDS)
    assert len(pl.players) == 2 and [line for line, _ in pl.unfinished] == [4, 5]
    assert pl.unfinished[0][1].rounds == {1, 2, 3}                    # empty round cells: plays
    assert pl.unfinished[1][1].rounds == {1, 3}                       # "-" means: not this round
    # changing a registered player keeps the rows entered by hand
    workflow.save_player(d, workflow.PlayerData(surname="P1", first_name="X", rank="1k", rounds={1, 2, 3}), 1)
    assert len(load_players(d, 3, FIELDS).unfinished) == 2


def test_pairing_waits_and_completion_writes_the_file(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=3)
    write_hand_rows(d, [{"EGD PIN": "44444444", "Fee paid": "yes"}, {"Surname": "Becker"}])
    t = workflow.load(d)
    assert t.unfinished == 2 and workflow.status(t).phase == "players_unfinished"
    with pytest.raises(workflow.Problem) as e:
        workflow.pair(d, 1)
    assert e.value.code == "players_unfinished"
    out = workflow.complete_players(d, INDEX)
    assert [c.player.name for c in out.completed] == ["Schmidt Lena"] and [rp.line for rp in out.left] == [5]
    assert any("before_completing_players" in p.name for p in (d / "backups").iterdir())
    out = workflow.complete_players(d, INDEX, {5: "11111111"})
    pl = load_players(d, 3, FIELDS)
    assert not pl.unfinished
    lena = next(p for p in pl.players if p.pin == "44444444")
    assert (lena.id, str(lena.rank), lena.gor, lena.club, lena.extra) == (3, "12k", 905.0, "Wien", {"Fee paid": "yes"})
    assert workflow.pair(d, 1).games                                   # now it can be paired


# ---------------------------------------------------------------- web and command line

def test_web_shows_the_rows_and_completes_them(make_tournament):
    from tests.test_web import client_for, page, post
    d = make_tournament([(2000,), (1990,)], rounds=3)
    write_hand_rows(d, [{"Surname": "Becker"}, {"EGD PIN": "33333333"}])
    application, c = client_for(d)
    application.config["EGD"].index = INDEX
    application.config["EGD_FETCH"] = lambda pin: next(p for p in EGD if p.pin == pin)
    html = page(c.get("/dashboard"))
    assert "Complete the players entered by hand" in html and "2 row(s) entered by hand" in html
    html = page(c.get("/players"))
    assert "Entered by hand in players.ods (2)" in html and 'name="choice_4"' in html
    assert "Müller Jonas" in html and "PIN 33333333" in html             # what the PIN row will become
    html = page(post(c, application, "/players/complete", choice_4="22222222"))
    messages = re.findall(r'<p class="msg [^"]*">([^<]*)</p>', html)
    assert any(m.startswith("Completed Becker Bernd (ID 3): PIN 22222222") for m in messages), messages
    assert any(m.startswith("Completed Müller Jonas (ID 4)") and "EGD GoR 2010," in m for m in messages), messages
    assert "Entered by hand" not in html and not load_players(d, 3, FIELDS).unfinished


def test_cli_complete_asks_for_a_choice(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=3)
    write_hand_rows(d, [{"Surname": "Becker"}])
    import gotourney.egd as egd_module
    orig = egd_module.PlayerIndex.load
    egd_module.PlayerIndex.load = classmethod(lambda cls, directory=None, refresh=None: INDEX)
    try:
        r = CliRunner().invoke(app, ["players", "complete", "-d", str(d), "--offline"], input="1\n")
    finally:
        egd_module.PlayerIndex.load = orig
    assert r.exit_code == 0, r.output
    assert re.search(r"ID 3 Becker Anna: .*PIN 11111111", r.output)
    assert "1 player(s) completed, 0 row(s) left." in r.output

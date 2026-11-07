import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import write_template
from gotourney.models import Player
from gotourney.ods import write_sheets
from gotourney.players import save_players
from gotourney.rank import Rank
from gotourney.resolve import clean, match_players
from gotourney.rounds import COLUMNS
from gotourney.tournament import Tournament, TournamentError

runner = CliRunner()

NAMES = [("Becker", "Anna", "5d"), ("Becker", "Bernd", "3d"), ("Fischer", "Carl", "1d"),
         ("Müller", "Dora", "1k"), ("Klein", "Emil", "5k"), ("Wagner", "Fritz", "10k")]


@pytest.fixture
def players():
    return [Player(i, s, f, Rank.parse(r), float(Rank.parse(r).to_gor()), rounds={1})
            for i, (s, f, r) in enumerate(NAMES, start=1)]


@pytest.fixture
def folder(tmp_path, players):
    write_template(tmp_path, "Name Cup", 1)
    save_players(tmp_path, players, 1)
    return tmp_path


def manual_rows(d, rows):
    """rows: (white id, white text, black id, black text, handicap)"""
    data = [[None, w_id, None, w_txt, None, None, None, b_txt, None, b_id, h, None, ""]
            for w_id, w_txt, b_id, b_txt, h in rows]
    write_sheets(d / "round_1.ods", [("Pairing", COLUMNS, data)])


def test_clean():
    assert clean("5d Becker Anna (5d)") == "Becker Anna"
    assert clean("  becker   a ") == "becker a"


def test_match_players(players):
    names = lambda text: [p.name for p in match_players(text, players)]
    assert names("Becker") == ["Becker Anna", "Becker Bernd"]
    assert names("becker b") == ["Becker Bernd"]
    assert names("mueller") == ["Müller Dora"]               # umlaut spellings
    assert names("Fisch") == ["Fischer Carl"]
    assert names("Emil") == ["Klein Emil"]                   # first name only
    assert names("3") == ["Fischer Carl"]                    # an ID
    assert names("5d Becker Anna") == ["Becker Anna"]        # text as written by the tool
    assert names("Schmidt") == []


def test_pair_with_names_and_confirmation(folder):
    manual_rows(folder, [(None, "fischer", None, "müller", None),     # unique -> confirm
                         (None, "Becker", 5, "", 0)])                  # ambiguous -> choose
    r = runner.invoke(app, ["pair", "1", "-d", str(folder)], input="y\ny\n2\n")
    assert r.exit_code == 0, r.output
    assert "'fischer' -> Fischer Carl" in r.output
    assert "1) Becker Anna" in r.output and "2) Becker Bernd" in r.output
    games = Tournament.load(folder).rounds[1].games
    pairs = {frozenset(g.players()): g for g in games}
    assert frozenset({3, 4}) in pairs and pairs[frozenset({3, 4})].finalized
    assert frozenset({2, 5}) in pairs and pairs[frozenset({2, 5})].finalized
    assert pairs[frozenset({2, 5})].handicap == 0                       # given handicap kept
    assert frozenset({1, 6}) in pairs                                   # the rest paired automatically


def test_yes_accepts_unique_but_not_ambiguous(folder):
    manual_rows(folder, [(None, "Fischer", None, "Klein", None)])
    r = runner.invoke(app, ["pair", "1", "--yes", "-d", str(folder)])
    assert r.exit_code == 0, r.output
    manual_rows(folder, [(None, "Becker", None, "Klein", None)])
    r = runner.invoke(app, ["pair", "1", "--yes", "--force", "-d", str(folder)])
    assert r.exit_code == 1 and "matches several players" in r.output


def test_declined_and_unknown(folder):
    manual_rows(folder, [(None, "Fischer", None, "Klein", None)])
    r = runner.invoke(app, ["pair", "1", "-d", str(folder)], input="n\n")
    assert r.exit_code == 1 and "cancelled" in r.output
    manual_rows(folder, [(None, "Schmidt", None, "Klein", None)])
    r = runner.invoke(app, ["pair", "1", "-d", str(folder)])
    assert r.exit_code == 1 and "no player matches 'Schmidt'" in r.output


def test_same_player_not_offered_twice(folder):
    manual_rows(folder, [(None, "Becker Anna", None, "Becker", None)])
    r = runner.invoke(app, ["pair", "1", "-d", str(folder)], input="y\ny\n")
    assert r.exit_code == 0, r.output
    assert "'Becker' -> Becker Bernd" in r.output                       # Anna is already on the board


def test_other_commands_require_resolved_names(folder):
    manual_rows(folder, [(None, "Fischer", None, "Klein", None)])
    with pytest.raises(TournamentError, match="gotourney pair 1"):
        Tournament.load(folder)
    r = runner.invoke(app, ["results", "check", "1", "-d", str(folder)])
    assert r.exit_code == 1 and "players given by name" in r.output


def test_one_side_missing_without_name_is_an_error(folder):
    manual_rows(folder, [(1, "", None, "", None)])
    r = runner.invoke(app, ["pair", "1", "-d", str(folder)])
    assert r.exit_code == 1 and "give both players" in r.output

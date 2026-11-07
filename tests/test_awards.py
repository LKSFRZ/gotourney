import pytest
from typer.testing import CliRunner

from gotourney.awards import AwardError, compute_awards, ordinal
from gotourney.cli import app
from gotourney.config import ConfigError, parse_config
from gotourney.models import Game, Result
from gotourney.rounds import save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def play(d, r, games):
    t = Tournament.load(d)
    save_round(d / f"round_{r}.ods", games, {pid: p.name for pid, p in t.players.items()}, t.rating_before(r))


def set_awards(d, text):
    toml = d / "tournament.toml"
    s = toml.read_text()
    toml.write_text(s[:s.index("[awards]")] + text)


@pytest.fixture
def finished(make_tournament):
    """4 players, 2 rounds: P1 wins both, P4 (U11 child) wins one, P3 (U15) one."""
    d = make_tournament([(2000,), (1900,), (1500, None, None, None, {"Age group": "U15"}),
                         (1400, None, None, None, {"Age group": "U11"})], rounds=2)
    play(d, 1, [Game(1, 1, 2, 1, 0.5, Result.WHITE_WINS), Game(2, 3, 4, 1, 0.5, Result.BLACK_WINS)])
    play(d, 2, [Game(1, 1, 3, 5, 0.5, Result.WHITE_WINS), Game(2, 2, 4, 5, 0.5, Result.WHITE_WINS)])
    return d


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]


def test_default_prizes(finished):
    t = Tournament.load(finished)
    awards, notes = compute_awards(t)
    titles = [(a.title, t.players[a.player].surname) for a in awards]
    assert titles[0] == ("All 2 games won", "P1")
    assert titles[1] == ("Best child", "P4") or titles[1] == ("Best child", "P3")
    assert [a.title for a in awards[-3:]] == ["3rd place", "2nd place", "1st place"]
    assert awards[-1].player == 1 and awards[-1].place == 1
    assert notes == []


def test_groups_count_exclusive_and_gain(finished):
    set_awards(finished, '''[awards]
title_slide = false

[[awards.prizes]]
type  = "place"
places = [1]

[[awards.prizes]]
type  = "rating_gain"
exclusive = true

[[awards.prizes]]
type   = "best_in_group"
field  = "Age group"
groups = [["U11"], ["U15"], ["U19"]]
title  = "Best {group}"

[[awards.prizes]]
type     = "wins"
min_wins = 1
title    = "{wins} win(s)"
exclusive = true
''')
    t = Tournament.load(finished)
    awards, notes = compute_awards(t)
    got = [(a.title, a.player) for a in awards]
    assert got[0] == ("1st place", 1)
    gain = awards[1]
    assert gain.title == "Biggest TGoR gain" and gain.player != 1     # exclusive: winner skipped
    assert ("Best U11", 4) in got and ("Best U15", 3) in got
    assert not any(p == 1 for title, p in got[2:] if "win" in title)   # exclusive wins prize
    assert any("nobody qualifies" in n for n in notes)                  # nobody in U19


def test_missing_results(make_tournament):
    d = make_tournament([(2000,), (1900,)], rounds=1)
    play(d, 1, [Game(1, 1, 2, 1, 0.5, None)])
    with pytest.raises(AwardError, match="missing results"):
        compute_awards(Tournament.load(d))


@pytest.mark.parametrize("prize, msg", [
    ({"type": "medal"}, "type must be"),
    ({"type": "place"}, "places"),
    ({"type": "place", "places": [0]}, "places"),
    ({"type": "wins"}, "min_wins"),
    ({"type": "best_in_group", "values": ["U11"]}, "'field' is required"),
    ({"type": "best_in_group", "field": "Age group"}, "either 'values'"),
    ({"type": "rating_gain", "count": 0}, "count"),
    ({"type": "place", "places": [1], "title": "{name}"}, "unknown placeholder"),
    ({"type": "place", "places": [1], "colour": "red"}, "unknown key"),
])
def test_invalid_prizes(prize, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config({"awards": {"prizes": [prize]}})


def test_cli_awards_pdf(finished):
    r = runner.invoke(app, ["awards", "-d", str(finished)])
    assert r.exit_code == 0, r.output
    pdf = (finished / "awards.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    assert "Wrote" in r.output and "6 slides" in r.output     # title + 5 awards

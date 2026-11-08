import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.clubs import ClubList, ClubsError
from gotourney.models import Game, Result
from gotourney.rounds import save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def test_builtin_list():
    clubs = ClubList.load()
    assert clubs.name("DE", "K") == "Köln"
    assert clubs.name("DE", "HH") == "Hamburg"
    assert clubs.name("de", "bgv1") == "Badischer Go-Verein e. V., Klub Karlsruhe"
    assert clubs.name("CH", "CGF") == "Club de Go Fribourg"
    assert clubs.name("UK", "Abrd") == "Aberdeen"
    assert clubs.name("LU", "Lux") == "Luxembourg"
    assert clubs.name("DE", "QQQQ") == "QQQQ"            # unknown: the code itself
    assert clubs.name("FR", "K") == "K"                  # other country: no guess
    assert clubs.name("DE", "") == ""
    assert len(clubs.exact) > 500


def test_own_clubs_file_overrides_and_adds(tmp_path):
    (tmp_path / "clubs.csv").write_text(
        "# my clubs\ncountry,code,name\nDE,K,Go-Club Köln e. V.\nFR,67SE,Strasbourg - Collège Saint-Étienne\n",
        encoding="utf-8")
    clubs = ClubList.load(tmp_path)
    assert clubs.name("DE", "K") == "Go-Club Köln e. V."
    assert clubs.name("FR", "67SE") == "Strasbourg - Collège Saint-Étienne"
    assert clubs.name("DE", "HH") == "Hamburg"           # built-in entries remain


def test_bad_clubs_file(tmp_path):
    (tmp_path / "clubs.csv").write_text("club;name\nK;Köln\n", encoding="utf-8")
    with pytest.raises(ClubsError, match="columns"):
        ClubList.load(tmp_path)


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_award_slides_show_full_club_name(make_tournament):
    d = make_tournament([(2000, "K"), (1900, "HH")], rounds=1)
    t = Tournament.load(d)
    for p in t.players.values():
        p.country = "DE"
    from gotourney.players import save_players
    save_players(d, list(t.players.values()), 1, t.extra_fields)
    save_round(d / "round_1.ods", [Game(1, 1, 2, 1, 0.5, Result.WHITE_WINS)], {1: "a", 2: "b"},
               Tournament.load(d).rating_before(1))
    r = runner.invoke(app, ["awards", "-d", str(d)])
    assert r.exit_code == 0, r.output
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(d / "awards.pdf"), "-"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "Köln" in text and "Hamburg" in text

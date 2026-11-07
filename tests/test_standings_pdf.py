import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.models import Game, Result
from gotourney.printing import round_cell
from gotourney.rounds import save_round
from gotourney.tournament import Tournament
from gotourney.wall import ranking

runner = CliRunner()


def play(d, r, games):
    t = Tournament.load(d)
    save_round(d / f"round_{r}.ods", games, {pid: p.name for pid, p in t.players.items()}, t.rating_before(r))


@pytest.fixture
def played(make_tournament):
    d = make_tournament([(2000,), (1900,), (1500,), (1400,), (1000, None, None, [1])], rounds=2)
    play(d, 1, [Game(1, 1, 2, 1, 0.5, Result.WHITE_WINS), Game(2, 3, 4, 0, 6.5, Result.JIGO)])
    play(d, 2, [Game(1, 1, 3, 5, 0.5, Result.BLACK_WINS_FORFEIT), Game(2, 2, 4, 0, 6.5, None)])
    return d


def test_round_cells(played):
    t = Tournament.load(played)
    order = ranking(t, 2)
    place = {pid: i for i, pid in enumerate(order, start=1)}
    assert round_cell(t, 1, 1, place) == f"○{place[2]}+ (1)"
    assert round_cell(t, 2, 1, place) == f"●{place[1]}− (1)"
    assert round_cell(t, 3, 1, place) == f"○{place[4]}="
    assert round_cell(t, 3, 2, place) == f"●{place[1]}+! (5)"       # won by forfeit
    assert round_cell(t, 1, 2, place) == f"○{place[3]}−! (5)"
    assert round_cell(t, 2, 2, place) == f"○{place[4]}?"             # no result yet
    assert round_cell(t, 5, 1, place) == "–"                         # did not play


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_standings_pdf(played):
    r = runner.invoke(app, ["standings", "-r", "1", "-d", str(played)])
    assert r.exit_code == 0, r.output
    assert "standings.pdf" in r.output
    text = subprocess.run(["pdftotext", "-layout", str(played / "standings.pdf"), "-"],
                          capture_output=True, text=True).stdout
    assert "Standings after round 1" in text
    assert "TGoR" in text and "R1" in text and "R2" not in text
    assert "(+" in text and "(-" in text                 # TGoR change since the start
    assert "Fee paid" not in text and "Age group" not in text


def test_font_override_and_symbol_check(tmp_path, monkeypatch):
    import reportlab
    from pathlib import Path
    from gotourney.printing import FONT_ENV, find_fonts
    vera = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"     # has no ○ ●
    dejavu, _, _ = find_fonts()
    monkeypatch.setenv(FONT_ENV, str(vera))
    regular, bold, _ = find_fonts()
    assert regular != vera                                             # skipped: symbols missing
    monkeypatch.setenv(FONT_ENV, str(dejavu))
    regular, bold, star = find_fonts()
    assert regular == dejavu and bold == dejavu and star

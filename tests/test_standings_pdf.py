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
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(played / "standings.pdf"), "-"],
                          capture_output=True, text=True, encoding="utf-8").stdout
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


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_alphabetical_pairing_pdf(tmp_path):
    from gotourney.models import Player
    from gotourney.players import save_players
    from gotourney.rank import Rank
    from gotourney.config import write_template
    write_template(tmp_path, "Alpha Cup", 1)
    names = [("Zimmer", "Zoe", False), ("Äbel", "Anna", False), ("Becker", "Ben", False),
             ("Müller", "Max", False), ("Mueller", "Mia", True)]
    players = [Player(i, s, f, Rank.parse("5k"), 1600.0 - i, joker=j, rounds={1})
               for i, (s, f, j) in enumerate(names, start=1)]
    save_players(tmp_path, players, 1)
    r = runner.invoke(app, ["pair", "1", "-d", str(tmp_path)])
    assert r.exit_code == 0, r.output
    pdf = tmp_path / "round_1_alphabetical.pdf"
    assert pdf.exists() and (tmp_path / "round_1.pdf").exists()
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(pdf), "-"], capture_output=True, text=True,
                          encoding="utf-8").stdout
    order = [n for n in ("Äbel Anna", "Becker Ben", "Mueller Mia", "Müller Max", "Zimmer Zoe")
             if n in text]
    assert len(order) == 5
    # rows of the table start with the player's name (other lines: board and opponent columns)
    first_column = [l.strip().split(" (5k)")[0] for l in text.splitlines()
                    if "(5k)" in l and l.strip().startswith(tuple(order))]
    assert first_column == ["Äbel Anna", "Becker Ben", "Mueller Mia", "Müller Max", "Zimmer Zoe"]
    assert "does not play this round" in text                # the joker sits out
    joker_line = next(l for l in text.splitlines() if l.strip().startswith("Mueller Mia"))
    assert "does not play" in joker_line

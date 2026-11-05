import pytest
from typer.testing import CliRunner

from gotourney import egd
from gotourney.cli import app
from gotourney.players import load_players

SAMPLE = """<pre>
   PIN          Name                              Club     Grade P&D    GoR    NT appearance
</b>
 20633162  Maekawa Kaku                          DE  K       5d   --   2543    34  T261003A
 10774412  Luethke Hans-Eckart                   DE  SN      1k   --   2064    40  T260926G
 13986203  van_den_Broek Erik                    NL  Gron    1k   --   1987    12  T250101A
 12345678  Mueller Anna                          DE  XXXX   37k   --   -833     1  T200101A
 20962524  Benedict Martina                      DE  XXXX   20k   --     11     0
</pre>"""


@pytest.fixture
def index():
    return egd.PlayerIndex(egd.parse_player_list(SAMPLE))


def test_parse(index):
    assert len(index.players) == 5
    p = index.by_pin["13986203"]
    assert (p.surname, p.first_name, p.country, p.club, p.grade, p.gor) == \
        ("van den Broek", "Erik", "NL", "Gron", "1k", 1987)
    assert index.by_pin["12345678"].club == ""
    assert index.by_pin["20962524"].last_appearance == ""


@pytest.mark.parametrize("query, names", [
    ("maek", ["Maekawa Kaku"]),
    ("luethke h", ["Luethke Hans-Eckart"]),
    ("lüthke", ["Luethke Hans-Eckart"]),
    ("Müller", ["Mueller Anna"]),
    ("van den", ["van den Broek Erik"]),
    ("erik broek", ["van den Broek Erik"]),
    ("2063", ["Maekawa Kaku"]),
    ("", []),
    ("zzz", []),
])
def test_search(index, query, names):
    assert [p.name for p in index.search(query)] == names


def test_cli_add_by_pin_uses_egd(tmp_path, monkeypatch, index):
    monkeypatch.setattr(egd, "fetch_by_pin", lambda pin: index.by_pin[pin])
    d = str(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init", d]).exit_code == 0
    r = runner.invoke(app, ["players", "add", "--pin", "10774412", "--rounds", "1-2", "-d", d])
    assert r.exit_code == 0, r.output
    p = load_players(tmp_path, 5).players[0]
    assert (p.name, str(p.rank), p.gor, p.club, p.egd_gor, p.egd_last_tournament, p.rounds) == \
        ("Luethke Hans-Eckart", "1k", 2064, "SN", 2064, "T260926G", {1, 2})


def test_cli_add_by_pin_offline_falls_back_to_list(tmp_path, monkeypatch, index):
    def offline(pin):
        raise egd.EGDError("no network")
    monkeypatch.setattr(egd, "fetch_by_pin", offline)
    monkeypatch.setattr(egd.PlayerIndex, "load", classmethod(lambda cls, *a, **k: index))
    d = str(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["init", d])
    r = runner.invoke(app, ["players", "add", "-p", "20633162", "-g", "2500", "-d", d])
    assert r.exit_code == 0, r.output
    p = load_players(tmp_path, 5).players[0]
    assert p.name == "Maekawa Kaku" and p.gor == 2500   # explicit GoR wins over EGD

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import ConfigError, parse_config
from gotourney.models import Game, Result
from gotourney.ods import read_sheet, write_sheet
from gotourney.players import columns, load_players, save_players
from gotourney.rounds import save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def set_fields(d, fields):
    """Set extra_fields and drop the dropdown lists of the template."""
    import re
    toml = d / "tournament.toml"
    text = re.sub(r"^extra_fields\s*=.*$", f"extra_fields = {fields!r}".replace("'", '"'), toml.read_text(),
                  flags=re.M)
    text = text[:text.index("[registration.field_values]")]
    toml.write_text(text)


@pytest.mark.parametrize("fields, msg", [(["Club"], "standard column"), (["R2"], "standard column"),
                                         (["Email", "email"], "twice"), ([""], "empty")])
def test_invalid_extra_fields(fields, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config({"registration": {"extra_fields": fields}})


def test_cli_add_with_extra_fields_and_standings(tmp_path):
    d = str(tmp_path)
    runner.invoke(app, ["init", d, "--rounds", "1"])
    set_fields(tmp_path, ["Email", "Fee paid"])
    r = runner.invoke(app, ["players", "add", "Doe", "John", "-r", "1k", "-x", "fee paid=yes",
                            "-x", "Email=john@example.org", "-d", d])
    assert r.exit_code == 0, r.output
    runner.invoke(app, ["players", "add", "Roe", "Jane", "-r", "2k", "-d", d])
    r = runner.invoke(app, ["players", "add", "X", "Y", "-r", "2k", "-x", "Shirt=L", "-d", d])
    assert r.exit_code == 1 and "unknown field" in r.output
    pl = load_players(tmp_path, 1, ["Email", "Fee paid"])
    assert pl.extra_fields == ["Email", "Fee paid", "Age group"]   # column from init is kept
    assert pl.players[0].extra == {"Email": "john@example.org", "Fee paid": "yes"}
    header = read_sheet(tmp_path / "players.ods").header
    assert header.index("Email") < header.index("Notes")
    # play the round and check the standings contain the extra data
    t = Tournament.load(tmp_path)
    save_round(tmp_path / "round_1.ods", [Game(1, 1, 2, 1, 0.5, Result.WHITE_WINS)],
               {1: "1k Doe John", 2: "2k Roe Jane"}, t.rating_before(1))
    r = runner.invoke(app, ["standings", "-d", d])
    assert r.exit_code == 0, r.output
    rows = {row.text("Name"): row for row in read_sheet(tmp_path / "standings.ods").rows}
    assert rows["Doe John"].text("Email") == "john@example.org"
    assert rows["Doe John"].text("Fee paid") == "yes"
    assert rows["Roe Jane"].text("Fee paid") == ""


def test_hand_added_column_is_kept(tmp_path):
    from gotourney.registration import new_player
    p = new_player([], surname="Doe", first_name="John", rank="1k", gor=None, rounds={1})
    save_players(tmp_path, [p], 1)
    # director adds a column "T-shirt" by hand in LibreOffice
    sheet = read_sheet(tmp_path / "players.ods")
    cols = columns(1)
    from gotourney.ods import Column
    write_sheet(tmp_path / "players.ods", "Players", cols + [Column("T-shirt")],
                [[r.get(c.title) for c in cols] + ["XL"] for r in sheet.rows])
    pl = load_players(tmp_path, 1)
    assert pl.extra_fields == ["T-shirt"] and pl.players[0].extra == {"T-shirt": "XL"}
    # rewriting (e.g. after adding another player) keeps the column and its data
    q = new_player(pl.players, surname="Roe", first_name="Jane", rank="2k", gor=None, rounds={1})
    save_players(tmp_path, pl.players + [q], 1, pl.extra_fields)
    again = load_players(tmp_path, 1)
    assert again.extra_fields == ["T-shirt"] and again.players[0].extra == {"T-shirt": "XL"}

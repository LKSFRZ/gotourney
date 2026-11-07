import re

import pytest
from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import ConfigError, parse_config
from gotourney.i18n import builtin
from gotourney.summary import SUMMARY_FILE, summary_sections, system_summary_pdf


def pages(path) -> int:
    return len(re.findall(rb"/Type /Page[^s]", path.read_bytes()))


def text_of(cfg, lang="en") -> str:
    return "\n".join(h + "\n" + "\n".join(ps) for h, ps in summary_sections(cfg, builtin(lang)))


def test_summary_uses_the_settings():
    cfg = parse_config({"tournament": {"rounds": 6}, "rating": {"k_factor": 2, "top_bar": "4d"},
                        "handicap": {"reduction": 1, "floor": "15k", "komi_even": 7.5}})
    text = text_of(cfg)
    assert "2 times as fast" in text and "2400 (4d)" in text and "minus 1" in text
    assert "below 600 (15k)" in text and "Komi: 7.5" in text and "after round 6" in text
    assert "Same Club: avoided" in text
    de = text_of(cfg, "de")
    assert "Komi: 7,5" in de and "2-mal so schnell" in de


def test_summary_leaves_out_what_is_switched_off():
    cfg = parse_config({"rating": {"top_bar": "none"}, "handicap": {"floor": "none"}, "pairing": {"rules": []}})
    text = text_of(cfg)
    assert "Nobody starts higher" not in text and "count as" not in text and "Same" not in text


def test_summary_is_one_page_even_with_many_rules(tmp_path):
    rules = [{"field": f, "type": "avoid_same", "points": 100} for f in ("Club", "Country", "Rank")] * 4
    cfg = parse_config({"tournament": {"name": "A rather long tournament name for testing"},
                        "pairing": {"rules": rules}})
    for lang in ("en", "de", "fr"):
        path = system_summary_pdf(cfg, tmp_path / f"s_{lang}.pdf", builtin(lang))
        assert pages(path) == 1, lang


def test_cli_and_web(make_tournament):
    d = make_tournament([(2000,), (1990,)], rounds=2)
    r = CliRunner().invoke(app, ["summary", "-d", str(d)])
    assert r.exit_code == 0, r.output
    assert pages(d / SUMMARY_FILE) == 1
    (d / SUMMARY_FILE).unlink()
    from tests.test_web import client_for, page
    application, c = client_for(d)
    assert "Tournament system (1 page)" in page(c.get("/documents"))
    assert SUMMARY_FILE in page(c.get("/system"))
    resp = c.get(f"/file/{SUMMARY_FILE}")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"


# ---------------------------------------------------------------- rules and clock

def test_game_settings_parse_and_defaults(tmp_path):
    from gotourney.config import load_config, write_template
    assert parse_config({}).game.rules is None and parse_config({}).game.time_system is None   # old files: not stated
    write_template(tmp_path, "T")
    g = load_config(tmp_path).game                                  # new tournaments: Japanese, 5 x 30 s
    assert (g.rules, g.time_system, g.byoyomi_periods, g.byoyomi_seconds) == ("japanese", "byoyomi", 5, 30)
    assert parse_config({"game": {"time_system": "Sudden Death"}}).game.time_system == "sudden_death"
    with pytest.raises(ConfigError, match="game.rules"):
        parse_config({"game": {"rules": "korean"}})
    with pytest.raises(ConfigError, match="byoyomi_seconds"):
        parse_config({"game": {"byoyomi_seconds": 0}})
    with pytest.raises(ConfigError, match="unknown"):
        parse_config({"game": {"overtime": 1}})


@pytest.mark.parametrize("game, expected", [
    ({"rules": "chinese", "time_system": "byoyomi", "byoyomi_periods": 3, "byoyomi_seconds": 20},
     ["Chinese rules", "40 minutes per player, then byo-yomi: 3 periods of 20 seconds"]),
    ({"rules": "aga", "time_system": "canadian", "canadian_stones": 20, "canadian_minutes": 10},
     ["AGA rules", "Canadian byo-yomi: 20 stones in 10 minutes"]),
    ({"time_system": "fischer", "fischer_seconds": 15, "fischer_max": 60},
     ["plus 15 seconds for every move", "At most 60 minutes"]),
    ({"time_system": "sudden_death"}, ["no overtime"]),
])
def test_rules_and_clock_in_the_summary(game, expected):
    cfg = parse_config({"tournament": {"time": 40}, "game": game})
    text = text_of(cfg)
    assert "Rules and time" in text
    for e in expected:
        assert e in text


def test_no_rules_section_when_not_stated():
    assert "Rules and time" not in text_of(parse_config({}))


def test_settings_form_saves_rules_and_clock(make_tournament):
    import re as _re
    from gotourney.config import load_config
    from tests.test_web import client_for, page, post
    d = make_tournament([(2000,), (1990,)], rounds=1)
    app_, c = client_for(d)
    html = page(c.get("/settings"))
    assert 'name="game_rules"' in html and 'data-system="canadian"' in html
    assert "byo-yomi: 5 periods of 30 seconds" in html                  # preview of the current clock
    version = _re.search(r'name="version" value="([^"]+)"', html).group(1)
    form = {"version": version, "name": "Cup", "class": "A", "time": "45", "rounds": "1", "language": "en",
            "translation_file": "translation.toml", "k_factor": "3", "top_bar": "3d", "reduction": "0", "floor": "20k",
            "komi_even": "7.5", "komi_handicap": "0.5", "random_seed": "1", "gor_outdated_years": "5",
            "rank_gor_tolerance": "300", "rule_field_0": "Club", "rule_type_0": "avoid_same", "rule_points_0": "150",
            "xf_name_0": "Fee paid", "xf_values_0": "yes, no", "xf_name_1": "Age group",
            "xf_values_1": "U7, U11, U15, U19, Ü50",
            "game_rules": "chinese", "time_system": "canadian", "canadian_stones": "20", "canadian_minutes": "10",
            "byoyomi_periods": "", "byoyomi_seconds": "", "fischer_seconds": "", "fischer_max": ""}
    r = post(c, app_, "/settings", **form)
    assert "Settings saved" in page(r)
    cfg = load_config(d)
    assert (cfg.game.rules, cfg.game.time_system, cfg.game.canadian_stones, cfg.game.canadian_minutes) == \
        ("chinese", "canadian", 20, 10)
    assert cfg.tournament.time == 45 and cfg.game.byoyomi_seconds == 30      # empty hidden field: kept default
    assert "Chinese rules" in page(c.get("/system"))


def test_dashboard_lists_the_summary(make_tournament):
    from tests.test_web import client_for, page
    d = make_tournament([(2000,), (1990,)], rounds=1)
    assert not (d / SUMMARY_FILE).exists()
    application, c = client_for(d)
    assert f'href="/file/{SUMMARY_FILE}"' in page(c.get("/dashboard"))      # listed before it exists
    assert c.get(f"/file/{SUMMARY_FILE}").mimetype == "application/pdf"      # and created when opened

import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from gotourney.awards import compute_awards
from gotourney.cli import app
from gotourney.config import ConfigError, load_config, parse_config
from gotourney.i18n import KEYS, TEXTS, TranslationError, builtin, get_translator, load_custom, translation_template
from gotourney.models import Game, Result
from gotourney.rounds import save_round
from gotourney.tournament import Tournament

runner = CliRunner()


def test_all_languages_have_all_keys():
    for lang, texts in TEXTS.items():
        assert set(KEYS) <= set(texts), lang


@pytest.mark.parametrize("value, lang", [("en", "en"), ("German", "de"), ("deutsch", "de"),
                                         ("Français", "fr"), ("custom", "custom")])
def test_language_setting(value, lang):
    assert parse_config({"output": {"language": value}}).output.language == lang


def test_unsupported_language():
    with pytest.raises(ConfigError, match="not supported"):
        parse_config({"output": {"language": "klingon"}})


@pytest.mark.parametrize("lang, n, text", [("en", 1, "1st"), ("en", 12, "12th"), ("en", 23, "23rd"),
                                           ("de", 1, "1."), ("de", 3, "3."), ("fr", 1, "1re"), ("fr", 2, "2e")])
def test_ordinals(lang, n, text):
    assert builtin(lang).ordinal(n) == text


def test_dates():
    assert builtin("de").date_range(["2026-09-27", "2026-09-26"]) == "26.09.2026 – 27.09.2026"
    assert builtin("fr").date("2026-09-26") == "26/09/2026"
    assert builtin("en").date("not a date") == "not a date"


def test_template_is_german_and_complete(tmp_path):
    path = tmp_path / "translation.toml"
    path.write_text(translation_template("de"))
    tr, warnings = load_custom(path)
    assert warnings == []
    assert tr.t("awards_title") == "Siegerehrung"
    assert tr.t("col_white_win") == "Weiß\ngewinnt"
    assert tr.ordinal(2) == "2."


def test_custom_file_fallback_and_errors(tmp_path):
    path = tmp_path / "translation.toml"
    path.write_text('awards_title = "Prijsuitreiking"\nordinal = "{n}e"\n[ordinals]\n1 = "1ste"\n')
    tr, warnings = load_custom(path)
    assert tr.t("awards_title") == "Prijsuitreiking"
    assert tr.t("col_board") == "Board"                      # missing -> English
    assert any("'col_board' missing" in w for w in warnings)
    assert tr.ordinal(1) == "1ste" and tr.ordinal(4) == "4e"
    path.write_text('award_place = "Plaats {rank}"\n')
    with pytest.raises(TranslationError, match="unknown placeholder"):
        load_custom(path)
    with pytest.raises(TranslationError, match="not found"):
        load_custom(tmp_path / "missing.toml")


def test_init_language_and_translation_file(tmp_path):
    d = tmp_path / "t"
    r = runner.invoke(app, ["init", str(d), "--language", "de"])
    assert r.exit_code == 0, r.output
    cfg = load_config(d)
    assert cfg.output.language == "de"
    assert [p.title for p in cfg.awards.prizes] == ["", "Bestes Kind", ""]
    assert "Siegerehrung" in (d / "translation.toml").read_text()
    assert runner.invoke(app, ["translation-file", "-d", str(d)]).exit_code == 1      # exists
    r = runner.invoke(app, ["translation-file", "-d", str(d), "--language", "fr", "--force"])
    assert r.exit_code == 0 and "Remise des prix" in (d / "translation.toml").read_text()


def test_default_prize_titles_follow_language(make_tournament):
    d = make_tournament([(2000,), (1900,)], rounds=1, language='"de"')
    t = Tournament.load(d)
    save_round(d / "round_1.ods", [Game(1, 1, 2, 1, 0.5, Result.WHITE_WINS)], {1: "a", 2: "b"}, t.rating_before(1))
    t = Tournament.load(d)
    tr, _ = get_translator(t.cfg, d)
    titles = [a.title for a in compute_awards(t, tr)[0]]
    assert titles == ["1 Siege", "2. Platz", "1. Platz"]


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_pdfs_in_german(make_tournament):
    d = make_tournament([(2000,), (1900,)], rounds=1, language='"de"')
    assert runner.invoke(app, ["pair", "1", "-d", str(d)]).exit_code == 0
    text = subprocess.run(["pdftotext", str(d / "round_1.pdf"), "-"], capture_output=True, text=True).stdout
    assert "Runde 1" in text and "Brett" in text and "Vorgabe" in text
    t = Tournament.load(d)
    g = t.rounds[1].games
    g[0].result = Result.WHITE_WINS
    save_round(d / "round_1.ods", g, {1: "a", 2: "b"}, t.rating_before(1))
    assert runner.invoke(app, ["awards", "-d", str(d)]).exit_code == 0
    text = subprocess.run(["pdftotext", str(d / "awards.pdf"), "-"], capture_output=True, text=True).stdout
    assert "Siegerehrung" in text and "1. Platz" in text and "Partien gewonnen" in text


def test_custom_language_needs_file(make_tournament):
    d = make_tournament([(2000,), (1900,)], rounds=1, language='"custom"')
    r = runner.invoke(app, ["pair", "1", "-d", str(d)])
    assert r.exit_code == 1 and "translation-file" in r.output

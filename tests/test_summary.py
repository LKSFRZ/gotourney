import re

from typer.testing import CliRunner

from gotourney.cli import app
from gotourney.config import parse_config
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

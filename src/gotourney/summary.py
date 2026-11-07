"""One-page summary of the tournament system with the settings of a tournament, to hang up."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate

from .config import Config
from .i18n import Translator, builtin
from .printing import _esc, _register_fonts
from .rank import Rank

SUMMARY_FILE = "tournament_system.pdf"
ACCENT = colors.HexColor("#1f4e79")
MUTED = colors.HexColor("#5f6b76")
MARGIN = 16 * mm
DASH = "–"


def _number(value: float, tr: Translator) -> str:
    text = f"{value:g}"
    return text.replace(".", ",") if tr.language in ("de", "fr") else text


def _rating(value: float, tr: Translator) -> str:
    return f"{_number(value, tr)} ({Rank.from_gor(value)})"


def game_lines(cfg: Config, tr: Translator) -> list[str]:
    """Rules and clock as sentences; empty if neither is stated in the settings."""
    g, main = cfg.game, cfg.tournament.time
    lines = []
    if g.rules:
        lines.append(tr.t("sys_rules_" + g.rules))
    if g.time_system == "sudden_death":
        lines.append(tr.t("sys_clock_sudden_death", main=main))
    elif g.time_system == "byoyomi":
        lines.append(tr.t("sys_clock_byoyomi", main=main, periods=g.byoyomi_periods, seconds=g.byoyomi_seconds))
    elif g.time_system == "canadian":
        lines.append(tr.t("sys_clock_canadian", main=main, stones=g.canadian_stones, minutes=g.canadian_minutes))
    elif g.time_system == "fischer":
        text = tr.t("sys_clock_fischer", main=main, seconds=g.fischer_seconds)
        if g.fischer_max:
            text += " " + tr.t("sys_clock_fischer_max", max=g.fischer_max)
        lines.append(text)
    return lines


def summary_sections(cfg: Config, tr: Translator) -> list[tuple[str, list[str]]]:
    """(heading, paragraphs) of the summary, using the settings of the tournament."""
    from .rating import game_changes
    gain, loss = game_changes(2000, 2000, 0, 1.0, cfg.rating.k_factor)
    start = [tr.t("sys_start")]
    if cfg.rating.top_bar is not None:
        start.append(tr.t("sys_bar", bar=_rating(cfg.rating.top_bar, tr)))
    update = [tr.t("sys_update", k=_number(cfg.rating.k_factor, tr)),
              tr.t("sys_example", rating=_rating(2000, tr), gain=f"{gain:.0f}", loss=f"{-loss:.0f}")]
    pairing = [tr.t("sys_pairing")]
    for rule in cfg.pairing.rules:
        pairing.append(tr.t("sys_rule_" + rule.type, field=rule.field, points=_number(rule.points, tr)))
    h = cfg.handicap
    handicap = [tr.t("sys_handicap_reduced", reduction=h.reduction) if h.reduction else tr.t("sys_handicap")]
    if h.floor is not None:
        handicap.append(tr.t("sys_floor", floor=_rating(h.floor, tr)))
    handicap.append(tr.t("sys_komi", even=_number(h.komi_even, tr), handicap=_number(h.komi_handicap, tr)))
    game = game_lines(cfg, tr)
    return ([(tr.t("sys_h_game"), game)] if game else []) + [
        (tr.t("sys_h_start"), start),
        (tr.t("sys_h_update"), update),
        (tr.t("sys_h_pairing"), pairing),
        (tr.t("sys_h_handicap"), handicap),
        (tr.t("sys_h_more"), [tr.t("sys_joker"), tr.t("sys_results")]),
        (tr.t("sys_h_winner"), [tr.t("sys_winner", rounds=cfg.tournament.rounds)]),
    ]


def _blocks(cfg: Config, tr: Translator, scale: float) -> list[list]:
    """The page as blocks of paragraphs; each section is one block, kept together."""
    regular, bold = _register_fonts()
    size = 13 * scale
    title = ParagraphStyle("t", fontName=bold, fontSize=30 * scale, leading=35 * scale)
    subtitle = ParagraphStyle("s", fontName=regular, fontSize=16 * scale, leading=20 * scale, textColor=MUTED,
                              spaceAfter=10 * scale)
    intro = ParagraphStyle("i", fontName=bold, fontSize=size + 1, leading=(size + 1) * 1.35, spaceAfter=6 * scale)
    heading = ParagraphStyle("h", fontName=bold, fontSize=17 * scale, leading=21 * scale, textColor=ACCENT,
                             spaceBefore=11 * scale, spaceAfter=3 * scale)
    body = ParagraphStyle("b", fontName=regular, fontSize=size, leading=size * 1.35, leftIndent=12 * scale,
                          bulletIndent=0, bulletFontName=regular, spaceAfter=3 * scale)
    blocks = [[Paragraph(_esc(tr.t("sys_title", tournament=cfg.tournament.name)), title),
               Paragraph(_esc(tr.t("sys_subtitle")), subtitle),
               Paragraph(_esc(tr.t("sys_intro")), intro)]]
    for head, paragraphs in summary_sections(cfg, tr):
        blocks.append([Paragraph(_esc(head), heading)]
                      + [Paragraph(_esc(p), body, bulletText=DASH) for p in paragraphs])
    return blocks


def _height(blocks: list[list], width: float) -> float:
    total = 0.0
    for flowable in (f for block in blocks for f in block):
        _, h = flowable.wrap(width, 10_000)
        total += h + flowable.getSpaceBefore() + flowable.getSpaceAfter()
    return total


def system_summary_pdf(cfg: Config, path: Path, tr: Translator | None = None) -> Path:
    """Write the one-page summary. The text shrinks if many rules would not fit on the page."""
    tr = tr or builtin("en")
    width, height = A4[0] - 2 * MARGIN, A4[1] - 2 * MARGIN
    scale = 1.0
    blocks = _blocks(cfg, tr, scale)
    while scale > 0.6 and _height(blocks, width) > height - 8 * mm:
        scale -= 0.05
        blocks = _blocks(cfg, tr, scale)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN, title=tr.t("sys_subtitle"), author="gotourney")
    doc.build([KeepTogether(block) for block in blocks])
    return Path(path)

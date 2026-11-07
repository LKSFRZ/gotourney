"""Printable PDF of a round's pairing: board, players (colour stone, rank, name), result columns,
handicap."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

from .i18n import Translator, builtin
from .rounds import BLACK_STONE, MARKS, WHITE_STONE, RoundGames, player_label
from .tournament import Tournament

FONT_CANDIDATES = [
    # (regular, bold) - fonts that contain the stone symbols ○ ●
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]


class PrintError(Exception):
    pass


def _register_fonts() -> tuple[str, str]:
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists():
            if "GT-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("GT-Regular", regular))
                pdfmetrics.registerFont(TTFont("GT-Bold", bold if Path(bold).exists() else regular))
            return "GT-Regular", "GT-Bold"
    raise PrintError("no font with the stone symbols found (install the DejaVu fonts: "
                     "sudo apt install fonts-dejavu-core)")


def pairing_pdf(t: Tournament, rg: RoundGames, path: Path, tr: Translator | None = None) -> Path:
    tr = tr or builtin("en")
    regular, bold = _register_fonts()
    games = sorted(rg.games, key=lambda g: g.board)

    header = [tr.t(k) for k in ("col_board", "col_white", "col_white_win", "col_draw",
                                "col_black_win", "col_black", "col_handicap")]
    data = [header]
    for g in games:
        marks = MARKS[g.result] if g.result else ("", "", "")
        data.append([
            str(g.board),
            f"{WHITE_STONE}  {player_label(t.players[g.white])}",
            *marks,
            f"{BLACK_STONE}  {player_label(t.players[g.black])}",
            str(g.handicap),
        ])

    page_w, _ = A4
    margin = 15 * mm
    usable = page_w - 2 * margin
    mark_w = 13 * mm
    board_w = 13 * mm
    handicap_w = 14 * mm
    name_w = (usable - board_w - 3 * mark_w - handicap_w) / 2
    # largest font size (11 down to 7 pt) at which the longest player cell fits
    longest = max((max(pdfmetrics.stringWidth(row[1], regular, 1), pdfmetrics.stringWidth(row[5], regular, 1))
                   for row in data[1:]), default=0)
    body_size = 11.0
    while body_size > 7 and longest * body_size > name_w - 8:
        body_size -= 0.5
    for row in data[1:]:
        for col in (1, 5):
            row[col] = _fit(row[col], regular, body_size, name_w - 8)
    widths = [board_w, name_w, mark_w, mark_w, mark_w, name_w, handicap_w]
    # header font: largest size (9.5 down to 6 pt) at which every header line fits its column
    header_size = 9.5
    while header_size > 6 and any(
            pdfmetrics.stringWidth(line, bold, header_size) > w - 4
            for text, w in zip(header, widths) for line in text.split("\n")):
        header_size -= 0.5
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), bold, header_size),
        ("LEFTPADDING", (2, 0), (4, 0), 2),
        ("RIGHTPADDING", (2, 0), (4, 0), 2),
        ("FONT", (0, 1), (-1, -1), regular, body_size),
        ("FONT", (0, 1), (0, -1), bold, body_size),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (4, -1), "CENTER"),
        ("ALIGN", (6, 0), (6, -1), "CENTER"),
        ("FONT", (6, 1), (6, -1), bold, body_size),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
        ("ALIGN", (5, 0), (5, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde5ee")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.HexColor("#1f4e79")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7b4")),
        ("BOX", (2, 0), (4, -1), 1.0, colors.HexColor("#1f4e79")),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (1, i), colors.HexColor("#f3f6f9")))
        style.append(("BACKGROUND", (5, i), (6, i), colors.HexColor("#f3f6f9")))
    table.setStyle(TableStyle(style))

    name = t.cfg.tournament.name or t.directory.resolve().name
    title_text = tr.t("pairing_title", tournament=name, round=rg.number)
    title_size = 16.0
    while title_size > 11 and pdfmetrics.stringWidth(title_text, bold, title_size) > usable - 14:  # frame padding
        title_size -= 0.5
    title_style = ParagraphStyle("title", fontName=bold, fontSize=title_size, leading=title_size + 4,
                                 spaceAfter=2)
    sub_style = ParagraphStyle("sub", fontName=regular, fontSize=10, leading=13,
                               textColor=colors.HexColor("#5f6b76"))
    story = [
        Paragraph(_esc(title_text), title_style),
        Paragraph(_esc(tr.t("pairing_boards", n=len(games))), sub_style),
        Spacer(1, 6 * mm),
        table,
    ]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#5f6b76"))
        canvas.drawRightString(page_w - margin, 10 * mm, tr.t("pairing_footer", round=rg.number, page=doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=18 * mm,
                            title=tr.t("pairing_title", tournament=name, round=rg.number))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Shorten text with an ellipsis if it is still too wide at the smallest font size."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pdf_path(directory: Path, r: int) -> Path:
    return Path(directory) / f"round_{r}.pdf"

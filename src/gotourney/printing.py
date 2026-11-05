"""Printable PDF of a round's pairing: board, players (colour stone, rank, name), result columns."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

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


def pairing_pdf(t: Tournament, rg: RoundGames, path: Path) -> Path:
    regular, bold = _register_fonts()
    games = sorted(rg.games, key=lambda g: g.board)

    header = ["Board", "White", "White\nwin", "Draw", "Black\nwin", "Black"]
    data = [header]
    for g in games:
        marks = MARKS[g.result] if g.result else ("", "", "")
        data.append([
            str(g.board),
            f"{WHITE_STONE}  {player_label(t.players[g.white])}",
            *marks,
            f"{BLACK_STONE}  {player_label(t.players[g.black])}",
        ])

    page_w, _ = A4
    margin = 15 * mm
    usable = page_w - 2 * margin
    mark_w = 15 * mm
    board_w = 14 * mm
    name_w = (usable - board_w - 3 * mark_w) / 2
    table = Table(data, colWidths=[board_w, name_w, mark_w, mark_w, mark_w, name_w], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), bold, 9.5),
        ("FONT", (0, 1), (-1, -1), regular, 11),
        ("FONT", (0, 1), (0, -1), bold, 11),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (4, -1), "CENTER"),
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
        style.append(("BACKGROUND", (5, i), (5, i), colors.HexColor("#f3f6f9")))
    table.setStyle(TableStyle(style))

    title_style = ParagraphStyle("title", fontName=bold, fontSize=16, leading=20, spaceAfter=2)
    sub_style = ParagraphStyle("sub", fontName=regular, fontSize=10, leading=13,
                               textColor=colors.HexColor("#5f6b76"))
    name = t.cfg.tournament.name or t.directory.resolve().name
    story = [
        Paragraph(f"{_esc(name)} – Round {rg.number}", title_style),
        Paragraph(f"{len(games)} boards", sub_style),
        Spacer(1, 6 * mm),
        table,
    ]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#5f6b76"))
        canvas.drawRightString(page_w - margin, 10 * mm, f"Round {rg.number} – page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=18 * mm,
                            title=f"{name} – Round {rg.number}")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pdf_path(directory: Path, r: int) -> Path:
    return Path(directory) / f"round_{r}.pdf"

"""Printable PDF of a round's pairing: board, players (colour stone, rank, name), result columns,
handicap."""

from __future__ import annotations

import os
import unicodedata
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

FONT_ENV = "GOTOURNEY_FONT"
REQUIRED_CHARS = "\u25cb\u25cf\u2212\u2013\u00b7"     # ○ ● − – ·
STAR = "\u2605"                                         # ★ (award slides; optional)


def font_candidates() -> list[tuple[Path, Path]]:
    """(regular, bold) font files to try, in order. GOTOURNEY_FONT overrides:
    "regular.ttf" or "regular.ttf<path separator>bold.ttf"."""
    cands: list[tuple[Path, Path]] = []
    env = os.environ.get(FONT_ENV, "").strip()
    if env:
        parts = env.split(os.pathsep)
        cands.append((Path(parts[0]), Path(parts[1] if len(parts) > 1 and parts[1] else parts[0])))
    bundled = Path(__file__).parent / "data" / "fonts"                                    # shipped with gotourney
    cands.append((bundled / "DejaVuSans.ttf", bundled / "DejaVuSans-Bold.ttf"))
    dejavu_dirs = [
        Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/TTF"), Path("/usr/share/fonts/dejavu"),
        Path.home() / ".local/share/fonts", Path.home() / ".fonts",                          # Linux
        Path.home() / "Library/Fonts", Path("/Library/Fonts"), Path("/opt/homebrew/share/fonts"),  # macOS
    ]
    for var in ("LOCALAPPDATA",):                                                           # Windows
        if os.environ.get(var):
            dejavu_dirs.append(Path(os.environ[var]) / "Microsoft/Windows/Fonts")
    windir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    dejavu_dirs.append(windir)
    cands += [(d / "DejaVuSans.ttf", d / "DejaVuSans-Bold.ttf") for d in dejavu_dirs]
    cands += [
        (Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),                       # macOS
        (Path("/Library/Fonts/Arial Unicode.ttf"), Path("/Library/Fonts/Arial Unicode.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        (windir / "arial.ttf", windir / "arialbd.ttf"),                                     # Windows
        (windir / "segoeui.ttf", windir / "segoeuib.ttf"),
    ]
    return cands


def _chars(path: Path) -> set[int]:
    try:
        return set(TTFont(f"probe-{abs(hash(str(path)))}", str(path)).face.charToGlyph)
    except Exception:            # unreadable or unsupported font file
        return set()


def find_fonts() -> tuple[Path, Path, bool]:
    """(regular, bold, has_star): the first candidate that has all required symbols."""
    for regular, bold in font_candidates():
        if not regular.is_file():
            continue
        chars = _chars(regular)
        if not all(ord(c) in chars for c in REQUIRED_CHARS):
            continue
        if not bold.is_file() or not all(ord(c) in _chars(bold) for c in REQUIRED_CHARS):
            bold = regular
        return regular, bold, ord(STAR) in _chars(bold)
    raise PrintError(
        "no font with the symbols \u25cb \u25cf found. Install the free DejaVu fonts "
        "(Linux: sudo apt install fonts-dejavu-core; macOS / Windows: https://dejavu-fonts.github.io, "
        f"install DejaVuSans.ttf) or set the environment variable {FONT_ENV} to a .ttf file.")


class PrintError(Exception):
    pass


_FONTS: dict[str, object] = {}


def _register_fonts() -> tuple[str, str]:
    if "regular" not in _FONTS:
        regular, bold, has_star = find_fonts()
        pdfmetrics.registerFont(TTFont("GT-Regular", str(regular)))
        pdfmetrics.registerFont(TTFont("GT-Bold", str(bold)))
        _FONTS.update(regular=regular, bold=bold, star=has_star)
    return "GT-Regular", "GT-Bold"


def star_symbol() -> str:
    """★ if the chosen font has it, otherwise a plain asterisk."""
    _register_fonts()
    return STAR if _FONTS.get("star") else "*"


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


def round_cell(t: Tournament, pid: int, r: int, place_of: dict[int, int]) -> str:
    """'○12+' = white against the player on place 12, won; '●3−(2)' = black with 2 stones, lost."""
    game = next((h for h in t.history[pid] if h.round == r), None)
    if game is None:
        return "–"
    stone = WHITE_STONE if game.colour == "w" else BLACK_STONE
    if not game.has_result:
        sign = "?"
    elif game.forfeit:
        sign = "+!" if _forfeit_won(t, pid, r) else "\u2212!"
    else:
        sign = {1.0: "+", 0.0: "\u2212", 0.5: "="}[game.score]
    handicap = f" ({game.handicap})" if game.handicap else ""
    return f"{stone}{place_of[game.opponent]}{sign}{handicap}"


def _forfeit_won(t: Tournament, pid: int, r: int) -> bool:
    from .models import Result
    for g in t.rounds[r].games:
        if pid in g.players():
            return (g.result is Result.WHITE_WINS_FORFEIT and g.white == pid) or \
                   (g.result is Result.BLACK_WINS_FORFEIT and g.black == pid)
    return False


def standings_pdf(t: Tournament, after_round: int, path: Path, tr: Translator | None = None) -> Path:
    """Standings as a printable cross table (landscape A4)."""
    from .wall import ranking

    tr = tr or builtin("en")
    regular, bold = _register_fonts()
    order = ranking(t, after_round)
    place_of = {pid: i for i, pid in enumerate(order, start=1)}
    ratings = t.ratings[after_round]

    header = [tr.t("col_place"), tr.t("col_name"), tr.t("col_rank"), tr.t("col_tgor")] + \
        [tr.t("col_round", round=r) for r in range(1, after_round + 1)]
    data = [header]
    for pid in order:
        p = t.players[pid]
        change = ratings[pid] - t.start[pid]
        data.append([str(place_of[pid]), p.name, str(p.rank or ""),
                     f"{ratings[pid]:.0f} ({change:+.0f})"]
                    + [round_cell(t, pid, r, place_of) for r in range(1, after_round + 1)])

    page_w, page_h = A4[1], A4[0]           # landscape
    margin = 12 * mm
    usable = page_w - 2 * margin - 14       # frame padding
    place_w, rank_w, tgor_w = 13 * mm, 13 * mm, 26 * mm
    round_w = min(24 * mm, max(15 * mm, (usable - place_w - rank_w - tgor_w - 60 * mm) / max(after_round, 1)))
    name_w = usable - place_w - rank_w - tgor_w - round_w * after_round
    widths = [place_w, name_w, rank_w, tgor_w] + [round_w] * after_round

    body_size = 10.0
    def too_wide(size):
        return any(pdfmetrics.stringWidth(str(row[c]), regular, size) > widths[c] - 6
                   for row in data[1:] for c in range(len(widths)))
    while body_size > 6.5 and too_wide(body_size):
        body_size -= 0.5
    for row in data[1:]:
        row[1] = _fit(row[1], regular, body_size, widths[1] - 6)

    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), bold, 9),
        ("FONT", (0, 1), (-1, -1), regular, body_size),
        ("FONT", (0, 1), (0, -1), bold, body_size),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde5ee")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.HexColor("#1f4e79")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7b4")),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
    ]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f6f9")))
    table.setStyle(TableStyle(style))

    name = t.cfg.tournament.name or t.directory.resolve().name
    title_text = (tr.t("standings_title", tournament=name, round=after_round) if after_round
                  else tr.t("standings_start", tournament=name))
    title_size = 16.0
    while title_size > 11 and pdfmetrics.stringWidth(title_text, bold, title_size) > usable:
        title_size -= 0.5
    title_style = ParagraphStyle("title", fontName=bold, fontSize=title_size, leading=title_size + 4,
                                 spaceAfter=2)
    sub_style = ParagraphStyle("sub", fontName=regular, fontSize=9, leading=12,
                               textColor=colors.HexColor("#5f6b76"))
    dates = tr.date_range(t.cfg.tournament.dates)
    story = [Paragraph(_esc(title_text), title_style)]
    if dates or t.cfg.tournament.place:
        story.append(Paragraph(_esc("  ·  ".join(x for x in [t.cfg.tournament.place, dates] if x)), sub_style))
    story += [Spacer(1, 4 * mm), table, Spacer(1, 3 * mm),
              Paragraph(_esc(tr.t("standings_legend")), sub_style)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#5f6b76"))
        canvas.drawRightString(page_w - margin, 7 * mm, tr.t("standings_footer", page=doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=(page_w, page_h), leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=14 * mm, title=title_text)
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


def alphabetical_pdf_path(directory: Path, r: int) -> Path:
    return Path(directory) / f"round_{r}_alphabetical.pdf"


def _sort_key(text: str) -> str:
    """Case- and accent-insensitive sort key ('Äbel' sorts like 'Abel')."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def alphabetical_pdf(t: Tournament, rg: RoundGames, path: Path, tr: Translator | None = None) -> Path:
    """Pairing of a round as a list of all players sorted by surname: board, colour, opponent, handicap.

    Players registered for the round who are not on a board (e.g. the joker) are listed as well."""
    tr = tr or builtin("en")
    regular, bold = _register_fonts()
    entries = []      # (player id, board, colour, opponent id, handicap)
    for g in rg.games:
        entries.append((g.white, g.board, "w", g.black, g.handicap))
        entries.append((g.black, g.board, "b", g.white, g.handicap))
    on_board = {e[0] for e in entries}
    for pid, p in t.players.items():
        if p.plays(rg.number) and pid not in on_board:
            entries.append((pid, None, None, None, None))
    entries.sort(key=lambda e: (_sort_key(t.players[e[0]].surname), _sort_key(t.players[e[0]].first_name), e[0]))

    header = [tr.t("col_player"), tr.t("col_board"), tr.t("col_colour"), tr.t("col_opponent"),
              tr.t("col_handicap")]
    data = [header]
    def name_rank(pid: int) -> str:
        """'Surname First name (5k)' - surname first, so the list can be scanned by name."""
        p = t.players[pid]
        rank = player_label(p)[: -len(p.name)].strip() if player_label(p).endswith(p.name) else ""
        return f"{p.name} ({rank})" if rank else p.name

    for pid, board, colour, opp, handicap in entries:
        name = name_rank(pid)
        if board is None:
            data.append([name, "–", tr.t("alpha_not_paired"), "", ""])      # spans columns 2-4
            continue
        stone = WHITE_STONE if colour == "w" else BLACK_STONE
        colour_text = tr.t("col_white" if colour == "w" else "col_black").replace("\n", " ")
        data.append([name, str(board), f"{stone} {colour_text}", name_rank(opp), str(handicap)])

    page_w, _ = A4
    margin = 15 * mm
    usable = page_w - 2 * margin - 14          # frame padding
    board_w, colour_w, handicap_w = 15 * mm, 26 * mm, 16 * mm
    name_w = (usable - board_w - colour_w - handicap_w) / 2
    widths = [name_w, board_w, colour_w, name_w, handicap_w]
    body_size = 10.0
    while body_size > 7 and any(pdfmetrics.stringWidth(str(row[c]), regular, body_size) > widths[c] - 8
                                for row in data[1:] if row[1] != "–" for c in (0, 2, 3)):
        body_size -= 0.5
    for row in data[1:]:
        for c in (0, 3):
            row[c] = _fit(row[c], regular, body_size, widths[c] - 8)
    header_size = 9.5
    while header_size > 6 and any(pdfmetrics.stringWidth(line, bold, header_size) > w - 4
                                  for text, w in zip(header, widths) for line in text.split("\n")):
        header_size -= 0.5

    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), bold, header_size),
        ("FONT", (0, 1), (-1, -1), regular, body_size),
        ("FONT", (0, 1), (0, -1), bold, body_size),
        ("FONT", (1, 1), (1, -1), bold, body_size),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde5ee")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.HexColor("#1f4e79")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7b4")),
        ("TOPPADDING", (0, 1), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1.6),
    ]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f6f9")))
    for i, row in enumerate(data[1:], start=1):
        if row[1] == "–":
            style.append(("TEXTCOLOR", (1, i), (-1, i), colors.HexColor("#5f6b76")))
            style.append(("SPAN", (2, i), (4, i)))
            style.append(("FONT", (2, i), (4, i), "GT-Regular", body_size))
    table.setStyle(TableStyle(style))

    name = t.cfg.tournament.name or t.directory.resolve().name
    title_text = tr.t("alpha_title", tournament=name, round=rg.number)
    title_size = 16.0
    while title_size > 11 and pdfmetrics.stringWidth(title_text, bold, title_size) > usable:
        title_size -= 0.5
    title_style = ParagraphStyle("title", fontName=bold, fontSize=title_size, leading=title_size + 4,
                                 spaceAfter=2)
    sub_style = ParagraphStyle("sub", fontName=regular, fontSize=10, leading=13,
                               textColor=colors.HexColor("#5f6b76"))
    story = [Paragraph(_esc(title_text), title_style),
             Paragraph(_esc(tr.t("pairing_boards", n=len(rg.games))), sub_style),
             Spacer(1, 4 * mm), table]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#5f6b76"))
        canvas.drawRightString(page_w - margin, 8 * mm, tr.t("pairing_footer", round=rg.number, page=doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=title_text)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path

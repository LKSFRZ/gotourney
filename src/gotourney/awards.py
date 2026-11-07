"""Award ceremony: who gets which prize, and a PDF presentation with one slide per winner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdfcanvas

from .config import Prize
from .players import field_value
from .printing import _register_fonts
from .rank import Rank
from .tournament import Tournament
from .wall import format_wins, ranking

AWARDS_FILE = "awards.pdf"

# 16:9 slide, 960 x 540 pt
SLIDE_W, SLIDE_H = 960.0, 540.0

BG = colors.HexColor("#10233f")
BG_LIGHT = colors.HexColor("#173057")
TEXT = colors.HexColor("#ffffff")
TEXT_SOFT = colors.HexColor("#d6e2ee")
TEXT_MUTED = colors.HexColor("#93a8bf")
ACCENT = colors.HexColor("#e9b949")
MEDAL = {1: colors.HexColor("#e9b949"), 2: colors.HexColor("#c4ccd6"), 3: colors.HexColor("#cd8b4f")}
STONE_WHITE = colors.HexColor("#f4f1ea")
STONE_BLACK = colors.HexColor("#05090f")


class AwardError(Exception):
    pass


@dataclass
class Award:
    title: str
    player: int
    place: int
    wins: float
    games: int
    gain: float
    group: str = ""          # value of the group field (best_in_group)
    prize_type: str = ""


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _norm(v: str) -> str:
    return v.strip().casefold()


def compute_awards(t: Tournament) -> tuple[list[Award], list[str]]:
    """The prize winners in slide order, and notes about prizes nobody qualified for."""
    for r, rg in t.rounds.items():
        if not rg.complete:
            raise AwardError(f"round {r} has missing results; enter them first")
    order = ranking(t)
    place_of = {pid: i for i, pid in enumerate(order, start=1)}
    final = t.final_ratings()
    awarded: set[int] = set()
    awards: list[Award] = []
    notes: list[str] = []

    def games(pid: int) -> int:
        return sum(1 for h in t.history[pid] if h.counts_as_played)

    def make(prize: Prize, pid: int, n: int, group: str = "", group_label: str = "") -> Award:
        values = {"place": place_of[pid], "ordinal": ordinal(place_of[pid]),
                  "wins": format_wins(t.wins(pid)), "games": games(pid), "group": group_label, "n": n}
        return Award(prize.title.format(**values), pid, place_of[pid], t.wins(pid), games(pid),
                     final[pid] - t.start[pid], group, prize.type)

    def eligible(prize: Prize, pid: int) -> bool:
        return not (prize.exclusive and pid in awarded)

    for i, prize in enumerate(t.cfg.awards.prizes, start=1):
        found: list[Award] = []
        if prize.type == "place":
            for place in prize.places:
                if place <= len(order) and eligible(prize, order[place - 1]):
                    found.append(make(prize, order[place - 1], len(found) + 1))
        elif prize.type == "wins":
            for pid in order:
                if t.wins(pid) >= prize.min_wins and eligible(prize, pid):
                    found.append(make(prize, pid, len(found) + 1))
        elif prize.type == "rating_gain":
            by_gain = sorted(order, key=lambda pid: (-(final[pid] - t.start[pid]), place_of[pid]))
            for pid in by_gain:
                if len(found) >= prize.count:
                    break
                if games(pid) and eligible(prize, pid):
                    found.append(make(prize, pid, len(found) + 1))
        elif prize.type == "best_in_group":
            known = {"club", "country", "rank"} | {f.lower() for f in t.extra_fields}
            if prize.group_field.lower() not in known:
                notes.append(f"prize {i} ({prize.title}): there is no column {prize.group_field!r}; skipped")
                continue
            for group in prize.all_groups:
                members = {_norm(v) for v in group}
                label = ", ".join(group)
                n = 0
                for pid in order:
                    if n >= prize.count:
                        break
                    value = field_value(t.players[pid], prize.group_field)
                    if _norm(value) in members and games(pid) and eligible(prize, pid):
                        n += 1
                        found.append(make(prize, pid, n, value.strip(), label))
        if not found:
            notes.append(f"prize {i} ({prize.type}, title {prize.title!r}): nobody qualifies")
        for a in found:
            awarded.add(a.player)
        awards.extend(found)
    return awards, notes


# ---------------------------------------------------------------- slides

def _fit_size(text: str, font: str, size: float, width: float, minimum: float = 14) -> float:
    while size > minimum and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 1
    return size


def _stone(c, x: float, y: float, r: float, black: bool) -> None:
    c.setFillColor(STONE_BLACK if black else STONE_WHITE)
    c.setStrokeColor(colors.HexColor("#2b3f5f") if black else colors.HexColor("#c9c3b6"))
    c.setLineWidth(1.2)
    c.circle(x, y, r, stroke=1, fill=1)
    # small highlight
    c.setFillColor(colors.HexColor("#3a4a63") if black else colors.white)
    c.circle(x - r * 0.35, y + r * 0.35, r * 0.18, stroke=0, fill=1)


def _background(c, large: bool = False) -> None:
    c.setFillColor(BG)
    c.rect(0, 0, SLIDE_W, SLIDE_H, stroke=0, fill=1)
    # faint board grid in the lower right corner
    c.saveState()
    c.setStrokeColor(BG_LIGHT)
    c.setLineWidth(1)
    step = 24
    x0, y0 = SLIDE_W - 8 * step, -step
    for k in range(9):
        c.line(x0 + k * step, y0, x0 + k * step, y0 + 6 * step)
    for k in range(7):
        c.line(x0, y0 + k * step, x0 + 8 * step, y0 + k * step)
    c.restoreState()
    r = 10.5 if not large else 11
    for gx, gy, black in [(3, 2, True), (4, 3, False), (5, 2, True), (6, 4, False), (7, 3, True), (5, 4, False)]:
        _stone(c, x0 + gx * step, y0 + gy * step, r, black)


def _header(c, t: Tournament, regular: str) -> None:
    c.setFillColor(TEXT_MUTED)
    c.setFont(regular, 14)
    c.drawString(40, SLIDE_H - 40, t.cfg.tournament.name or t.directory.resolve().name)
    dates = " – ".join(sorted(set(t.cfg.tournament.dates)))
    if dates:
        c.drawRightString(SLIDE_W - 40, SLIDE_H - 40, dates)
    c.setStrokeColor(BG_LIGHT)
    c.setLineWidth(1.5)
    c.line(40, SLIDE_H - 52, SLIDE_W - 40, SLIDE_H - 52)


def _medal(c, cx: float, cy: float, award: Award, bold: str) -> None:
    if award.prize_type == "place" and award.place in MEDAL:
        colour, label, size = MEDAL[award.place], str(award.place), 30
    else:
        colour, label, size = ACCENT, "★", 28        # ★
    c.setFillColor(colour)
    c.setStrokeColor(colors.HexColor("#ffffff"))
    c.setLineWidth(2)
    c.circle(cx, cy, 30, stroke=1, fill=1)
    c.setFillColor(BG)
    c.setFont(bold, size)
    c.drawCentredString(cx, cy - size * 0.36, label)


def _title_slide(c, t: Tournament, regular: str, bold: str) -> None:
    _background(c, large=True)
    info = t.cfg.tournament
    name = info.name or t.directory.resolve().name
    size = _fit_size(name, bold, 46, SLIDE_W - 120)
    c.setFillColor(TEXT)
    c.setFont(bold, size)
    c.drawCentredString(SLIDE_W / 2, SLIDE_H / 2 + 40, name)
    c.setFillColor(ACCENT)
    c.setFont(bold, 30)
    c.drawCentredString(SLIDE_W / 2, SLIDE_H / 2 - 10, "Award ceremony")
    details = "  ·  ".join(x for x in [info.place, " – ".join(sorted(set(info.dates)))] if x)
    if details:
        c.setFillColor(TEXT_SOFT)
        c.setFont(regular, 20)
        c.drawCentredString(SLIDE_W / 2, SLIDE_H / 2 - 55, details)


def _award_slide(c, t: Tournament, a: Award, number: int, total: int, regular: str, bold: str) -> None:
    _background(c)
    _header(c, t, regular)
    p = t.players[a.player]
    cx = SLIDE_W / 2
    _medal(c, cx, SLIDE_H - 118, a, bold)

    c.setFillColor(ACCENT)
    size = _fit_size(a.title, bold, 36, SLIDE_W - 120)
    c.setFont(bold, size)
    c.drawCentredString(cx, SLIDE_H - 200, a.title)

    name = f"{p.first_name} {p.surname}".strip()
    c.setFillColor(TEXT)
    size = _fit_size(name, bold, 64, SLIDE_W - 100)
    c.setFont(bold, size)
    c.drawCentredString(cx, SLIDE_H / 2 - 20, name)

    rank = p.rank or (Rank.from_gor(t.start_gor[a.player]) if a.player in t.start_gor else None)
    info = "  ·  ".join(x for x in [str(rank or ""), p.club, p.country] if x)
    c.setFillColor(TEXT_SOFT)
    c.setFont(regular, 22)
    c.drawCentredString(cx, SLIDE_H / 2 - 62, info)

    stats = [f"Place {a.place}", f"{format_wins(a.wins)} of {a.games} games won",
             f"TGoR {t.final_ratings()[a.player]:.0f} ({a.gain:+.0f})"]
    if a.group:
        stats.insert(0, a.group)
    c.setFillColor(TEXT_MUTED)
    c.setFont(regular, 18)
    c.drawCentredString(cx, SLIDE_H / 2 - 96, "  ·  ".join(stats))

    c.setFont(regular, 10)
    c.drawString(40, 24, f"{number} / {total}")


def awards_pdf(t: Tournament, awards: list[Award], path: Path) -> Path:
    regular, bold = _register_fonts()
    c = pdfcanvas.Canvas(str(path), pagesize=(SLIDE_W, SLIDE_H))
    name = t.cfg.tournament.name or t.directory.resolve().name
    c.setTitle(f"{name} – Award ceremony")
    if t.cfg.awards.title_slide:
        _title_slide(c, t, regular, bold)
        c.showPage()
    for i, a in enumerate(awards, start=1):
        _award_slide(c, t, a, i, len(awards), regular, bold)
        c.showPage()
    if not awards and not t.cfg.awards.title_slide:
        _title_slide(c, t, regular, bold)
        c.showPage()
    c.save()
    return path

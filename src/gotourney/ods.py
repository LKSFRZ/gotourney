"""Reading and writing simple tables in LibreOffice Calc (.ods) files.

A table is one sheet with a header row; every following non-empty row is a record.
Reading is tolerant of hand edits: extra columns are ignored, header names are matched
case-insensitively, trailing empty rows/columns and repeated cells are handled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from odf.opendocument import OpenDocumentSpreadsheet, load
from odf.style import (MasterPage, PageLayout, PageLayoutProperties, ParagraphProperties, Style,
                       TableColumnProperties, TableProperties, TextProperties)
from odf.table import Table, TableCell, TableColumn, TableHeaderRows, TableRow
from odf.text import P, S

Cell = str | float | int | None

# Guard against absurd repeat counts LibreOffice writes for "rest of the sheet".
_MAX_REPEAT = 1000


class OdsError(Exception):
    pass


@dataclass
class Row:
    """One record of a table. ``line`` is the 1-based row number in the sheet."""

    line: int
    values: dict[str, Cell]

    def get(self, column: str, default: Cell = None) -> Cell:
        v = self.values.get(column.lower(), default)
        return default if v is None else v

    def text(self, column: str) -> str:
        v = self.get(column)
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v).strip()


@dataclass
class Sheet:
    name: str
    header: list[str]
    rows: list[Row]


# ---------------------------------------------------------------- reading

def _cell_text(cell) -> str:
    parts: list[str] = []

    def walk(node):
        for child in node.childNodes:
            if child.nodeType == child.TEXT_NODE:
                parts.append(child.data)
            elif child.qname[1] == "s":  # <text:s text:c="n"/> = n spaces
                parts.append(" " * int(child.getAttribute("c") or 1))
            elif child.qname[1] in ("tab",):
                parts.append("\t")
            else:
                walk(child)

    paragraphs = [c for c in cell.childNodes if c.qname[1] == "p"]
    texts = []
    for p in paragraphs:
        parts.clear()
        walk(p)
        texts.append("".join(parts))
    return "\n".join(texts)


def _cell_value(cell) -> Cell:
    vtype = cell.getAttribute("valuetype")
    if vtype in ("float", "percentage", "currency"):
        raw = cell.getAttribute("value")
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    text = _cell_text(cell).strip()
    return text if text != "" else None


def _read_rows(table) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for tr in table.getElementsByType(TableRow):
        rrep = int(tr.getAttribute("numberrowsrepeated") or 1)
        values: list[Cell] = []
        for cell in tr.childNodes:
            if cell.qname[1] not in ("table-cell", "covered-table-cell"):
                continue
            crep = int(cell.getAttribute("numbercolumnsrepeated") or 1)
            v = _cell_value(cell) if cell.qname[1] == "table-cell" else None
            values.extend([v] * min(crep, _MAX_REPEAT))
        while values and values[-1] is None:
            values.pop()
        rows.extend([list(values) for _ in range(min(rrep, _MAX_REPEAT))])
    while rows and not rows[-1]:
        rows.pop()
    return rows


def read_sheet(path: Path, sheet: str | None = None, fallback_first: bool = False) -> Sheet:
    """Read a sheet by name (or the first sheet). With fallback_first, a missing sheet name
    falls back to the first sheet (e.g. after a hand-made file got a different sheet name)."""
    path = Path(path)
    if not path.exists():
        raise OdsError(f"{path} not found")
    try:
        doc = load(str(path))
    except Exception as e:  # odfpy raises various errors on broken files
        raise OdsError(f"{path}: cannot read file ({e})") from e
    tables = doc.spreadsheet.getElementsByType(Table)
    if not tables:
        raise OdsError(f"{path}: no sheets found")
    if sheet is None:
        table = tables[0]
    else:
        matches = [t for t in tables if t.getAttribute("name").lower() == sheet.lower()]
        if not matches and not fallback_first:
            raise OdsError(f"{path}: sheet '{sheet}' not found")
        table = matches[0] if matches else tables[0]
    name = table.getAttribute("name")
    raw = _read_rows(table)
    if not raw:
        return Sheet(name, [], [])
    header = [str(h).strip() if h is not None else "" for h in raw[0]]
    keys = [h.lower() for h in header]
    rows: list[Row] = []
    for i, values in enumerate(raw[1:], start=2):
        if all(v is None for v in values):
            continue
        record = {}
        for k, v in zip(keys, values):
            if k:
                record[k] = v
        rows.append(Row(i, record))
    return Sheet(name, header, rows)


def require_columns(sheet: Sheet, path: Path, columns: Sequence[str]) -> None:
    have = {h.lower() for h in sheet.header}
    missing = [c for c in columns if c.lower() not in have]
    if missing:
        raise OdsError(f"{path}, sheet '{sheet.name}': missing column(s): {', '.join(missing)}")


# ---------------------------------------------------------------- writing

@dataclass
class Column:
    title: str
    width_cm: float = 2.5
    align: str | None = None      # "center", "end", ... (None = LibreOffice default)


def _add_text(p: P, text: str) -> None:
    """Add text to a paragraph, preserving runs of spaces."""
    buf = ""
    i = 0
    while i < len(text):
        if text[i] == " " and (i == 0 or text[i - 1] == " " or i + 1 < len(text) and text[i + 1] == " "):
            j = i
            while j < len(text) and text[j] == " ":
                j += 1
            if buf:
                p.addText(buf)
                buf = ""
            p.addElement(S(c=j - i))
            i = j
            continue
        buf += text[i]
        i += 1
    if buf:
        p.addText(buf)


def _make_cell(value: Any, style=None) -> TableCell:
    kwargs = {}
    if style is not None:
        kwargs["stylename"] = style
    if value is None or value == "":
        return TableCell(**kwargs)
    if isinstance(value, bool):
        if not value:
            return TableCell(**kwargs)
        value = "x"
    if isinstance(value, (int, float)):
        cell = TableCell(valuetype="float", value=str(value), **kwargs)
        shown = str(int(value)) if float(value).is_integer() else str(value)
        cell.addElement(P(text=shown))
        return cell
    cell = TableCell(valuetype="string", **kwargs)
    for line in str(value).split("\n"):
        p = P()
        _add_text(p, line)
        cell.addElement(p)
    return cell


def write_sheets(path: Path, sheets: Sequence[tuple[str, Sequence[Column], Sequence[Sequence[Any]]]],
                 landscape: bool = False) -> None:
    """Write one or more sheets. Each sheet is (name, columns, rows).

    The header row is repeated on every printed page. With ``landscape``, sheets print in
    landscape orientation, scaled to the page width.
    """
    doc = OpenDocumentSpreadsheet()
    table_style = None
    if landscape:
        layout = PageLayout(name="LandscapeLayout")
        layout.addElement(PageLayoutProperties(
            printorientation="landscape", pagewidth="29.7cm", pageheight="21cm",
            margintop="1cm", marginbottom="1cm", marginleft="1cm", marginright="1cm", scaletox="1"))
        doc.automaticstyles.addElement(layout)
        doc.masterstyles.addElement(MasterPage(name="Landscape", pagelayoutname=layout))
        table_style = Style(name="ta1", family="table", masterpagename="Landscape")
        table_style.addElement(TableProperties(display="true"))
        doc.automaticstyles.addElement(table_style)
    align_styles: dict[str, Style] = {}

    def align_style(align: str | None):
        if align is None:
            return None
        if align not in align_styles:
            st = Style(name=f"al{len(align_styles) + 1}", family="table-cell")
            st.addElement(ParagraphProperties(textalign=align))
            doc.automaticstyles.addElement(st)
            align_styles[align] = st
        return align_styles[align]

    header_style = Style(name="Header", family="table-cell")
    header_style.addElement(TextProperties(fontweight="bold"))
    header_style.addElement(ParagraphProperties(textalign="center"))
    doc.automaticstyles.addElement(header_style)

    col_styles: dict[float, Style] = {}

    def col_style(width: float) -> Style:
        if width not in col_styles:
            st = Style(name=f"co{len(col_styles) + 1}", family="table-column")
            st.addElement(TableColumnProperties(columnwidth=f"{width}cm"))
            doc.automaticstyles.addElement(st)
            col_styles[width] = st
        return col_styles[width]

    for name, columns, rows in sheets:
        table = Table(name=name, **({"stylename": table_style} if table_style else {}))
        for c in columns:
            table.addElement(TableColumn(stylename=col_style(c.width_cm)))
        header_rows = TableHeaderRows()
        tr = TableRow()
        for c in columns:
            tr.addElement(_make_cell(c.title, header_style))
        header_rows.addElement(tr)
        table.addElement(header_rows)
        styles = [align_style(c.align) for c in columns]
        for row in rows:
            tr = TableRow()
            values = list(row) + [None] * (len(columns) - len(row))
            for v, st in zip(values, styles + [None] * (len(values) - len(styles))):
                tr.addElement(_make_cell(v, st))
            table.addElement(tr)
        doc.spreadsheet.addElement(table)

    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    doc.save(str(tmp))
    tmp.replace(path)


def write_sheet(path: Path, name: str, columns: Sequence[Column], rows: Sequence[Sequence[Any]]) -> None:
    write_sheets(path, [(name, columns, rows)])

import re
from dataclasses import dataclass

from bs4 import Tag

from src.parsing.models import Cell, CellType

# TE, TU는 DART 전용 데이터 셀
CELL_TAGS = ["td", "th", "te", "tu"]

_NUM = r"(?:\d[\d,]*(?:\.\d+)?|\.\d+)"
_NUMBER_RE = re.compile(rf"[△▲\-−+]?\s*{_NUM}|\(\s*[△▲\-−]?\s*{_NUM}\s*\)")
_PERCENT_RE = re.compile(
    rf"[△▲\-−+]?\s*{_NUM}\s*%|\(\s*[△▲\-−]?\s*{_NUM}\s*%?\s*\)\s*%?"
)
_EMPTY_RE = re.compile(r"[-−–—ㅡ]*")
_DATE_RES = [
    re.compile(r"\d{4}\s*년(?:\s*\d{1,2}\s*월(?:\s*말|\s*초)?(?:\s*\d{1,2}\s*일)?)?(?:\s*말)?"),
    re.compile(r"(?:19|20)\d{2}\s*[.\-/]\s*(?:0?[1-9]|1[0-2])(?:\s*[.\-/]\s*\d{1,2})?\.?"),
]
_PERIOD_RE = re.compile(
    r"제\s*\d+\s*(?:기|분기|반기).*|(?:당|전|전전)(?:기|분기|반기)(?:말|초)?|.*\d+\s*개월.*|누적"
)
# 행 라벨이나 열 이름에 적힌 자기 단위. 예: "주당이익(원)", "연이자율(%)"
_OWN_UNIT_RE = re.compile(r"[(（](명|주|천주|%|원|천원|백만원|억원|조원|회|건|개|년|개월|일|배|톤|대|시간)[)）]")
# 금액이 아닌 항목. 공백을 지운 글자에 맞춘다.
_NON_MONEY_RE = re.compile(r"직원수|인원|근로자수|주식수|주식의수|발행주식|수량|횟수|건수|개수|근속|연령")
# 비율 항목: 라벨 조각이 "율"로 끝날 때만 본다(뒤의 각주 괄호는 허용).
# "이자율스왑계약", "세율에 따른 법인세비용", "증감(률) / 금액"은 금액이고 환율, 법률도 금액 항목일 수 있다
_RATIO_RE = re.compile(r"(?<![환법])[율률](?:\([^)]*\))*$")
_PER_SHARE_RE = re.compile(r"주당")  # 주당 금액은 원 단위다. 표 단위가 백만원 등일 때만 단위를 비운다


@dataclass
class RawTable:
    header: list[str]
    rows: list[list[str]]


def clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("　", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n[ \n]*", "\n", text)
    return text.strip()


def build_grid(table: Tag) -> tuple[list[list[str]], list[bool]]:
    grid: list[list[str]] = []
    is_head: list[bool] = []
    pending: dict[int, tuple[str, int]] = {}  # 열 번호 -> (값, 남은 행 수)
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = [c for c in tr.find_all(CELL_TAGS) if c.find_parent("tr") is tr]
        row: list[str] = []
        col = next_cell = 0
        while next_cell < len(cells) or _pending_from(pending, col):
            value, remaining = pending.get(col, ("", 0))
            if remaining > 0:
                row.append(value)
                pending[col] = (value, remaining - 1)
                col += 1
                continue
            if next_cell >= len(cells):  # 셀은 떨어졌지만 오른쪽에 병합 셀이 남았으면 빈칸으로 채운다
                row.append("")
                col += 1
                continue
            cell = cells[next_cell]
            next_cell += 1
            text = clean(cell.get_text(" "))
            colspan = _span(cell, "colspan")
            rowspan = _span(cell, "rowspan")
            for offset in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col + offset] = (text, rowspan - 1)
            col += colspan
        if not any(row):
            continue
        grid.append(row)
        is_head.append(
            tr.find_parent("thead") is not None
            or (bool(cells) and all(c.name == "th" for c in cells))
        )
    return grid, is_head


# 이 열부터 오른쪽에 아직 채울 병합 셀이 남았는지
def _pending_from(pending: dict[int, tuple[str, int]], col: int) -> bool:
    return any(c >= col and remaining > 0 for c, (_, remaining) in pending.items())


# 테두리가 있는 표만 데이터 표다. 테두리 없는 표는 제목, 단위, 기준일을 담는 레이아웃이다.
def is_data_table(table: Tag, grid: list[list[str]]) -> bool:
    border = table.get("border")
    if border is not None:
        return str(border) != "0"
    return len(grid) >= 2 and max(len(row) for row in grid) >= 2


def split_table(grid: list[list[str]], is_head: list[bool]) -> RawTable:
    head_rows = 0
    while head_rows < len(grid) and is_head[head_rows]:
        head_rows += 1
    if head_rows == 0 and len(grid) > 1:
        head_rows = 1  # THEAD가 없으면 첫 행을 헤더로 본다

    width = max(len(row) for row in grid)
    header: list[str] = []
    if head_rows:
        for col in range(width):
            parts: list[str] = []
            for row in grid[:head_rows]:
                value = row[col] if col < len(row) else ""
                if value and (not parts or parts[-1] != value):
                    parts.append(value)
            header.append(" / ".join(parts))
    rows = [row + [""] * (width - len(row)) for row in grid[head_rows:]]
    return _promote_date_rows(header, rows)


# 라벨이 비어 있고 값이 전부 날짜·기간인 첫 본문 행은 헤더의 일부다.
def _promote_date_rows(header: list[str], rows: list[list[str]]) -> RawTable:
    header = list(header)
    while rows and header and not rows[0][0]:
        values = [v for v in rows[0][1:] if v]
        if not values or not all(is_date(v) or _PERIOD_RE.fullmatch(v) for v in values):
            break
        for col, value in enumerate(rows[0]):
            if value and value not in header[col]:
                header[col] = f"{header[col]} / {value}" if header[col] else value
        rows = rows[1:]
    return RawTable(header=header, rows=rows)


def cell_type(raw: str) -> CellType:
    value = raw.strip()
    if _EMPTY_RE.fullmatch(value):
        return "empty"
    if is_date(value):
        return "date"
    if _NUMBER_RE.fullmatch(value):
        return "number"
    if _PERCENT_RE.fullmatch(value):
        return "percent"
    return "text"


def make_cells(table: RawTable, unit: str | None) -> list[list[Cell]]:
    result: list[list[Cell]] = []
    for row in table.rows:
        cells: list[Cell] = []
        for col, raw in enumerate(row):
            kind = cell_type(raw)
            cells.append(
                Cell(
                    row=row[0] if col else "",
                    column=table.header[col] if col < len(table.header) else "",
                    raw=raw,
                    type=kind,
                    unit=_cell_unit(unit, row[0], table.header[col] if col < len(table.header) else "")
                    if kind == "number"
                    else None,
                )
            )
        result.append(cells)
    return result


# 표 단위가 하나여도 행 라벨이나 열 이름이 다른 단위나 금액 아닌 항목을 가리키면 단위를 모른다고 본다.
def _cell_unit(unit: str | None, label: str, column: str) -> str | None:
    if unit is None:
        return None
    text = re.sub(r"\s+", "", f"{label}|{column}")
    if (own := _OWN_UNIT_RE.search(text)) and own.group(1) != re.sub(r"\s+", "", unit):
        return None
    if own or not _is_money(unit):
        return unit
    if _NON_MONEY_RE.search(text) or (unit != "원" and _PER_SHARE_RE.search(text)):
        return None
    if _is_ratio(label, column):
        return None
    return unit


# 행 라벨의 조각들과 열 이름의 마지막 조각(실제 열)만 본다.
def _is_ratio(label: str, column: str) -> bool:
    parts = [*re.split(r"[/,]", label), column.split("/")[-1]]
    return any(_RATIO_RE.search(re.sub(r"\s+", "", part)) for part in parts)


def _is_money(unit: str) -> bool:
    return "원" in unit or "$" in unit or "달러" in unit


def is_date(value: str) -> bool:
    return any(pattern.fullmatch(value) for pattern in _DATE_RES)


def _span(cell: Tag, name: str) -> int:
    try:
        return max(int(cell.get(name, 1) or 1), 1)
    except ValueError:
        return 1

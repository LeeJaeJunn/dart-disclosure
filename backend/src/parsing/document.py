import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from src.parsing.models import (
    Basis,
    BasisSource,
    ParsedDocument,
    ParsedSection,
    ParsedTable,
    TableBlock,
    TextBlock,
)
from src.parsing.tables import (
    RawTable,
    build_grid,
    clean,
    is_data_table,
    is_date,
    make_cells,
    split_table,
)

PARSER_VERSION = "p6"

_CONTAINER_TAGS = {"body", "document", "part", "div", "library", "html"}
_METADATA_TAGS = {"document-name", "formula-version", "company-name", "summary"}  # 문서 정보이지 본문이 아니다
_UNIT_RE = re.compile(r"단\s*위\s*[:：]\s*([^)\]）]+)")
_UNIT_ONLY_RE = re.compile(r"[(\[]?\s*단\s*위\s*[:：][^)\]）]*[)\]）]?")
_AS_OF_RE = re.compile(r"기준일\s*[:：]\s*([^)）]+)")
_PERIOD_LABEL_RE = re.compile(r"(?:당|전|전전)(?:기|분기|반기)(?:말|초)?")
_STATEMENT_PERIOD_RE = re.compile(r"제\s*\d+\s*(?:기|분기|반기)\b.*")
_NOTE_RE = re.compile(r"\s*(?:※|\*|\[?△|\[?▲|<?주\s*\d*\)|\(주\s*\d*\)|\[주)")
_XBRL_RE = re.compile(r"\{XBRL\}[A-Z]+_([CS])(?:\d|_|$)")
_CONSOLIDATED_RE = re.compile(r"요약연결|연결\s*(?:기준|재무|손익|포괄|자본변동|현금흐름)")
_SEPARATE_RE = re.compile(r"요약별도|별도\s*(?:기준|재무|손익|포괄|자본변동|현금흐름)")
_SEPARATE_SECTION_RE = re.compile(r"\d+\.\s*재무제표(?:\s*주석)?")
# 개요 번호(1. 가. (1) 1) ① (가))나 괄호 제목([ ] < > 【 】)으로 시작하는 줄
_HEADING_RE = re.compile(
    r"\s*(?:[IVXⅠ-Ⅻ]+\.|\d+(?:-\d+)*\.(?!\d)|[가-하]\.|\(\d+\)|\d+\)|[①-⑳]|\([가-하]\)|[가-하]\)"
    r"|\[[^\]]+\]|<[^>]+>|【[^】]+】)"
)

_MAX_CONTEXT_ITEMS = 4
_MAX_CONTEXT_TEXT = 120
_MAX_CONTEXT_LAYOUT = 200
_MAX_LAYOUT_TITLE = 80
_MAX_TEXT_TITLE = 40
_SENTENCE_END_RE = re.compile(r"(?:다\.?|며,?|고,?|여,?|서,?)\s*$")


@dataclass
class _Group:
    title: str | None
    xbrl_code: str | None


@dataclass
class _Text:
    text: str
    consumed: bool = False


@dataclass
class _Layout:
    cells: list[str]
    text: str
    consumed: bool = False


@dataclass
class _Table:
    raw: RawTable
    group: _Group | None
    parsed: ParsedTable | None = None


_Item = _Text | _Layout | _Table


@dataclass
class _Node:
    title: str
    level: int
    parent: "_Node | None" = None
    items: list[_Item] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)

    @property
    def path(self) -> list[str]:
        node: _Node | None = self
        titles: list[str] = []
        while node is not None and node.level > 0:
            titles.append(node.title)
            node = node.parent
        return list(reversed(titles))


def parse_document(xml: str) -> ParsedDocument:
    xml = re.sub(r"&(cr|crlf|nbsp);", " ", xml)  # DART 전용 엔티티
    xml = re.sub(r"<\?xml[^>]*\?>", "", xml)
    soup = BeautifulSoup(xml, "lxml")
    root = _Node(title="ROOT", level=0)
    _build(soup.find("body") or soup, root)
    return ParsedDocument(parser_version=PARSER_VERSION, root=_finish(root))


def _build(node: Tag, parent: _Node) -> None:
    for child in node.children:
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name.startswith("section"):
            section = _section_node(child, parent)
            parent.children.append(section)
            for sub in child.children:
                _collect(sub, None, section.items)
            _build(child, section)
        elif name in _CONTAINER_TAGS or _has_section(child):
            _build(child, parent)
        elif parent.level == 0 and name not in _METADATA_TAGS:  # 표지처럼 섹션 밖에 있는 내용도 보존한다
            _collect(child, None, parent.items)


def _section_node(tag: Tag, parent: _Node) -> _Node:
    match = re.match(r"section-?(\d+)", tag.name.lower())
    level = int(match.group(1)) if match else parent.level + 1
    title_tag = tag.find("title", recursive=False) or tag.find("title")
    title = re.sub(r"\s+", " ", clean(title_tag.get_text(" "))) if title_tag else "(제목 없음)"
    return _Node(title=title, level=level, parent=parent)


def _has_section(tag: Tag) -> bool:
    return tag.find(lambda t: t.name and t.name.lower().startswith("section")) is not None


# 섹션 안의 내용을 문서 순서대로 항목으로 만든다.
def _collect(node, group: _Group | None, items: list[_Item]) -> None:
    if not isinstance(node, Tag):
        if type(node) is NavigableString and (text := clean(str(node))):
            items.append(_Text(text))
        return

    name = node.name.lower()
    if name.startswith("section"):
        return
    if name == "title":
        if group is not None and (text := clean(node.get_text(" "))):
            items.append(_Text(text))
        return
    if name == "table":
        _collect_table(node, group, items)
    elif name == "table-group":
        title_tag = node.find("title", recursive=False)
        aclass = node.get("aclass") or ""
        new_group = _Group(
            title=clean(title_tag.get_text(" ")) if title_tag else None,
            xbrl_code=aclass if aclass.startswith("{XBRL}") else None,
        )
        for sub in node.children:
            _collect(sub, new_group, items)
    elif name in _CONTAINER_TAGS or _has_section(node) or node.find("table") is not None:
        for sub in node.children:
            _collect(sub, group, items)
    elif text := clean(node.get_text(" ")):
        items.append(_Text(text))


def _collect_table(tag: Tag, group: _Group | None, items: list[_Item]) -> None:
    grid, is_head = build_grid(tag)
    if not grid:
        return
    if is_data_table(tag, grid):
        items.append(_Table(raw=split_table(grid, is_head), group=group))
        return
    lines = [_unique(row) for row in grid]
    cells = [cell for line in lines for cell in line]
    items.append(_Layout(cells=cells, text="\n".join(" ".join(line) for line in lines)))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _finish(node: _Node) -> ParsedSection:
    path = node.path
    _link_tables(node.items, path)
    blocks: list[TextBlock | TableBlock] = []
    for item in node.items:
        if isinstance(item, _Table):
            blocks.append(TableBlock(table=item.parsed))
        elif not item.consumed:
            blocks.append(TextBlock(text=item.text))
    return ParsedSection(
        title=node.title,
        level=node.level,
        path=path,
        blocks=blocks,
        children=[_finish(child) for child in node.children],
    )


# 표 앞의 제목·단위·기준일과 표 뒤의 안내 문구를 해당 표에 연결한다.
def _link_tables(items: list[_Item], path: list[str]) -> None:
    pending: list[_Text | _Layout] = []
    last_table: ParsedTable | None = None
    right_after_table = False

    for item in items:
        if isinstance(item, _Table):
            item.parsed = _make_table(item, pending, path)
            last_table = item.parsed
            pending = []
            right_after_table = True
        elif right_after_table and last_table and _is_note(item.text):
            last_table.notes.extend(_note_parts(item))
            if isinstance(item, _Layout):
                item.consumed = True
        else:
            right_after_table = False
            pending.append(item)


def _is_note(text: str) -> bool:
    return not _UNIT_RE.search(text) and (bool(_NOTE_RE.match(text)) or "부(-)" in text)


def _note_parts(item: _Text | _Layout) -> list[str]:
    return list(item.cells) if isinstance(item, _Layout) else [item.text]


def _make_table(item: _Table, pending: list[_Text | _Layout], path: list[str]) -> ParsedTable:
    chain = _context_chain(pending)
    unit_raw = as_of = period_label = title = None
    notes: list[str] = []

    for context in reversed(chain):
        used = False
        if unit_raw is None and (match := _UNIT_RE.search(context.text)):
            unit_raw = re.sub(r"\s+", " ", match.group(1)).strip()
            used = True
        if as_of is None and (match := _AS_OF_RE.search(context.text)):
            as_of = re.sub(r"\s+", " ", match.group(1)).strip()
            used = True
        if isinstance(context, _Layout):
            if period_label is None:
                period_label = next(
                    (c for c in context.cells if _PERIOD_LABEL_RE.fullmatch(c)), None
                )
                used = used or period_label is not None
            if not _UNIT_RE.search(context.text) and _is_note(context.text):
                notes = _note_parts(context) + notes
                context.consumed = True
                continue
        if title is None and (title := _title_from(context)):
            used = True
        if isinstance(context, _Layout) and used:
            context.consumed = True
        elif isinstance(context, _Text) and _UNIT_ONLY_RE.fullmatch(context.text):
            context.consumed = True

    group = item.group
    title = title or (group.title if group else None)
    context_before = [context.text for context in chain]
    basis, basis_source = _basis(group, path, [title or "", *context_before])
    unit = unit_raw if unit_raw and not re.search(r"[,，/·]", unit_raw) else None
    return ParsedTable(
        title=title,
        group_title=group.title if group else None,
        xbrl_code=group.xbrl_code if group else None,
        unit_raw=unit_raw,
        as_of=as_of,
        period_label=period_label,
        basis=basis,
        basis_source=basis_source,
        context_before=context_before,
        notes=notes,
        header=item.raw.header,
        rows=make_cells(item.raw, unit),
    )


# 표 바로 앞에 이어진 짧은 문단과 레이아웃만 문맥으로 본다.
# 소제목을 만나면 그 위로는 연속된 상위 소제목만 포함한다. 소제목 위의 글은 앞 내용에 속한다.
def _context_chain(pending: list[_Text | _Layout]) -> list[_Text | _Layout]:
    chain: list[_Text | _Layout] = []
    seen_heading = False
    for item in reversed(pending):
        if len(chain) >= _MAX_CONTEXT_ITEMS:
            break
        limit = _MAX_CONTEXT_LAYOUT if isinstance(item, _Layout) else _MAX_CONTEXT_TEXT
        heading = _is_heading(item)
        if seen_heading and not heading:
            break
        if len(item.text) > limit and not _UNIT_RE.search(item.text):
            break
        chain.append(item)
        seen_heading = seen_heading or heading
    chain.reverse()
    return chain


def _is_heading(item: _Text | _Layout) -> bool:
    if _UNIT_ONLY_RE.fullmatch(item.text.strip()) or _is_note(item.text):
        return False  # "(단위 : 원)", "[△는 부(-)의 값임]"은 소제목이 아니다
    return bool(_HEADING_RE.match(item.text))


def _title_from(context: _Text | _Layout) -> str | None:
    # 기준일은 "(기준일 :", "2023년 12월 31일", ")"처럼 칸이 나뉘어 제목으로 오인되기 쉽다.
    if _AS_OF_RE.search(context.text) or _SENTENCE_END_RE.search(context.text):
        return None
    is_layout = isinstance(context, _Layout)
    lines = context.cells if is_layout else context.text.split("\n")
    max_length = _MAX_LAYOUT_TITLE if is_layout else _MAX_TEXT_TITLE
    for line in lines:
        text = _UNIT_ONLY_RE.sub("", line).strip()
        if (
            re.search(r"[0-9A-Za-z가-힣]", text)
            and len(text) <= max_length
            and not _SENTENCE_END_RE.search(text)
            and not is_date(text)
            and not _PERIOD_LABEL_RE.fullmatch(text)
            and not _STATEMENT_PERIOD_RE.fullmatch(text)
            and not _NOTE_RE.match(text)
        ):
            return text
    return None


def _basis(
    group: _Group | None, path: list[str], texts: list[str]
) -> tuple[Basis, BasisSource | None]:
    if group and group.xbrl_code and (match := _XBRL_RE.search(group.xbrl_code)):
        return ("consolidated" if match.group(1) == "C" else "separate"), "xbrl"

    if any("연결재무제표" in title for title in path):
        return "consolidated", "section_title"
    if any(_SEPARATE_SECTION_RE.fullmatch(title) for title in path):
        return "separate", "section_title"

    joined = " ".join(text for text in texts if len(text) <= _MAX_CONTEXT_TEXT)
    consolidated = bool(_CONSOLIDATED_RE.search(joined))
    separate = bool(_SEPARATE_RE.search(joined))
    if consolidated != separate:
        return ("consolidated" if consolidated else "separate"), "preceding_heading"
    return "unknown", None

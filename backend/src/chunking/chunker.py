import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from src.chunking.models import (
    Chunk,
    ChunkedDocument,
    ChunkingConfig,
    FilingInfo,
    TableRecord,
)
from src.parsing.models import Cell, ParsedDocument, ParsedSection, ParsedTable

_SECTION_TAGS = [
    (r"회사의 개요|연혁|자본금|주식의 총수|정관", "company"),
    (r"사업의 개요|주요 제품|원재료|생산|매출|수주|위험관리|파생|연구개발|기타 참고", "business"),
    (r"재무에 관한|요약재무|연결재무|재무제표|주석|배당|증권의 발행", "financial"),
    (r"이사회|감사제도|주주총회|의결권", "governance"),
    (r"임원|직원|보수", "people"),
    (r"주주에 관한|최대주주|소액주주", "shareholder"),
    (r"계열회사|타법인출자", "affiliates"),
    (r"이해관계자|대주주.*거래|제재|소송", "related"),
]
_BASIS_LABELS = {"consolidated": "연결", "separate": "별도"}
_KV_TYPES = {"number", "percent", "date"}
_TOC_LINE_RE = re.compile(r".+-{5,}\s*\d+\s*")  # 예: "4. 매출 및 수주상황 ------ 34"


@dataclass
class _Section:
    section_id: str
    path_text: str
    crumb: str
    meta: dict[str, Any]


def chunk_document(
    document: ParsedDocument, filing: FilingInfo, config: ChunkingConfig | None = None
) -> ChunkedDocument:
    config = config or ChunkingConfig()
    chunks: list[Chunk] = []
    tables: list[TableRecord] = []
    occurrences: Counter[str] = Counter()
    section_ids: dict[str, str] = {}

    for order, parsed in enumerate(_walk(document.root)):
        if parsed.level == 0 and not parsed.blocks:
            continue
        section = _make_section(parsed, filing, occurrences, section_ids, order)
        records: list[TableRecord] = []
        for block in parsed.blocks:
            if block.kind == "table":
                records.append(_table_record(block.table, section, filing, len(records)))
        tables += records

        chunks.append(_section_chunk(parsed, section, filing, records))
        chunks += _text_chunks(parsed, section, filing, config)
        for record in records:
            chunks += _table_chunks(record, section, config)

    return ChunkedDocument(
        filing=filing,
        parser_version=document.parser_version,
        chunker_version=_version(config),
        config=config,
        tables=tables,
        chunks=chunks,
    )


def _version(config: ChunkingConfig) -> str:
    digest = hashlib.md5(json.dumps(config.model_dump(), sort_keys=True).encode()).hexdigest()
    return f"c3-{digest[:6]}"


def _make_id(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:16]


def _walk(section: ParsedSection) -> Iterator[ParsedSection]:
    yield section
    for child in section.children:
        yield from _walk(child)


def _make_section(
    parsed: ParsedSection,
    filing: FilingInfo,
    occurrences: Counter[str],
    section_ids: dict[str, str],
    section_order: int,
) -> _Section:
    path = parsed.path or ["표지"]
    path_text = " > ".join(path)
    # 같은 경로의 섹션이 또 나오면 ID가 겹치지 않게 순번을 넣는다.
    repeat = occurrences[path_text]
    occurrences[path_text] += 1
    section_id = _make_id(filing.rcept_no, *path, *([str(repeat)] if repeat else []))
    section_ids[path_text] = section_id

    meta = {
        "corp_code": filing.corp_code,
        "corp_name": filing.corp_name,
        "report_nm": filing.report_nm,
        "report_type": filing.report_type,
        "period": filing.period,
        "year": filing.period[:4],
        "rcept_dt": filing.rcept_dt,
        "section_title": path[-1],
        "section_level": parsed.level,
        "section_order": section_order,
        "parent_section_id": section_ids.get(" > ".join(path[:-1])),
        "tags": _tags(path),
    }
    crumb = f"[{filing.corp_name} | {filing.report_type} {filing.period} | {path_text}]"
    return _Section(section_id=section_id, path_text=path_text, crumb=crumb, meta=meta)


def _tags(path: list[str]) -> list[str]:
    joined = " ".join(path)
    return [tag for pattern, tag in _SECTION_TAGS if re.search(pattern, joined)] or ["etc"]


def _table_record(
    table: ParsedTable, section: _Section, filing: FilingInfo, table_index: int
) -> TableRecord:
    return TableRecord(
        **table.model_dump(),
        table_id=_make_id(section.section_id, "table", str(table_index)),
        rcept_no=filing.rcept_no,
        section_id=section.section_id,
        table_index=table_index,
    )


# 위키 경로가 읽는 섹션 페이지. 긴 표는 발췌 때 뒷부분이 잘리므로 안내 문구를 표 위에 둔다.
def _section_chunk(
    parsed: ParsedSection, section: _Section, filing: FilingInfo, records: list[TableRecord]
) -> Chunk:
    lines = [f"# {section.path_text}", ""]
    tables = iter(records)
    for block in parsed.blocks:
        if block.kind == "text":
            lines += [block.text, ""]
            continue
        record = next(tables)
        width = _table_width(record)
        lines.append(f"### 표 {record.table_index + 1}")
        if context := _context_line(record):
            lines.append(context)
        lines += record.notes
        lines += [_markdown(record, list(range(width)), record.rows), ""]
    page = "\n".join(lines).rstrip()
    return Chunk(
        chunk_id=_make_id(section.section_id, "section"),
        rcept_no=filing.rcept_no,
        section_id=section.section_id,
        section_path=section.path_text,
        kind="section",
        embed=False,
        text=page,
        raw=page,
        meta=section.meta,
    )


def _split_paragraphs(text: str, limit: int) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in (p.strip() for p in re.split(r"\n+", text)):
        if _TOC_LINE_RE.fullmatch(paragraph):  # 목차 줄은 검색 대상에서 뺀다. 위키 페이지에는 남는다
            continue
        if len(paragraph) <= limit:
            if paragraph:
                paragraphs.append(paragraph)
            continue
        for sentence in re.split(r"(?<=[.다]\s)", paragraph):
            sentence = sentence.strip()
            paragraphs += [sentence[i : i + limit] for i in range(0, len(sentence), limit)]
    return paragraphs


def _text_chunks(
    parsed: ParsedSection, section: _Section, filing: FilingInfo, config: ChunkingConfig
) -> list[Chunk]:
    text = "\n".join(block.text for block in parsed.blocks if block.kind == "text")
    chunks: list[Chunk] = []
    buffer: list[str] = []
    length = 0
    has_new = False  # 겹침 문단만 남은 조각은 청크로 만들지 않는다

    def flush() -> None:
        nonlocal buffer, length, has_new
        if not has_new:
            return
        body = "\n".join(buffer)
        index = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=_make_id(section.section_id, "text", str(index)),
                rcept_no=filing.rcept_no,
                section_id=section.section_id,
                section_path=section.path_text,
                kind="text",
                embed=True,
                text=f"{section.crumb}\n{body}"[: config.max_embed_chars],
                raw=body,
                meta={**section.meta, "chunk_index": index},
            )
        )
        buffer = buffer[-config.overlap_paragraphs :] if config.overlap_paragraphs else []
        length = sum(map(len, buffer))
        has_new = False

    for paragraph in _split_paragraphs(text, config.max_paragraph_chars):
        if has_new and length + len(paragraph) > config.target_chars:
            flush()
        buffer.append(paragraph)
        length += len(paragraph)
        has_new = True
        if length > config.max_chars:
            flush()
    flush()
    return chunks


def _table_width(table: ParsedTable) -> int:
    return max([len(table.header), *(len(row) for row in table.rows)], default=0)


# 넓은 표는 첫 열을 고정하고 열 방향으로 나눈다.
def _column_groups(table: ParsedTable, config: ChunkingConfig) -> list[list[int]]:
    width = _table_width(table)
    if width <= config.max_columns:
        return [list(range(width))]
    step = config.max_columns - 1
    return [[0, *range(start, min(start + step, width))] for start in range(1, width, step)]


def _row_groups(rows: list[list[Cell]], config: ChunkingConfig) -> Iterator[tuple[int, list[list[Cell]]]]:
    start = 0
    current: list[list[Cell]] = []
    length = 0
    for row in rows:
        row_length = sum(len(cell.raw) + len(cell.column) + 4 for cell in row) + 20
        if current and (
            length + row_length > config.table_chars
            or len(current) >= config.table_rows_per_chunk
        ):
            yield start, current
            start += len(current)
            current, length = [], 0
        current.append(row)
        length += row_length
    yield start, current


def _table_chunks(record: TableRecord, section: _Section, config: ChunkingConfig) -> list[Chunk]:
    chunks: list[Chunk] = []
    context = _context_line(record)
    for col_group, columns in enumerate(_column_groups(record, config)):
        picked = [[row[col] for col in columns if col < len(row)] for row in record.rows]
        for group, (start, rows) in enumerate(_row_groups(picked, config)):
            markdown = _markdown(record, columns, rows)
            kv = _linearize(rows)
            meta = {
                **section.meta,
                "table_index": record.table_index,
                "row_start": start,
                "col_group": col_group,
            }
            raw = "\n".join(part for part in (context, markdown) if part)
            location = f"(표 {record.table_index + 1}, 행 {start + 1}-{start + len(rows)})"
            chunk_id = _make_id(record.table_id, str(col_group), str(group))
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    rcept_no=record.rcept_no,
                    section_id=section.section_id,
                    section_path=section.path_text,
                    kind="table",
                    table_id=record.table_id,
                    embed=not kv and _has_values(rows),
                    text=f"{section.crumb}\n{location}\n{raw}"[: config.max_embed_chars],
                    raw=raw,
                    meta=meta,
                )
            )
            if kv:
                kv_raw = "\n".join(part for part in (context, kv) if part)
                chunks.append(
                    Chunk(
                        chunk_id=_make_id(chunk_id, "kv"),
                        rcept_no=record.rcept_no,
                        section_id=section.section_id,
                        section_path=section.path_text,
                        kind="table_kv",
                        table_id=record.table_id,
                        embed=True,
                        text=f"{section.crumb}\n{kv_raw}"[: config.max_embed_chars],
                        raw=kv_raw,
                        meta=meta,
                    )
                )
    return chunks


def _context_line(table: ParsedTable) -> str:
    parts = [
        table.title,
        f"단위: {table.unit_raw}" if table.unit_raw else None,
        _BASIS_LABELS.get(table.basis),
        table.period_label,
        f"기준일: {table.as_of}" if table.as_of else None,
    ]
    return " | ".join(part for part in parts if part)


def _escape(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def _markdown(table: ParsedTable, columns: list[int], rows: list[list[Cell]]) -> str:
    header = [
        table.header[col] if col < len(table.header) else f"col{col + 1}" for col in columns
    ]
    lines = [
        "| " + " | ".join(_escape(value) for value in header) + " |",
        "|" + "---|" * len(columns),
    ]
    for row in rows:
        values = [_escape(cell.raw) for cell in row] + [""] * (len(columns) - len(row))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _has_values(rows: list[list[Cell]]) -> bool:
    return any(
        cell.type != "empty" for row in rows for cell in (row[1:] if len(row) > 1 else row)
    )


# 행(열)=값 문장. 단위는 셀에 확정된 경우에만 붙는다.
def _linearize(rows: list[list[Cell]]) -> str:
    if not any(cell.type in _KV_TYPES for row in rows for cell in row[1:]):
        return ""
    lines: list[str] = []
    for row in rows:
        label = row[0].raw.replace("\n", " ") if row else ""
        pairs: list[str] = []
        for cell in row[1:]:
            if cell.type == "empty":
                continue
            column = f"({cell.column})" if cell.column else ""
            unit = f" {cell.unit}" if cell.unit else ""
            pairs.append(f"{label}{column}={cell.raw.replace('\n', ' ')}{unit}")
        if pairs:
            lines.append("; ".join(pairs))
    return "\n".join(lines)

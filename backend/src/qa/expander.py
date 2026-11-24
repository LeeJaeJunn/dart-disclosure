"""표 확장: 검색된 표 청크(잘린 조각일 수 있음)를 원본 표 전체로 바꾼다.

표는 12행(1,400자) 단위 조각으로 나뉘어 청크가 되므로, 검색된 표 청크는 표의 일부일 수 있다.
    1. 표 청크(table, table_kv)의 원본 표를 filing_table에서 조회한다 (retriever.get_tables)
    2. 원본 표가 TABLE_CHARS 이하면 그 자리를 원본 표 전체로 바꾼다 (expanded=True)
       넘으면 검색된 조각 그대로 둔다 (큰 목록형 표를 통째로 넣지 않는다)
    3. 같은 표가 또 나오면 앞 순위 하나만 남긴다. 빈 자리는 채우지 않는다
    4. 근거 합계가 CONTEXT_CHARS를 넘으면 순위가 낮은 원본 표부터 검색된 조각으로 되돌린다

근거 정보(chunk_id, 공시, 목차 경로, DART 링크)는 검색된 청크의 값을 그대로 쓴다.
"""

from typing import Any

from src.qa.answerer import MAX_CHUNK_CHARS
from src.qa.retriever import get_tables
from src.qa.schemas import RetrievedChunk

TABLE_CHARS = 4000  # 원본 표로 바꾸는 최대 크기 (render_table 결과 기준, 약 2,600 토큰)
# 2차 LLM에 넣는 근거 합계 상한 (약 8,000 토큰). 표를 모두 되돌리면 최대 MAX_CHUNK_CHARS × 5 = 10,000자라
# 근거를 빼지 않고도 항상 이 안에 들어간다.
CONTEXT_CHARS = 12000

_BASIS_LABELS = {"consolidated": "연결", "separate": "별도"}


async def expand_tables(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """표 청크를 원본 표 전체로 바꾼다. 순서는 검색 순위 그대로."""
    table_ids = list(dict.fromkeys(c.table_id for c in chunks if c.table_id))
    tables = await get_tables(table_ids)
    rendered = {table_id: render_table(table) for table_id, table in tables.items()}

    out: list[RetrievedChunk] = []
    originals: dict[int, RetrievedChunk] = {}  # out 위치 → 원본 표로 바꾸기 전 청크 (되돌릴 때 사용)
    used: set[str] = set()  # 이미 원본 표로 넣은 table_id
    for chunk in chunks:
        table_id = chunk.table_id
        table = rendered.get(table_id) if table_id else None
        if table_id is None or table is None or len(table) > TABLE_CHARS:
            out.append(chunk)  # 표가 아니거나, 원본 표가 너무 크면 검색된 조각 그대로
            continue
        if table_id in used:
            continue  # 같은 표의 다른 조각: 앞 순위에 이미 표 전체가 있다
        used.add(table_id)
        originals[len(out)] = chunk
        out.append(chunk.model_copy(update={"raw": table, "expanded": True}))
    return _fit_budget(out, originals)


def prompt_chars(chunk: RetrievedChunk) -> int:
    """이 근거가 2차 LLM에 들어가는 길이 (answerer.build_context와 같은 규칙)."""
    return len(chunk.raw) if chunk.expanded else min(len(chunk.raw), MAX_CHUNK_CHARS)


def _fit_budget(chunks: list[RetrievedChunk], originals: dict[int, RetrievedChunk]) -> list[RetrievedChunk]:
    """근거 합계가 CONTEXT_CHARS를 넘으면 순위가 낮은 원본 표부터 검색된 조각으로 되돌린다.
    근거 개수와 순서는 그대로다."""
    out = list(chunks)
    for i in sorted(originals, reverse=True):  # 순위가 낮은(뒤쪽) 표부터
        if sum(map(prompt_chars, out)) <= CONTEXT_CHARS:
            break
        out[i] = originals[i]
    return out


def render_table(table: dict[str, Any]) -> str:
    """원본 표 1개 → 문자열. 청크와 같은 형식 (첫 줄 표 정보 + 마크다운 표), 주석은 표 아래에."""
    info = [
        table["title"],
        f"단위: {table['unit_raw']}" if table["unit_raw"] else None,
        _BASIS_LABELS.get(table["basis"]),
        table["period_label"],
        f"기준일: {table['as_of']}" if table["as_of"] else None,
    ]
    header: list[str] = table["header"]
    lines = [
        " | ".join(part for part in info if part),
        "| " + " | ".join(_escape(h) for h in header) + " |",
        "|" + "---|" * len(header),
    ]
    for row in table["cells"]:
        lines.append("| " + " | ".join(_escape(cell["raw"]) for cell in row) + " |")
    lines.extend(table["notes"])
    return "\n".join(line for line in lines if line)


def _escape(value: str) -> str:
    """셀 안의 줄바꿈과 | 가 마크다운 표를 깨지 않게 한다."""
    return value.replace("\n", " ").replace("|", "\\|")

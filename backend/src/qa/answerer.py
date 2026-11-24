"""답변 생성: 질문 + 검색 결과 → LLM → 답변 본문 + 근거 목록.

- 검색 결과에 [1]..[n] 번호를 붙여 LLM에 넘긴다.
  검색 대상이 여럿이면 대상별로 묶고([대상 1], [대상 2]) 번호는 이어서 붙인다.
- sources에는 답변에서 실제로 인용한 번호만 넣는다 (검색됐지만 쓰이지 않은 청크는 제외).
- 공시가 없는 대상의 안내 문장(notice)과 notes는 코드가 답변 맨 앞에 붙인다.
- 검색 결과가 하나도 없으면 LLM을 호출하지 않는다.
"""

import re

from src.llm.models import get_chat_model
from src.qa.prompts import ANSWER_SYSTEM, ANSWER_USER, CONTEXT_ITEM, GROUP_FAILED, GROUP_HEADER
from src.qa.schemas import AskResponse, RetrievedChunk, SearchGroup, Source

NO_EVIDENCE = "질문과 관련된 공시 근거를 찾지 못했습니다. 회사명이나 기간을 넣어 다시 질문해 주세요."

MAX_CHUNK_CHARS = 2000      # 근거 1건이 프롬프트에 들어가는 최대 길이 (긴 표 청크 대비).
                            # 원본 표로 바꾼 근거(expanded)는 expander.TABLE_CHARS 이하라 자르지 않는다
QUOTE_CHARS = 300           # 응답의 근거 발췌(quote) 길이

CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def format_chunk(n: int, c: RetrievedChunk) -> str:
    """근거 1건 → [n] 기업 공시 · 목차 경로 + 원문."""
    raw = c.raw if c.expanded or len(c.raw) <= MAX_CHUNK_CHARS else c.raw[:MAX_CHUNK_CHARS] + "\n...(중략)"
    return CONTEXT_ITEM.format(n=n, corp_name=c.corp_name, report_nm=c.report_nm, section_path=c.section_path, raw=raw)


def build_context(groups: list[SearchGroup]) -> str:
    """검색 결과를 [1]..[n] 번호가 붙은 근거 목록 문자열로 만든다.
    대상이 1개면 묶음 제목 없이 근거만, 여럿이면 대상별 제목 아래에 근거를 둔다 (번호는 이어서)."""
    if len(groups) == 1:
        return "\n\n".join(format_chunk(n, c) for n, c in enumerate(groups[0].chunks, 1))
    parts: list[str] = []
    n = 0
    for i, group in enumerate(groups, 1):
        if not group.chunks:
            parts.append(GROUP_FAILED.format(i=i, notice=group.notice or f"{group.label}: 근거를 찾지 못함"))
            continue
        items = [GROUP_HEADER.format(i=i, label=group.label)]
        for c in group.chunks:
            n += 1
            items.append(format_chunk(n, c))
        parts.append("\n\n".join(items))
    return "\n\n".join(parts)


def cited_numbers(text: str, n_chunks: int) -> list[int]:
    """답변 본문에서 인용된 근거 번호를 찾는다. 범위를 벗어난 번호는 버린다."""
    return sorted({n for n in map(int, CITATION_RE.findall(text)) if 1 <= n <= n_chunks})


def to_source(n: int, c: RetrievedChunk) -> Source:
    quote = c.raw if len(c.raw) <= QUOTE_CHARS else c.raw[:QUOTE_CHARS] + "..."
    return Source(
        n=n,
        chunk_id=c.chunk_id,
        rcept_no=c.rcept_no,
        corp_name=c.corp_name,
        report_nm=c.report_nm,
        rcept_dt=c.rcept_dt,
        section_path=c.section_path,
        quote=quote,
        dart_url=c.dart_url,
    )


def with_notices(text: str, notices: list[str]) -> str:
    """안내 문장들을 답변 맨 앞에 붙인다."""
    return "\n\n".join([*notices, text]) if notices else text


async def answer(question: str, groups: list[SearchGroup], notes: list[str] | None = None) -> AskResponse:
    """검색 결과만 근거로 질문에 답한다.
    notes: 대상별 안내 외에 답변 앞에 붙일 문장 (예: 대상이 너무 많아 일부만 검색함)."""
    notices = [*(notes or []), *(g.notice for g in groups if g.notice)]
    chunks = [c for g in groups for c in g.chunks]  # 번호 순서 (build_context와 같음)
    if not chunks:
        return AskResponse(type="disclosure", answer=with_notices(NO_EVIDENCE, notices), sources=[])

    messages = [
        ("system", ANSWER_SYSTEM),
        ("user", ANSWER_USER.format(context=build_context(groups), question=question)),
    ]

    response = await get_chat_model().ainvoke(messages)

    text = str(response.text)

    sources = [to_source(n, chunks[n - 1]) for n in cited_numbers(text, len(chunks))]
    return AskResponse(type="disclosure", answer=with_notices(text, notices), sources=sources)

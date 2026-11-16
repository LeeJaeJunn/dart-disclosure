"""답변 생성: 질문 + 검색 결과 → LLM → 답변 본문 + 근거 목록.

- 검색 결과에 [1]..[n] 번호를 붙여 LLM에 넘긴다.
- sources에는 답변에서 실제로 인용한 번호만 넣는다 (검색됐지만 쓰이지 않은 청크는 제외).
- 검색 결과가 없으면 LLM을 호출하지 않는다.
"""

import re

from src.llm.models import get_chat_model
from src.qa.prompts import ANSWER_SYSTEM, ANSWER_USER, CONTEXT_ITEM
from src.qa.schemas import AskResponse, RetrievedChunk, Source

NO_EVIDENCE = "질문과 관련된 공시 근거를 찾지 못했습니다. 회사명이나 기간을 넣어 다시 질문해 주세요."

MAX_CHUNK_CHARS = 2000      # 근거 1건이 프롬프트에 들어가는 최대 길이 (긴 표 청크 대비)
QUOTE_CHARS = 300           # 응답의 근거 발췌(quote) 길이

CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def build_context(chunks: list[RetrievedChunk]) -> str:
    """검색 결과를 [1]..[n] 번호가 붙은 근거 목록 문자열로 만든다."""
    items = []
    for n, c in enumerate(chunks, 1):
        raw = c.raw if len(c.raw) <= MAX_CHUNK_CHARS else c.raw[:MAX_CHUNK_CHARS] + "\n...(중략)"
        items.append(CONTEXT_ITEM.format(
            n=n, corp_name=c.corp_name, report_nm=c.report_nm, section_path=c.section_path, raw=raw,
        ))
    return "\n\n".join(items)


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


async def answer(question: str, chunks: list[RetrievedChunk]) -> AskResponse:
    """검색 결과만 근거로 질문에 답한다."""
    if not chunks:
        return AskResponse(type="disclosure", answer=NO_EVIDENCE, sources=[])

    messages = [
        ("system", ANSWER_SYSTEM),
        ("user", ANSWER_USER.format(context=build_context(chunks), question=question)),
    ]

    response = await get_chat_model().ainvoke(messages)

    text = str(response.text)

    sources = [to_source(n, chunks[n - 1]) for n in cited_numbers(text, len(chunks))]
    return AskResponse(type="disclosure", answer=text, sources=sources)

"""기업분석 보고서 생성: 공시 1건(ChunkedDocument) → Analysis (analysis 테이블 1행).

    섹션 정의 (templates.SECTIONS, 공시 종류에 맞는 것만)
     │
     ├─ 일반 섹션 (동시에)  섹션마다:
     │     ① section 청크 중 section_path가 patterns에 맞는 것을 고른다 (검색·임베딩 없음)
     │     ② 긴 목차는 키워드 발췌로 줄인다 (목차당 PAGE_CHARS, 섹션당 CONTEXT_CHARS)
     │     ③ LLM 1회 → SectionDraft (출력이 형식에 맞지 않으면 1회 다시 시도)
     │     ④ 근거 인용문의 숫자, 표의 숫자를 원문과 대조 → sources[].verified, check
     │
     └─ 한눈에 보기 (마지막)  done인 일반 섹션의 결과만 읽고 LLM 1회
     ▼
    Analysis (섹션 순서는 템플릿 순서, 한눈에 보기가 맨 앞)

섹션 상태: done | no_evidence(근거 없음, 화면에서 빠짐) | error(LLM 호출 실패 등, 그 섹션만 실패로 남긴다)
공시 적재 때 메모리에 있는 결과로 만든다 (src/ingest/__main__.py). DB를 읽지 않는다.
"""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import date
from typing import Any, Literal

from src.chunking.models import Chunk, ChunkedDocument, FilingInfo
from src.config import settings
from src.llm.models import get_chat_model
from src.summary import prompts
from src.summary.evidence import excerpt, unverified_table_numbers, verify_evidence
from src.summary.schemas import Analysis, AnalysisSection, AnalysisSource, SectionDraft
from src.summary.templates import (
    CONTEXT_CHARS,
    MAX_PAGES,
    PAGE_CHARS,
    TEMPLATE_ID,
    TEMPLATE_TITLE,
    SectionSpec,
    sections_for,
)

_CITATION_RE = re.compile(r"\[\d+\]")


def analysis_version(report_type: str) -> str:
    """프롬프트, 출력 형식, 섹션 정의, 글자 예산, 모델을 합친 해시.
    하나라도 바뀌면 값이 바뀌어, 저장된 요약이 어느 버전으로 만들어졌는지 알 수 있다."""
    key = json.dumps(
        [
            prompts.SECTION_SYSTEM,
            prompts.SUMMARY_SYSTEM,
            prompts.SECTION_USER,
            prompts.SUMMARY_USER,
            SectionDraft.model_json_schema(),
            [PAGE_CHARS, MAX_PAGES, CONTEXT_CHARS],
            settings.openai_model,
            [asdict(spec) for spec in sections_for(report_type)],
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return "a1." + hashlib.md5(key.encode("utf-8")).hexdigest()[:8]


async def build_analysis(doc: ChunkedDocument) -> Analysis:
    """공시 1건의 기업분석 보고서를 만든다. 섹션 하나가 실패해도 나머지는 만든다."""
    filing = doc.filing
    specs = sections_for(filing.report_type)
    pages = [chunk for chunk in doc.chunks if chunk.kind == "section"]
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "usd": None}

    normal = [spec for spec in specs if not spec.summary]
    results = await asyncio.gather(*(_timed(_section(spec, filing, pages, usage)) for spec in normal))
    by_id = {result.id: result for result in results}
    for spec in specs:
        if spec.summary:
            by_id[spec.id] = await _timed(_summary(spec, filing, results, usage))

    return Analysis(
        rcept_no=filing.rcept_no,
        template=TEMPLATE_ID,
        title=TEMPLATE_TITLE,
        version=analysis_version(filing.report_type),
        model=settings.openai_model,
        parser_version=doc.parser_version,
        chunker_version=doc.chunker_version,
        usage=usage,
        sections=[by_id[spec.id] for spec in specs],
    )


async def _timed(coro) -> AnalysisSection:
    """섹션 1개를 만들고 걸린 시간을 diag에 남긴다."""
    start = time.perf_counter()
    section = await coro
    section.diag["seconds"] = round(time.perf_counter() - start, 2)
    return section


# ---------------------------------------------------------------------------
# 일반 섹션
# ---------------------------------------------------------------------------
async def _section(
    spec: SectionSpec, filing: FilingInfo, pages: list[Chunk], usage: dict[str, Any]
) -> AnalysisSection:
    diag: dict[str, Any] = {}
    try:
        # ① 읽을 목차 고르기. 제목만 있고 본문이 없는 목차(상위 목차 등)는 뺀다
        matched = [p for p in pages if any(pat in p.section_path for pat in spec.patterns) and _has_body(p.raw)]
        matched = matched[:MAX_PAGES]

        # ② 긴 목차 줄이기, 섹션 예산 안에서 근거 블록 만들기
        items: list[tuple[Chunk, str]] = []  # (목차, LLM에 넣은 글자)
        blocks: list[str] = []
        used, trimmed = 0, False
        for page in matched:
            text, cut = excerpt(page.raw, spec.keywords, PAGE_CHARS)
            block = prompts.EVIDENCE_ITEM.format(chunk_id=page.chunk_id, source=_source(filing, page), text=text)
            if used + len(block) > CONTEXT_CHARS:
                trimmed = True
                continue
            items.append((page, text))
            blocks.append(block)
            used += len(block)
            trimmed |= cut
        diag.update(pages_found=len(matched), context_chars=used, trimmed=trimmed)
        if not items:
            return _result(spec, "section", status="no_evidence", diag=diag)

        # ③ LLM
        user = prompts.SECTION_USER.format(
            today=date.today().isoformat(),
            corp_name=filing.corp_name,
            report_nm=filing.report_nm,
            title=spec.title,
            instruction=spec.instruction,
            table_note="" if spec.table else prompts.NO_TABLE_NOTE,
            evidence="\n\n".join(blocks),
        )
        draft = await _ask(prompts.SECTION_SYSTEM, user, usage, diag)

        # ④ 검증
        given = {page.chunk_id: (page, text) for page, text in items}
        sources = [_to_source(n, ev.chunk_id, ev.quote, filing, given) for n, ev in enumerate(draft.evidence, 1)]
        table = draft.table_markdown.strip()
        check = {
            "n_evidence": len(sources),
            "n_unverified": sum(not s.verified for s in sources),
            "table_unverified_numbers": unverified_table_numbers(table, [text for _, text in items]),
        }
        headline, overview = draft.headline.strip(), draft.overview.strip()
        return _result(
            spec,
            "section",
            status="done" if sources and (headline or overview) else "no_evidence",
            headline=headline,
            overview=overview,
            interpretation=_clean(draft.interpretation)[:3],
            watch=_clean(draft.watch)[:2],
            table_markdown=table,
            sources=sources,
            check=check,
            diag=diag,
        )
    except Exception as error:  # noqa: BLE001  한 섹션의 실패가 보고서 전체를 막지 않게 한다
        return _result(spec, "section", status="error", diag=diag, error=f"{type(error).__name__}: {str(error)[:300]}")


def _has_body(raw: str) -> bool:
    """section 청크의 첫 줄(# 목차 경로)을 빼고 내용이 있는지."""
    return bool(raw.split("\n", 1)[1].strip()) if "\n" in raw else False


def _source(filing: FilingInfo, page: Chunk) -> str:
    return f"{filing.corp_name} {filing.report_type}({filing.period}) · {page.section_path}"


def _to_source(
    n: int, chunk_id: str, quote: str, filing: FilingInfo, given: dict[str, tuple[Chunk, str]]
) -> AnalysisSource:
    page, text = given.get(chunk_id, (None, None))
    return AnalysisSource(
        n=n,
        rcept_no=filing.rcept_no,
        rcept_dt=filing.rcept_dt,
        report_nm=filing.report_nm,
        source=_source(filing, page) if page else chunk_id,
        section=page.section_path if page else "",
        period=filing.period,
        quote=quote,
        url=filing.dart_url,
        chunk_id=chunk_id,
        verified=not (problems := verify_evidence(quote, text)),
        problems=problems,
    )


# ---------------------------------------------------------------------------
# 한눈에 보기
# ---------------------------------------------------------------------------
async def _summary(
    spec: SectionSpec, filing: FilingInfo, results: list[AnalysisSection], usage: dict[str, Any]
) -> AnalysisSection:
    diag: dict[str, Any] = {}
    try:
        done = [r for r in results if r.status == "done"]
        diag["sections_used"] = len(done)
        if not done:
            return _result(spec, "summary", status="no_evidence", diag=diag)

        blocks = []
        for r in done:
            lines = [f"## {r.title}", f"특징: {r.headline}", r.overview]
            if r.interpretation:
                lines += ["(해석)", *(f"- {x}" for x in r.interpretation)]
            blocks.append(_CITATION_RE.sub("", "\n".join(lines)))  # 섹션별 근거 번호는 여기서 의미가 없다
        user = prompts.SUMMARY_USER.format(
            corp_name=filing.corp_name,
            report_nm=filing.report_nm,
            instruction=spec.instruction,
            sections="\n\n".join(blocks),
        )
        diag["context_chars"] = len(user)
        draft = await _ask(prompts.SUMMARY_SYSTEM, user, usage, diag)

        headline, overview = draft.headline.strip(), draft.overview.strip()
        return _result(
            spec,
            "summary",
            status="done" if headline or overview else "no_evidence",
            headline=headline,
            overview=overview,
            interpretation=_clean(draft.interpretation)[:3],
            watch=_clean(draft.watch)[:1],
            diag=diag,
        )
    except Exception as error:  # noqa: BLE001  한눈에 보기만 실패로 남긴다
        return _result(spec, "summary", status="error", diag=diag, error=f"{type(error).__name__}: {str(error)[:300]}")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
async def _ask(system: str, user: str, usage: dict[str, Any], diag: dict[str, Any]) -> SectionDraft:
    """LLM 1회 → SectionDraft. 출력이 형식에 맞지 않으면(잘림 등) 1회 다시 시도한다.
    토큰 수는 보고서 전체(usage)와 섹션(diag)에 더한다."""
    model = get_chat_model().with_structured_output(SectionDraft, method="json_schema", strict=True, include_raw=True)
    diag.update(input_tokens=0, output_tokens=0, retried=False)
    for attempt in (1, 2):
        result = await model.ainvoke([("system", system), ("user", user)])
        tokens = getattr(result["raw"], "usage_metadata", None) or {}
        for key in ("input_tokens", "output_tokens"):
            usage[key] += tokens.get(key, 0)
            diag[key] += tokens.get(key, 0)
        if result["parsed"] is not None:
            return result["parsed"]
        if attempt == 1:
            diag["retried"] = True
    raise ValueError(f"LLM 출력이 형식에 맞지 않습니다: {result['parsing_error']}")


def _result(spec: SectionSpec, kind: Literal["summary", "section"], **fields: Any) -> AnalysisSection:
    return AnalysisSection(id=spec.id, kind=kind, title=spec.title, **fields)


def _clean(items: list[str]) -> list[str]:
    return [x.strip() for x in items if x.strip()]

"""질의응답 흐름: 질문 → 1차 LLM 판단 → (필요하면) 대상마다 확인·검색 → 2차 LLM 답변.

    질문
     │
     ▼
    1차 LLM (search_disclosures tool 연결)
     ├─ tool 호출 없음 → 1차 응답을 그대로 답변                                       (type=general)
     └─ tool 호출 있음 → 검색 대상(targets) 모으기 (최대 MAX_TARGETS개)               (type=disclosure)
                          → 대상마다: 확인(resolve_target) → 검색 → 표 확장
                          → answerer로 답변 (대상이 여럿이면 근거를 대상별로 묶음)

검색 대상: 보통 1개. 회사나 공시(기간)가 다른 대상을 묻거나 비교하면 대상마다 하나씩 (예: 삼성전자 매출 / SK하이닉스 매출).
    대상 1개: 근거 top_k개 (기본 5, 두 검색의 최상위 4칸 + RRF 1칸)
    대상 2개: 대상마다 근거 3개 (최상위 2칸 + RRF 1칸), 근거 합계 상한도 대상마다 나눈다
    공시가 없는 대상은 검색하지 않고 안내 문장을 답변 앞에 붙인다. 모든 대상이 없으면 안내만 답한다.

대상 1개의 확인 (resolve_target)
  회사 (mentioned_company: 질문에 나온 회사, corp_name: 보유 목록 중 해당 회사)
    mentioned_company 있음 + corp_name 없음 → 검색 안 함, "공시가 없습니다"
    둘 다 없음                              → 전체 검색
    corp_name 있음                          → 그 회사 안에서만 검색 (DB에 그 회사 공시가 없으면 "공시가 없습니다")
  인자 검증 실패
    corp_name이 목록 밖                     → "공시가 없습니다"
    report_type이 사업·반기·분기보고서가 아님 → "조회할 수 없는 공시 종류입니다"
    그 외                                   → 다시 질문해 달라고 안내
  기간 (report_type: 공시 종류, period: YYYY.MM, latest: "최근" 질문)
    latest + 회사 있음        → 그 회사의 가장 최근 공시(종류를 말했으면 그 종류 중)로 report_type, period를 정한다
    report_type·period 있음   → 그 조건으로 검색. 맞는 공시가 없으면 검색 안 함, "해당 기간 공시가 없습니다"
    기간 없음                 → 전체 기간에서 검색
    latest + 회사 없음        → 기업마다 최근 공시가 달라 고를 수 없으므로 전체 기간에서 검색

검색은 한 번에 끝난다 (검색 → 답변). 검색 결과를 보고 다시 검색하는 흐름은 LangGraph에서 다룬다.
"""

import asyncio
import json
from datetime import date
from typing import Any, get_args

from pydantic import ValidationError

from src.llm.models import get_chat_model
from src.qa.answerer import answer
from src.qa.expander import CONTEXT_CHARS, expand_tables
from src.qa.prompts import ROUTER_SYSTEM
from src.qa.retriever import GUARANTEED, list_filings, search
from src.qa.schemas import AskResponse, ChatTurn, FilingRef, SearchGroup
from src.qa.tools import MAX_TARGETS, CorpName, ReportType, SearchTarget, search_disclosures

INVALID_ARGS = "질문을 이해하지 못했습니다. 회사명과 찾을 내용을 넣어 다시 질문해 주세요."
TOO_MANY_TARGETS = f"한 번에 최대 {MAX_TARGETS}개 대상(회사·공시)까지 찾을 수 있어 앞의 {MAX_TARGETS}개만 찾았습니다."

PER_TARGET_K = 3  # 대상이 여럿일 때 대상마다 넘기는 근거 수
PER_TARGET_GUARANTEED = 2  # 그중 두 검색(임베딩·BM25)의 최상위 결과로 먼저 채우는 칸 수


# ---------------------------------------------------------------------------
# 안내 문장 (검색하지 않고 답할 때)
# ---------------------------------------------------------------------------
def no_company_message(company: str | None) -> str:
    """보유하지 않은 회사를 물었을 때."""
    name = company or "해당 회사"
    return f"{name}의 공시가 없습니다. 현재 조회할 수 있는 기업: {', '.join(get_args(CorpName))}"


def unsupported_type_message(report_type: object) -> str:
    """조회할 수 없는 공시 종류(감사보고서 등)를 물었을 때."""
    return f"{report_type} 공시는 조회할 수 없습니다. 조회할 수 있는 공시 종류: {', '.join(get_args(ReportType))}"


def no_period_message(target: SearchTarget, filings: list[FilingRef]) -> str:
    """요청한 종류·기간의 공시가 없을 때. 조회 가능한 공시 목록을 함께 알려 준다."""
    wanted = " ".join(v for v in (target.corp_name, target.report_type, target.period) if v)
    if target.corp_name:
        available = ", ".join(f.report_nm for f in filings)
    else:
        available = ", ".join(f"{f.corp_name} {f.report_nm}" for f in filings)
    return f"{wanted} 공시가 없습니다. 현재 조회할 수 있는 공시: {available}"


def matches(filing: FilingRef, target: SearchTarget) -> bool:
    """공시가 대상의 종류·기간 조건에 맞는지. 조건이 비어 있으면 통과."""
    return (not target.report_type or filing.report_type == target.report_type) and (
        not target.period or filing.period == target.period
    )


# ---------------------------------------------------------------------------
# 검색 대상 처리
# ---------------------------------------------------------------------------
def collect_targets(tool_calls: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """모든 tool 호출의 targets를 모은다. 같은 대상은 하나로, MAX_TARGETS개를 넘으면 앞의 것만.
    (LLM이 대상마다 tool을 따로 호출하는 경우도 있다.) 반환: (대상 인자 목록, 답변 앞에 붙일 안내)"""
    raws = [t for call in tool_calls for t in (call["args"].get("targets") or []) if isinstance(t, dict)]
    unique: dict[str, dict[str, Any]] = {}
    for raw in raws:
        key = json.dumps({k: v for k, v in raw.items() if v not in (None, "", False)}, sort_keys=True, ensure_ascii=False)
        unique.setdefault(key, raw)
    targets = list(unique.values())
    notes = [TOO_MANY_TARGETS] if len(targets) > MAX_TARGETS else []
    return targets[:MAX_TARGETS], notes


async def resolve_target(raw: dict[str, Any]) -> tuple[SearchTarget | None, str | None]:
    """대상 1개의 인자를 검증하고 회사·기간을 DB 공시 목록으로 확인한다.
    반환: (검색할 대상, None) 또는 (None, 안내 문장). "최근"이면 report_type, period를 실제 최근 공시로 바꾼다."""
    try:
        target = SearchTarget(**raw)
    except ValidationError as error:
        # 어느 인자가 틀렸는지에 따라 안내한다
        failed = {e["loc"][0] for e in error.errors() if e["loc"]}
        if "corp_name" in failed:  # 목록 밖 회사명
            return None, no_company_message(raw.get("mentioned_company") or raw.get("corp_name"))
        if "report_type" in failed:  # 사업·반기·분기보고서가 아닌 공시 (감사보고서 등)
            return None, unsupported_type_message(raw.get("report_type"))
        return None, INVALID_ARGS

    # 질문에 회사가 있는데 보유 목록에 없음
    if target.mentioned_company and not target.corp_name:
        return None, no_company_message(target.mentioned_company)

    # 기간 조건이 있으면 DB의 공시 목록으로 확인한다 (LLM은 어떤 공시가 있는지 모른다)
    if (target.latest and target.corp_name) or target.report_type or target.period:
        filings = await list_filings(target.corp_name)
        if target.corp_name and not filings:
            return None, no_company_message(target.corp_name)

        # "최근": LLM이 추측한 기간 대신 실제 가장 최근 공시를 고른다
        if target.latest and target.corp_name:
            candidates = [f for f in filings if not target.report_type or f.report_type == target.report_type]
            if candidates:
                latest = candidates[0]
                target = target.model_copy(update={"report_type": latest.report_type, "period": latest.period})

        if not any(matches(f, target) for f in filings):
            return None, no_period_message(target, filings)

    return target, None


def target_label(target: SearchTarget) -> str:
    """대상별 묶음 제목. 예: 삼성전자 · 분기보고서 (2026.09) · 찾을 내용: 매출"""
    company = target.corp_name or "전체 기업"
    filing = f"{target.report_type or '전체 공시'}{f' ({target.period})' if target.period else ''}"
    return f"{company} · {filing} · 찾을 내용: {target.query}"


async def search_target(target: SearchTarget, k: int, guaranteed: int, budget: int) -> SearchGroup:
    """대상 1개를 검색하고 표를 확장한다. 회사 공시가 DB에 없으면 안내 문장만 담는다."""
    label = target_label(target)
    # 값이 있는 조건(회사, 종류, 기간)으로만 좁혀서 검색한다
    chunks = await search(
        target.query, k, target.corp_name, target.report_type, target.period, guaranteed=guaranteed
    )
    # 결과 0개: 회사 목록(CorpName)에는 있지만 DB에 공시가 없는 회사면 "공시가 없습니다".
    # 공시는 있는데 결과가 없으면 근거 없는 대상으로 둔다 (answer()가 처리).
    if target.corp_name and not chunks and not await list_filings(target.corp_name):
        return SearchGroup(label=label, notice=no_company_message(target.corp_name))
    # 표 청크(잘린 조각일 수 있음)를 원본 표 전체로 바꾼다 (작은 표만, 같은 표는 하나로, 근거 합계 budget까지)
    return SearchGroup(label=label, chunks=await expand_tables(chunks, budget))


# ---------------------------------------------------------------------------
# 전체 흐름
# ---------------------------------------------------------------------------
async def ask(question: str, top_k: int = 5, history: list[ChatTurn] | None = None) -> AskResponse:
    """사용자 질문에 답한다. 공시 질문이면 검색 결과를 근거로 답한다.

    history(이전 대화)는 1차 LLM에만 넘긴다. 이어지는 질문의 회사·기간을 판단하는 데 쓰고,
    2차 LLM(답변)은 이번 검색 근거만 보게 해서 이전 답변 내용을 근거처럼 쓰지 않게 한다.
    top_k는 검색 대상이 1개일 때의 근거 수다. 대상이 여럿이면 대상마다 PER_TARGET_K개.
    """
    router = get_chat_model().bind_tools([search_disclosures])
    messages = [
        ("system", ROUTER_SYSTEM.format(today=date.today().isoformat())),
        *[(turn.role, turn.content) for turn in history or []],
        ("user", question),
    ]
    decision = await router.ainvoke(messages)

    # tool 호출 없음: 일반 대화. 1차 응답이 곧 답변이다.
    if not decision.tool_calls:
        return AskResponse(type="general", answer=str(decision.text), sources=[])

    raws, notes = collect_targets(decision.tool_calls)
    if not raws:
        return AskResponse(type="disclosure", answer=INVALID_ARGS, sources=[], search_args={"targets": []})

    # 대상마다 확인 (동시에). 확인 결과가 같은 대상은 하나로 합친다.
    resolved = await asyncio.gather(*(resolve_target(raw) for raw in raws))
    slots: list[SearchTarget | str] = []  # 대상 순서대로: 검색할 대상 또는 안내 문장
    search_args: list[dict[str, Any]] = []
    for raw, (target, notice) in zip(raws, resolved, strict=True):
        if target is None:
            slots.append(notice or INVALID_ARGS)
            search_args.append(raw)
        elif target.model_dump() not in search_args:
            slots.append(target)
            search_args.append(target.model_dump())
    args = {"targets": search_args}

    targets = [slot for slot in slots if isinstance(slot, SearchTarget)]
    if not targets:  # 모든 대상이 공시 없음: 검색하지 않고 안내만
        notices = [slot for slot in slots if isinstance(slot, str)]
        return AskResponse(type="disclosure", answer="\n\n".join([*notes, *notices]), sources=[], search_args=args)

    # 대상마다 검색 (동시에). 대상이 여럿이면 근거 수와 근거 합계 상한을 나눈다.
    k, guaranteed = (top_k, GUARANTEED) if len(targets) == 1 else (PER_TARGET_K, PER_TARGET_GUARANTEED)
    found = iter(await asyncio.gather(
        *(search_target(t, k, guaranteed, CONTEXT_CHARS // len(targets)) for t in targets)
    ))
    groups = [next(found) if isinstance(slot, SearchTarget) else SearchGroup(label="", notice=slot) for slot in slots]

    # 두 대상에서 같은 청크가 나오면 앞 대상에만 남긴다
    seen: set[str] = set()
    for group in groups:
        group.chunks = [c for c in group.chunks if c.chunk_id not in seen]
        seen.update(c.chunk_id for c in group.chunks)

    # 모든 대상이 결국 공시 없음 (검색해 보니 DB에 회사 공시가 없음): 안내만
    if all(g.notice for g in groups):
        notices = [g.notice for g in groups if g.notice]
        return AskResponse(type="disclosure", answer="\n\n".join([*notes, *notices]), sources=[], search_args=args)

    # 답변은 LLM이 정리한 query가 아니라 사용자의 원래 질문으로 만든다.
    response = await answer(question, groups, notes)
    response.search_args = args
    return response

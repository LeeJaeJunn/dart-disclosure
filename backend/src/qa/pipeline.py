"""질의응답 흐름: 질문 → 1차 LLM 판단 → (필요하면) 검색 → 2차 LLM 답변.

    질문
     │
     ▼
    1차 LLM (search_disclosures tool 연결)
     ├─ tool 호출 없음 → 1차 응답을 그대로 답변                   (type=general)
     └─ tool 호출 있음 → 검색(LLM이 정한 query) → answerer로 답변   (type=disclosure)

회사 처리 (mentioned_company: 질문에 나온 회사, corp_name: 보유 목록 중 해당 회사)
    mentioned_company 있음 + corp_name 없음 → 검색 안 함, "공시가 없습니다"
    둘 다 없음                              → 전체 검색
    corp_name 있음                          → 그 회사 안에서만 검색 (DB에 그 회사 공시가 없으면 "공시가 없습니다")

인자 검증 실패
    corp_name이 목록 밖                     → "공시가 없습니다"
    report_type이 사업·반기·분기보고서가 아님 → "조회할 수 없는 공시 종류입니다"
    그 외                                   → 다시 질문해 달라고 안내

기간 처리 (report_type: 공시 종류, period: YYYY.MM, latest: "최근" 질문)
    latest + 회사 있음        → 그 회사의 가장 최근 공시(종류를 말했으면 그 종류 중)로 report_type, period를 정한다
    report_type·period 있음   → 그 조건으로 검색. 맞는 공시가 없으면 검색 안 함, "해당 기간 공시가 없습니다"
    기간 없음                 → 전체 기간에서 검색
    latest + 회사 없음        → 기업마다 최근 공시가 달라 고를 수 없으므로 전체 기간에서 검색

1단계는 tool 호출을 한 번만 처리한다 (검색 → 답변). 여러 번 검색하는 흐름은 LangGraph에서 다룬다.
"""

from datetime import date
from typing import get_args

from pydantic import ValidationError

from src.llm.models import get_chat_model
from src.qa.answerer import answer
from src.qa.prompts import ROUTER_SYSTEM
from src.qa.retriever import list_filings, search
from src.qa.schemas import AskResponse, ChatTurn, FilingRef
from src.qa.tools import CorpName, ReportType, SearchDisclosuresArgs, search_disclosures

INVALID_ARGS = "질문을 이해하지 못했습니다. 회사명과 찾을 내용을 넣어 다시 질문해 주세요."


def no_company_response(company: str | None, search_args: dict) -> AskResponse:
    """보유하지 않은 회사를 물었을 때의 답변. 검색하지 않는다."""
    name = company or "해당 회사"
    available = ", ".join(get_args(CorpName))
    return AskResponse(
        type="disclosure",
        answer=f"{name}의 공시가 없습니다. 현재 조회할 수 있는 기업: {available}",
        sources=[],
        search_args=search_args,
    )


def unsupported_type_response(report_type: object, search_args: dict) -> AskResponse:
    """조회할 수 없는 공시 종류(감사보고서 등)를 물었을 때의 답변. 검색하지 않는다."""
    supported = ", ".join(get_args(ReportType))
    return AskResponse(
        type="disclosure",
        answer=f"{report_type} 공시는 조회할 수 없습니다. 조회할 수 있는 공시 종류: {supported}",
        sources=[],
        search_args=search_args,
    )


def no_period_response(args: SearchDisclosuresArgs, filings: list[FilingRef]) -> AskResponse:
    """요청한 종류·기간의 공시가 없을 때의 답변. 조회 가능한 공시 목록을 함께 알려 준다. 검색하지 않는다."""
    wanted = " ".join(v for v in (args.corp_name, args.report_type, args.period) if v)
    if args.corp_name:
        available = ", ".join(f.report_nm for f in filings)
    else:
        available = ", ".join(f"{f.corp_name} {f.report_nm}" for f in filings)
    return AskResponse(
        type="disclosure",
        answer=f"{wanted} 공시가 없습니다. 현재 조회할 수 있는 공시: {available}",
        sources=[],
        search_args=args.model_dump(),
    )


def matches(filing: FilingRef, args: SearchDisclosuresArgs) -> bool:
    """공시가 args의 종류·기간 조건에 맞는지. 조건이 비어 있으면 통과."""
    return (not args.report_type or filing.report_type == args.report_type) and (
        not args.period or filing.period == args.period
    )


async def ask(question: str, top_k: int = 5, history: list[ChatTurn] | None = None) -> AskResponse:
    """사용자 질문에 답한다. 공시 질문이면 검색 결과를 근거로 답한다.

    history(이전 대화)는 1차 LLM에만 넘긴다. 이어지는 질문의 회사·기간을 판단하는 데 쓰고,
    2차 LLM(답변)은 이번 검색 근거만 보게 해서 이전 답변 내용을 근거처럼 쓰지 않게 한다.
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

    # tool 호출 있음: LLM이 채운 인자를 검증한다. 여러 번 호출해도 지금은 첫 번째만 쓴다.
    raw_args = decision.tool_calls[0]["args"]
    try:
        args = SearchDisclosuresArgs(**raw_args)
    except ValidationError as error:
        # 어느 인자가 틀렸는지에 따라 안내한다
        failed = {e["loc"][0] for e in error.errors() if e["loc"]}
        if "corp_name" in failed:  # 목록 밖 회사명
            return no_company_response(raw_args.get("mentioned_company") or raw_args.get("corp_name"), raw_args)
        if "report_type" in failed:  # 사업·반기·분기보고서가 아닌 공시 (감사보고서 등)
            return unsupported_type_response(raw_args.get("report_type"), raw_args)
        return AskResponse(type="disclosure", answer=INVALID_ARGS, sources=[], search_args=raw_args)

    # 질문에 회사가 있는데 보유 목록에 없음 → 검색하지 않는다
    if args.mentioned_company and not args.corp_name:
        return no_company_response(args.mentioned_company, args.model_dump())

    # 기간 조건이 있으면 DB의 공시 목록으로 확인한다 (LLM은 어떤 공시가 있는지 모른다)
    if (args.latest and args.corp_name) or args.report_type or args.period:
        filings = await list_filings(args.corp_name)
        if args.corp_name and not filings:
            return no_company_response(args.corp_name, args.model_dump())

        # "최근": LLM이 추측한 기간 대신 실제 가장 최근 공시를 고른다
        if args.latest and args.corp_name:
            candidates = [f for f in filings if not args.report_type or f.report_type == args.report_type]
            if candidates:
                latest = candidates[0]
                args = args.model_copy(update={"report_type": latest.report_type, "period": latest.period})

        if not any(matches(f, args) for f in filings):
            return no_period_response(args, filings)

    # 값이 있는 조건(회사, 종류, 기간)으로만 좁혀서 검색한다
    chunks = await search(
        args.query, top_k, corp_name=args.corp_name, report_type=args.report_type, period=args.period
    )
    # 결과 0개: 회사 목록(CorpName)에는 있지만 DB에 공시가 없는 회사면 "공시가 없습니다".
    # 공시는 있는데 결과가 없으면 answer()가 "근거를 찾지 못했습니다"로 답한다.
    if args.corp_name and not chunks and not await list_filings(args.corp_name):
        return no_company_response(args.corp_name, args.model_dump())

    # 답변은 LLM이 정리한 query가 아니라 사용자의 원래 질문으로 만든다.
    response = await answer(question, chunks)
    response.search_args = args.model_dump()
    return response

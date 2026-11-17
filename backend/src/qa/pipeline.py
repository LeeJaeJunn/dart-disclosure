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
    corp_name 있음                          → 그 회사 안에서만 검색 (결과 0개면 "공시가 없습니다")
    인자 검증 실패 (목록 밖 회사명 등)       → "공시가 없습니다"

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
from src.qa.schemas import AskResponse, FilingRef
from src.qa.tools import CorpName, SearchDisclosuresArgs, search_disclosures

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


async def ask(question: str, top_k: int = 5) -> AskResponse:
    """사용자 질문에 답한다. 공시 질문이면 검색 결과를 근거로 답한다."""
    router = get_chat_model().bind_tools([search_disclosures])
    messages = [
        ("system", ROUTER_SYSTEM.format(today=date.today().isoformat())),
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
    except ValidationError:
        # 목록 밖 회사명 등 잘못된 인자 → 보유하지 않은 회사로 처리
        return no_company_response(raw_args.get("mentioned_company") or raw_args.get("corp_name"), raw_args)

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
    if args.corp_name and not chunks:
        return no_company_response(args.corp_name, args.model_dump())

    # 답변은 LLM이 정리한 query가 아니라 사용자의 원래 질문으로 만든다.
    response = await answer(question, chunks)
    response.search_args = args.model_dump()
    return response

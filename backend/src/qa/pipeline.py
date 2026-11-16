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

1단계는 tool 호출을 한 번만 처리한다 (검색 → 답변). 여러 번 검색하는 흐름은 LangGraph에서 다룬다.
"""

from datetime import date
from typing import get_args

from pydantic import ValidationError

from src.llm.models import get_chat_model
from src.qa.answerer import answer
from src.qa.prompts import ROUTER_SYSTEM
from src.qa.retriever import search
from src.qa.schemas import AskResponse
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

import json


async def ask(question: str, top_k: int = 5) -> AskResponse:
    """사용자 질문에 답한다. 공시 질문이면 검색 결과를 근거로 답한다."""
    router = get_chat_model().bind_tools([search_disclosures])
    messages = [
        ("system", ROUTER_SYSTEM.format(today=date.today().isoformat())),
        ("user", question),
    ]
    decision = await router.ainvoke(messages)
    print(json.dumps(decision.model_dump(), ensure_ascii=False, indent=2, default=str))

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

    # corp_name이 있으면 그 회사 안에서만, 없으면 전체에서 검색한다
    chunks = await search(args.query, top_k, corp_name=args.corp_name)
    if args.corp_name and not chunks:
        return no_company_response(args.corp_name, args.model_dump())

    # 답변은 LLM이 정리한 query가 아니라 사용자의 원래 질문으로 만든다.
    response = await answer(question, chunks)
    response.search_args = args.model_dump()
    return response

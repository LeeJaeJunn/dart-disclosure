"""LLM이 호출하는 tool 정의.

1차 LLM은 이 tool의 이름·설명·인자 설명을 보고 호출 여부와 인자 값을 정한다.
인자 설명이 곧 LLM에게 주는 안내문이므로, 형식과 예시를 구체적으로 적는다.
"""

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.qa.retriever import search
from src.qa.schemas import RetrievedChunk

ReportType = Literal["사업보고서", "반기보고서", "분기보고서"]

# 공시를 보유한 기업 목록 (DB에 저장된 기업명 그대로). 공시를 추가하면 여기에도 추가한다.
CorpName = Literal["삼성전자", "SK하이닉스"]


class SearchDisclosuresArgs(BaseModel):
    """search_disclosures의 인자. pipeline에서 LLM이 채운 값을 검증할 때도 쓴다."""

    query: str = Field(
        description="공시에서 찾을 내용만 짧게 쓴다. 회사명과 기간은 넣지 않는다. 예: 영업이익, 배당금, 반도체 사업 위험 요인",
    )
    mentioned_company: str | None = Field(
        default=None,
        description="질문에 나온 회사명을 사용자가 쓴 그대로 옮긴다. 예: 삼전, LG전자. 질문에 회사가 없으면 비운다.",
    )
    corp_name: CorpName | None = Field(
        default=None,
        description="mentioned_company가 가리키는 회사를 목록에서 고른다. 줄임말도 같은 회사면 고른다 (예: 삼전 → 삼성전자). "
        "목록에 없는 회사이거나 질문에 회사가 없으면 비운다. 비슷한 다른 회사를 대신 고르지 않는다.",
    )
    report_type: ReportType | None = Field(
        default=None,
        description="공시 종류. 연간 실적이면 사업보고서, 상반기면 반기보고서, 1·3분기면 분기보고서. 질문에서 알 수 없으면 비운다.",
    )
    period: str | None = Field(
        default=None,
        description="보고 기간 YYYY.MM 형식. 사업보고서는 YYYY.12, 반기보고서는 YYYY.06, 1분기는 YYYY.03, 3분기는 YYYY.09. "
        "질문에 연도와 기간(연간, 상반기, 분기)이 함께 나올 때만 채운다. 질문에서 알 수 없거나 '최근'이면 비운다.",
    )
    latest: bool = Field(
        default=False,
        description="질문에 '최근', '최신', '요즘' 같은 단어가 직접 있을 때만 true. 이때 period는 채우지 않는다 (가장 최근 공시는 시스템이 고른다). "
        "기간을 말하지 않은 질문은 false로 둔다 (예: 'HBM 사업 현황 알려줘' → false).",
    )


@tool(args_schema=SearchDisclosuresArgs)
async def search_disclosures(
    query: str,
    mentioned_company: str | None = None,
    corp_name: CorpName | None = None,
    report_type: ReportType | None = None,
    period: str | None = None,
    latest: bool = False,
) -> list[RetrievedChunk]:
    """국내 상장기업의 DART 공시(사업보고서·반기보고서·분기보고서) 본문과 표에서 질문과 관련된 부분을 검색한다.
    기업의 재무 수치, 사업 내용, 위험 요인, 배당, 임원 등 공시에서 확인할 수 있는 내용을 물으면 호출한다."""
    # LLM이 인자를 정하는 데만 쓴다. 실제 검색(latest 처리 포함)은 pipeline.ask()가 한다.
    return await search(query, corp_name=corp_name, report_type=report_type, period=period)

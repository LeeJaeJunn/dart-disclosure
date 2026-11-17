"""질의응답 요청·응답 스키마."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """이전 대화 1개 (사용자 질문 또는 답변 본문)."""

    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    """사용자 질문."""

    question: str = Field(min_length=1, description="사용자 질문")
    top_k: int = Field(default=5, ge=1, le=20, description="답변에 사용할 검색 결과 수")
    history: list[ChatTurn] = Field(
        default_factory=list,
        description="이전 대화 (오래된 순). 1차 LLM이 '그럼 영업이익은?'처럼 이어지는 질문의 회사·기간을 판단하는 데만 쓴다",
    )


class RetrievedChunk(BaseModel):
    """검색 결과 1건. retriever가 만들고 answerer가 사용한다 (API 응답에는 직접 나가지 않음)."""

    chunk_id: str
    kind: str                   # text | table | table_kv
    section_path: str           # 원문 위치 (목차 경로)
    raw: str                    # 원문 텍스트
    score: float                # 유사도 (1 - 코사인 거리, 클수록 비슷함)
    # 근거 정보 (chunk.rcept_no, chunk.meta에서 읽음)
    rcept_no: str               # 접수번호
    corp_name: str              # 기업명
    report_nm: str              # 공시명
    rcept_dt: str               # 공시일 (YYYYMMDD)
    dart_url: str               # DART 원문 링크 (meta에 없어서 rcept_no로 생성)


class FilingRef(BaseModel):
    """조회 가능한 공시 1건. 기간 필터를 정하거나 "공시가 없습니다" 안내에 쓴다."""

    corp_name: str
    report_nm: str              # 예: 분기보고서 (2026.09)
    report_type: str            # 사업보고서 | 반기보고서 | 분기보고서
    period: str                 # YYYY.MM


class Source(BaseModel):
    """답변 근거 1건. 답변 본문의 [n]과 n이 대응한다."""

    n: int = Field(description="답변 본문의 인용 번호 [n]")
    chunk_id: str
    rcept_no: str = Field(description="접수번호")
    corp_name: str = Field(description="기업명")
    report_nm: str = Field(description="공시명")
    rcept_dt: str = Field(description="공시일 (YYYYMMDD)")
    section_path: str = Field(description="원문 위치 (목차 경로)")
    quote: str = Field(description="근거 원문 발췌")
    dart_url: str = Field(description="DART 원문 링크")


class AskResponse(BaseModel):
    """질문에 대한 답변과 근거."""

    type: Literal["general", "disclosure"] = Field(
        description="general: 공시 검색 없이 답한 일반 대화 (근거 없음) / disclosure: 공시 검색 결과로 답함",
    )
    answer: str = Field(description="답변 본문. 근거는 [n] 형식으로 인용")
    sources: list[Source] = Field(description="답변에 사용한 근거 목록")
    search_args: dict | None = Field(
        default=None,
        description="검색에 쓴 조건 (query, mentioned_company, corp_name, report_type, period, latest). "
        "'최근' 질문이면 report_type, period는 코드가 DB에서 고른 값이다. 확인용",
    )

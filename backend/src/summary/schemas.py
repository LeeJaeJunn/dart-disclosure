"""공시 요약 조회 응답 스키마.

analysis 테이블 구조를 그대로 내보내지 않고 화면에 필요한 필드만 고른다.
(analysis 테이블은 재설계 예정. docs/discussion.md 1번)
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SummarySource(BaseModel):
    """요약 근거 1건. 공시 정보(공시명, 공시일, 접수번호, DART 링크)는 FilingSummary에 있다."""

    section_path: str = Field(description="원문 위치 (목차 경로)")
    quote: str = Field(description="근거 원문 발췌")


class SummarySection(BaseModel):
    """요약 섹션 1개 (예: 실적, 리스크)."""

    id: str = Field(description="섹션 식별자 (예: financials)")
    title: str = Field(description="섹션 제목")
    headline: str = Field(description="한 줄 결론")
    overview: str = Field(description="본문 요약 (원문에서 확인한 사실)")
    interpretation: list[str] = Field(description="LLM 해석")
    watch: list[str] = Field(description="지켜볼 항목")
    table_markdown: str = Field(description="섹션 표 (마크다운, 없으면 빈 문자열)")
    sources: list[SummarySource] = Field(description="근거 목록")


class FilingSummary(BaseModel):
    """공시 1건의 요약."""

    rcept_no: str = Field(description="접수번호")
    corp_name: str = Field(description="기업명")
    report_nm: str = Field(description="공시명")
    rcept_dt: str = Field(description="공시일 (YYYYMMDD)")
    dart_url: str = Field(description="DART 원문 링크")
    title: str = Field(description="요약 제목 (예: 기업분석 보고서)")
    model: str = Field(description="요약을 생성한 LLM 모델")
    created_at: datetime = Field(description="요약 생성 시각")
    sections: list[SummarySection] = Field(description="요약 섹션 목록")

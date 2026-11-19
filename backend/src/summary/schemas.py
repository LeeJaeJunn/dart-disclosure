"""공시 요약 스키마.

- 조회 응답 (SummarySource, SummarySection, FilingSummary): analysis 테이블 구조를 그대로 내보내지 않고
  화면에 필요한 필드만 고른다.
- 생성 (EvidenceDraft, SectionDraft): LLM이 섹션 1개마다 채우는 출력 형식.
- 저장 (AnalysisSource, AnalysisSection, Analysis): analysis 테이블 1행. AGENTS.md의 DB 구조와 같다.
"""

from datetime import datetime
from typing import Any, Literal

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


# ---------------------------------------------------------------------------
# 생성: LLM 출력 형식 (OpenAI strict JSON schema라 모든 필드가 필수이고 기본값이 없다)
# ---------------------------------------------------------------------------
class EvidenceDraft(BaseModel):
    chunk_id: str = Field(description="[근거]의 id 그대로")
    quote: str = Field(description="근거 원문 일부를 숫자까지 그대로, 150자 이내")


class SectionDraft(BaseModel):
    headline: str = Field(description="이 섹션의 핵심 특징 한 줄 (40자 안팎)")
    overview: str = Field(description="특징을 설명하는 2~3문장 서술. 수치는 꼭 필요한 것만")
    table_markdown: str = Field(description="핵심 데이터 마크다운 표 (원문 숫자 그대로), 없으면 빈 문자열")
    interpretation: list[str] = Field(description="해석 최대 3개, 각 1문장")
    watch: list[str] = Field(description="확인이 필요한 점 최대 2개")
    evidence: list[EvidenceDraft] = Field(description="근거 목록. 본문의 [1], [2]가 이 순서를 가리킨다")


# ---------------------------------------------------------------------------
# 저장: analysis 테이블 1행
# ---------------------------------------------------------------------------
class AnalysisSource(BaseModel):
    """섹션 근거 1건. n은 overview·interpretation 본문의 [n]과 같다."""

    n: int
    rcept_no: str
    rcept_dt: str
    report_nm: str
    source: str  # 예: SK하이닉스 분기보고서(2026.09) · III. 재무에 관한 사항 > 1. 요약재무정보
    section: str  # 원문 위치 (목차 경로)
    period: str
    quote: str
    url: str
    chunk_id: str  # chunk.chunk_id
    verified: bool  # 인용문의 숫자가 모두 원문에 있음
    problems: list[str]


SectionStatus = Literal["done", "no_evidence", "error"]


class AnalysisSection(BaseModel):
    """analysis.sections[] 1개."""

    id: str
    kind: Literal["summary", "section"]
    title: str
    status: SectionStatus  # done | no_evidence(근거 없음, 화면에서 빠짐) | error(생성 실패)
    headline: str = ""
    overview: str = ""
    interpretation: list[str] = Field(default_factory=list)
    watch: list[str] = Field(default_factory=list)
    table_markdown: str = ""
    sources: list[AnalysisSource] = Field(default_factory=list)
    check: dict[str, Any] = Field(default_factory=dict)  # {n_evidence, n_unverified, table_unverified_numbers}
    diag: dict[str, Any] = Field(default_factory=dict)  # 디버깅용: 찾은 목차 수, 글자 수·잘림, 시간·토큰, 재시도
    error: str | None = None  # status가 error일 때만


class Analysis(BaseModel):
    """analysis 테이블 1행."""

    rcept_no: str
    template: str
    title: str
    version: str
    model: str
    parser_version: str
    chunker_version: str
    usage: dict[str, Any]  # {input_tokens, output_tokens, usd(null)}
    sections: list[AnalysisSection]

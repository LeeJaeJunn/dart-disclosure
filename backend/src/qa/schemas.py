"""질의응답 요청·응답 스키마."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """사용자 질문."""

    question: str = Field(min_length=1, description="사용자 질문")
    top_k: int = Field(default=5, ge=1, le=20, description="답변에 사용할 검색 결과 수")


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

    answer: str = Field(description="답변 본문. 근거는 [n] 형식으로 인용")
    sources: list[Source] = Field(description="답변에 사용한 근거 목록")

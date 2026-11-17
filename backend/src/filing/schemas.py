"""저장 공시 조회 응답 스키마."""

from pydantic import BaseModel, Field


class Company(BaseModel):
    """공시가 저장된 기업 1곳. 기업 테이블이 없어 filing을 corp_code로 묶어 만든다."""

    corp_code: str = Field(description="DART 기업 고유번호")
    corp_name: str = Field(description="기업명 (가장 최근 공시 기준)")
    filing_count: int = Field(description="저장된 공시 수 (정정 전 공시 제외)")
    latest_rcept_dt: str = Field(description="가장 최근 공시일 (YYYYMMDD)")


class Filing(BaseModel):
    """저장된 공시 1건."""

    rcept_no: str = Field(description="접수번호")
    corp_code: str = Field(description="DART 기업 고유번호")
    corp_name: str = Field(description="기업명")
    report_nm: str = Field(description="공시명")
    report_type: str = Field(description="공시 유형")
    period: str = Field(description="보고 기간 (예: 2023.12)")
    rcept_dt: str = Field(description="공시일 (YYYYMMDD)")
    is_latest: bool = Field(description="같은 기간 공시 중 최신(정정 반영) 여부")
    dart_url: str = Field(description="DART 원문 링크")
    has_summary: bool = Field(description="요약(analysis)이 있는지 여부")

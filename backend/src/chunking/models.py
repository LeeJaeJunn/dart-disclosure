import re
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from src.parsing.models import ParsedTable

ChunkKind = Literal["section", "text", "table", "table_kv"]


class FilingInfo(BaseModel):
    rcept_no: str
    corp_code: str
    corp_name: str
    report_nm: str
    rcept_dt: str  # YYYYMMDD
    is_latest: bool = True  # 기재정정 전 공시는 False

    @computed_field
    @property
    def report_type(self) -> str:
        for name in ("사업보고서", "반기보고서", "분기보고서"):
            if name in self.report_nm:
                return name
        return self.report_nm

    @computed_field
    @property
    def period(self) -> str:
        match = re.search(r"\((\d{4}\.\d{2})\)", self.report_nm)
        return match.group(1) if match else f"{self.rcept_dt[:4]}.{self.rcept_dt[4:6]}"

    @computed_field
    @property
    def dart_url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.rcept_no}"


class ChunkingConfig(BaseModel):
    target_chars: int = 900
    max_chars: int = 1400
    overlap_paragraphs: int = 1
    max_paragraph_chars: int = 800
    table_rows_per_chunk: int = 12
    table_chars: int = 1400
    max_columns: int = 10
    max_embed_chars: int = 6000  # 임베딩 입력 상한. LLM에게 주는 raw는 자르지 않는다


# DB의 chunk 테이블 한 행
class Chunk(BaseModel):
    chunk_id: str
    rcept_no: str
    section_id: str
    section_path: str
    kind: ChunkKind
    table_id: str | None = None  # 표 청크는 이 값으로 표의 notes를 찾는다
    embed: bool
    text: str  # 임베딩 입력
    raw: str  # LLM에게 보여 줄 원문
    meta: dict[str, Any] = Field(default_factory=dict)


# DB의 filing_table 테이블 한 행
class TableRecord(ParsedTable):
    table_id: str
    rcept_no: str
    section_id: str
    table_index: int


class ChunkedDocument(BaseModel):
    filing: FilingInfo
    parser_version: str
    chunker_version: str
    config: ChunkingConfig
    tables: list[TableRecord]
    chunks: list[Chunk]

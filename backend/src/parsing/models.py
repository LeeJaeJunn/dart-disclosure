from typing import Annotated, Literal

from pydantic import BaseModel, Field

CellType = Literal["number", "percent", "date", "text", "empty"]
Basis = Literal["consolidated", "separate", "unknown"]
BasisSource = Literal["xbrl", "section_title", "preceding_heading"]


# 값은 원문 그대로 raw에 둔다. △, 괄호의 의미 해석은 LLM이 notes를 보고 한다.
class Cell(BaseModel):
    row: str
    column: str
    raw: str
    type: CellType
    unit: str | None = None  # 표 단위가 하나이고 숫자 셀일 때만 채운다


class ParsedTable(BaseModel):
    title: str | None = None
    group_title: str | None = None
    xbrl_code: str | None = None
    unit_raw: str | None = None  # 원문 단위 표기. 예: "백만원, %"
    as_of: str | None = None
    period_label: str | None = None  # 당기, 전기 등
    basis: Basis = "unknown"
    basis_source: BasisSource | None = None
    context_before: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # 이 표에 달린 안내 문구
    header: list[str]
    rows: list[list[Cell]]


class TextBlock(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class TableBlock(BaseModel):
    kind: Literal["table"] = "table"
    table: ParsedTable


Block = Annotated[TextBlock | TableBlock, Field(discriminator="kind")]


class ParsedSection(BaseModel):
    title: str
    level: int
    path: list[str]
    blocks: list[Block] = Field(default_factory=list)
    children: list["ParsedSection"] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    parser_version: str
    root: ParsedSection

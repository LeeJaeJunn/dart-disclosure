"""공시 요약 조회·저장: analysis 테이블.

- get_summary(): 공시 1건의 요약을 화면용으로 읽는다.
- save_analysis(): builder가 만든 요약을 저장한다 (공시 적재 때).

analysis SQL과 JSON 해석은 이 파일에만 둔다. analysis 구조가 바뀌면 이 파일만 고친다.
"""

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from src.db.session import pool
from src.summary.schemas import Analysis, FilingSummary, SummarySection, SummarySource

# 같은 공시·템플릿이 이미 있으면 새 내용으로 바꾼다.
SAVE_SQL = """
INSERT INTO analysis (rcept_no, template, title, version, model, parser_version, chunker_version, usage, sections)
VALUES (%(rcept_no)s, %(template)s, %(title)s, %(version)s, %(model)s, %(parser_version)s, %(chunker_version)s,
        %(usage)s, %(sections)s)
ON CONFLICT (rcept_no, template) DO UPDATE SET
    title = EXCLUDED.title,
    version = EXCLUDED.version,
    model = EXCLUDED.model,
    parser_version = EXCLUDED.parser_version,
    chunker_version = EXCLUDED.chunker_version,
    usage = EXCLUDED.usage,
    sections = EXCLUDED.sections,
    created_at = now()
"""

# 공시 정보(기업명, 공시명, 공시일, DART 링크)는 filing에서 조인한다.
# (analysis.sections[].sources[]의 rcept_dt, report_nm은 null이다)
# 한 공시에 템플릿이 여러 개면 가장 최근에 만든 것을 쓴다.
SUMMARY_SQL = """
SELECT
    f.rcept_no, f.corp_name, f.report_nm, f.rcept_dt, f.dart_url,
    a.title, a.model, a.created_at, a.sections
FROM analysis a
JOIN filing f USING (rcept_no)
WHERE a.rcept_no = %(rcept_no)s
ORDER BY a.created_at DESC
LIMIT 1
"""


def _to_section(section: dict) -> SummarySection:
    """analysis.sections[] 1개에서 화면에 필요한 필드만 고른다."""
    return SummarySection(
        id=section["id"],
        title=section["title"],
        headline=section.get("headline") or "",
        overview=section.get("overview") or "",
        interpretation=section.get("interpretation") or [],
        watch=section.get("watch") or [],
        table_markdown=section.get("table_markdown") or "",
        sources=[
            SummarySource(section_path=s.get("section") or "", quote=s.get("quote") or "")
            for s in section.get("sources") or []
        ],
    )


async def get_summary(rcept_no: str) -> FilingSummary | None:
    """공시 1건의 요약. 요약이 없으면 None. 생성이 끝난(status = done) 섹션만 담는다."""
    async with pool.connection() as conn:
        cur = await conn.execute(SUMMARY_SQL, {"rcept_no": rcept_no})
        row = await cur.fetchone()
    if row is None:
        return None

    sections = [_to_section(s) for s in row.pop("sections") if s.get("status") == "done"]
    return FilingSummary(**row, sections=sections)


async def save_analysis(conn: AsyncConnection, analysis: Analysis) -> None:
    """요약 1건을 저장한다. filing에 같은 rcept_no가 있어야 한다 (FK)."""
    sections = [section.model_dump(exclude_none=True) for section in analysis.sections]  # error는 실패한 섹션에만
    async with conn.transaction():
        await conn.execute(
            SAVE_SQL,
            {
                **analysis.model_dump(exclude={"usage", "sections"}),
                "usage": Jsonb(analysis.usage),
                "sections": Jsonb(sections),
            },
        )

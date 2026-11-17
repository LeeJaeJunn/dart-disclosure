"""공시 요약 조회: analysis 테이블에서 공시 1건의 요약을 읽는다.

조회 SQL과 analysis JSON 해석은 이 파일에만 둔다. analysis 구조가 바뀌면 이 파일만 고친다.
"""

from src.db.session import pool
from src.summary.schemas import FilingSummary, SummarySection, SummarySource

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

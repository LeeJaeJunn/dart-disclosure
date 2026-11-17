"""저장 공시 조회: 기업 목록, 기업별 공시 목록.

조회 SQL은 이 파일에만 둔다. DB 구조가 바뀌면 이 파일만 고친다.
기업 테이블이 없어 filing을 corp_code로 묶어 기업 목록을 만든다.
"""

from src.db.session import pool
from src.filing.schemas import Company, Filing

# 기업명은 사명 변경이 있을 수 있어 corp_code별 가장 최근 공시의 것을 쓴다.
# 공시 수는 정정 전 공시(is_latest = false)를 빼고 센다.
COMPANIES_SQL = """
SELECT
    corp_code,
    (array_agg(corp_name ORDER BY rcept_dt DESC, rcept_no DESC))[1] AS corp_name,
    count(*) FILTER (WHERE is_latest) AS filing_count,
    max(rcept_dt) AS latest_rcept_dt
FROM filing
GROUP BY corp_code
ORDER BY corp_name
"""

# latest_only가 true면 정정 전 공시(is_latest = false)를 뺀다.
FILINGS_SQL = """
SELECT
    rcept_no, corp_code, corp_name, report_nm, report_type,
    period, rcept_dt, is_latest, dart_url,
    EXISTS (SELECT 1 FROM analysis a WHERE a.rcept_no = filing.rcept_no) AS has_summary
FROM filing
WHERE corp_code = %(corp_code)s
  AND (is_latest OR NOT %(latest_only)s)
ORDER BY rcept_dt DESC, rcept_no DESC
"""


async def list_companies() -> list[Company]:
    """공시가 저장된 기업 목록 (기업명 순)."""
    async with pool.connection() as conn:
        cur = await conn.execute(COMPANIES_SQL)
        rows = await cur.fetchall()
    return [Company(**row) for row in rows]


async def list_filings(corp_code: str, latest_only: bool = True) -> list[Filing]:
    """기업 1곳의 저장 공시 목록 (최근 공시일 순). 저장된 공시가 없으면 빈 목록."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            FILINGS_SQL, {"corp_code": corp_code, "latest_only": latest_only}
        )
        rows = await cur.fetchall()
    return [Filing(**row) for row in rows]

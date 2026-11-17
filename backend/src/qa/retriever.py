"""검색: 질문 → 임베딩 → pgvector 유사도 검색 → RetrievedChunk 목록.

dense 검색 + 회사·공시 종류·기간 필터만 한다 (키워드 검색, 리랭커 없음).
검색 SQL은 이 파일에만 둔다. DB 구조가 바뀌면 이 파일만 고친다.
"""

from pgvector import Vector
from psycopg.types.json import Jsonb

from src.db.session import pool
from src.llm.models import get_embeddings
from src.qa.schemas import FilingRef, RetrievedChunk

# <=> : 코사인 거리 (0에 가까울수록 비슷함). score는 1 - 거리 (1에 가까울수록 비슷함)
# 근거 정보(기업명, 공시명, 공시일)는 chunk.meta에서 읽는다.
SEARCH_SQL = """
SELECT
    chunk_id,
    kind,
    section_path,
    raw,
    rcept_no,
    1 - (embedding <=> %(q)s) AS score,
    meta->>'corp_name' AS corp_name,
    meta->>'report_nm' AS report_nm,
    meta->>'rcept_dt'  AS rcept_dt
FROM chunk
WHERE embedding IS NOT NULL
  AND meta @> %(filter)s
ORDER BY embedding <=> %(q)s
LIMIT %(k)s
"""
# meta @> {...} : meta가 주어진 키·값을 모두 포함하는 청크만 (GIN 인덱스 ix_chunk_meta 사용)
# 조건이 없으면 {} 를 넘겨 전체를 검색한다.

# 조회 가능한 공시 목록. 최근 기간부터 (period는 YYYY.MM이라 문자열 정렬 = 기간 순서)
# 정정 전 옛 공시(is_latest = false)는 뺀다. corp_name이 NULL이면 전체 기업.
FILINGS_SQL = """
SELECT corp_name, report_nm, report_type, period
FROM filing
WHERE is_latest
  AND (%(corp_name)s::text IS NULL OR corp_name = %(corp_name)s)
ORDER BY period DESC, rcept_no DESC
"""


def dart_url(rcept_no: str) -> str:
    """접수번호로 DART 원문 링크를 만든다."""
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


async def search(
    question: str,
    k: int = 5,
    corp_name: str | None = None,
    report_type: str | None = None,
    period: str | None = None,
) -> list[RetrievedChunk]:
    """질문과 의미가 가까운 청크를 k개 찾는다 (유사도 높은 순).
    corp_name, report_type, period 중 값이 있는 조건으로만 좁혀서 찾는다."""
    embedding = await get_embeddings().aembed_query(question)
    conditions = {"corp_name": corp_name, "report_type": report_type, "period": period}
    meta_filter = {key: value for key, value in conditions.items() if value}

    async with pool.connection() as conn:
        cur = await conn.execute(
            SEARCH_SQL, {"q": Vector(embedding), "k": k, "filter": Jsonb(meta_filter)}
        )
        rows = await cur.fetchall()

    return [RetrievedChunk(**row, dart_url=dart_url(row["rcept_no"])) for row in rows]


async def list_filings(corp_name: str | None = None) -> list[FilingRef]:
    """조회 가능한 공시 목록 (최근 기간부터). corp_name이 없으면 전체 기업."""
    async with pool.connection() as conn:
        cur = await conn.execute(FILINGS_SQL, {"corp_name": corp_name})
        rows = await cur.fetchall()
    return [FilingRef(**row) for row in rows]

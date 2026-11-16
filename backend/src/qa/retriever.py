"""검색: 질문 → 임베딩 → pgvector 유사도 검색 → RetrievedChunk 목록.

1단계는 dense 검색만 한다 (필터, 키워드 검색, 리랭커 없음).
검색 SQL은 이 파일에만 둔다. DB 구조가 바뀌면 이 파일만 고친다.
"""

from pgvector import Vector

from src.db.session import pool
from src.llm.models import get_embeddings
from src.qa.schemas import RetrievedChunk

# <=> : 코사인 거리 (0에 가까울수록 비슷함). score는 1 - 거리 (1에 가까울수록 비슷함)
# 근거 정보(기업명, 공시명, 공시일)는 chunk.meta에서 읽는다. (docs/discussion.md 8번 결정)
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
ORDER BY embedding <=> %(q)s
LIMIT %(k)s
"""


def dart_url(rcept_no: str) -> str:
    """접수번호로 DART 원문 링크를 만든다."""
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


async def search(question: str, k: int = 5) -> list[RetrievedChunk]:
    """질문과 의미가 가까운 청크를 k개 찾는다 (유사도 높은 순)."""
    embedding = await get_embeddings().aembed_query(question)

    async with pool.connection() as conn:
        cur = await conn.execute(SEARCH_SQL, {"q": Vector(embedding), "k": k})
        rows = await cur.fetchall()

    return [RetrievedChunk(**row, dart_url=dart_url(row["rcept_no"])) for row in rows]

"""검색: 질문 → 임베딩 검색 + BM25 키워드 검색 → RRF로 합침 → RetrievedChunk 목록.

    _dense()  임베딩 검색. 뜻이 비슷한 청크 (pgvector 코사인 거리)
    _bm25()   키워드 검색. 질문의 단어가 들어 있는 청크 (chunk.bm25, backend/sql/bm25.sql)
    _rrf()    두 검색의 순위만 보고 합친다. 점수는 단위가 달라 비교하지 않는다

회사·공시 종류·기간 필터는 두 검색에 똑같이 건다. 리랭커와 주변 청크 붙이기는 없다.
검색 SQL은 이 파일에만 둔다. DB 구조가 바뀌면 이 파일만 고친다.
"""

import asyncio
from typing import Any, Literal

from pgvector import Vector
from psycopg.types.json import Jsonb

from src.db.session import pool
from src.llm.models import get_embeddings
from src.qa.schemas import FilingRef, RetrievedChunk

SearchMode = Literal["hybrid", "dense", "bm25"]  # dense, bm25는 비교 실험·디버깅용

PREFETCH = 50  # hybrid에서 각 검색이 RRF에 넘기는 청크 수
RRF_K = 60  # RRF 점수 = Σ 1 / (RRF_K + 순위)

# BM25 설정 (프로토타입 dart_rag/index/bm25.py와 같은 공식)
BM25_K1 = 1.2  # 같은 단어가 여러 번 나올 때 점수가 오르는 정도 (클수록 많이 오름)
BM25_B = 0.75  # 긴 청크를 깎는 정도 (0이면 길이 무시)
BM25_AVGDL = 405  # 청크 평균 토큰 수 (2026-11 측정값). 공시가 많이 늘면 다시 잰다
COMMON_RATIO = 0.5  # 청크의 이 비율보다 많이 나오는 토큰은 후보를 고를 때 뺀다 (점수에는 쓴다)

# 근거 정보(기업명, 공시명, 공시일)는 chunk.meta에서 읽는다.
CHUNK_COLUMNS = """
    c.chunk_id, c.kind, c.section_path, c.raw, c.rcept_no,
    c.meta->>'corp_name' AS corp_name,
    c.meta->>'report_nm' AS report_nm,
    c.meta->>'rcept_dt'  AS rcept_dt"""

# <=> : 코사인 거리 (0에 가까울수록 비슷함). score는 1 - 거리 (1에 가까울수록 비슷함)
# meta @> {...} : meta가 주어진 키·값을 모두 포함하는 청크만 (GIN 인덱스 ix_chunk_meta 사용)
# 조건이 없으면 {} 를 넘겨 전체를 검색한다.
DENSE_SQL = f"""
SELECT {CHUNK_COLUMNS},
    1 - (c.embedding <=> %(q)s) AS score
FROM chunk c
WHERE c.embedding IS NOT NULL
  AND c.meta @> %(filter)s
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
"""

# BM25: 질문 토큰마다  idf × tf·(k1+1) / (tf + k1·(1 − b + b·청크길이/평균길이))  를 더한다.
#   idf = ln(1 + (N − df + 0.5) / (df + 0.5))   드문 토큰일수록 크다
#   N   = BM25 대상 청크 수, df = 그 토큰이 들어 있는 청크 수 (필터와 무관하게 전체에서 센다)
#   tf  = 이 청크에 나온 횟수 (tsvector의 위치 개수), 청크길이 = 이 청크의 tf 합
# 질문은 저장할 때와 같은 bm25_tokens()로 자른다.
# @@ : 토큰이 들어 있는 청크 (GIN 인덱스 ix_chunk_bm25 사용)
BM25_SQL = f"""
WITH q AS (
    SELECT DISTINCT unnest(bm25_tokens(%(q)s)) AS tok
),
corpus AS (
    SELECT count(*)::float8 AS n FROM chunk WHERE bm25 IS NOT NULL
),
qd AS (  -- 질문 토큰별 df, idf (청크에 없는 토큰은 버린다)
    SELECT q.tok, d.df, d.df / corpus.n AS ratio,
           ln(1 + (corpus.n - d.df + 0.5) / (d.df + 0.5)) AS idf
    FROM q
    CROSS JOIN corpus
    CROSS JOIN LATERAL (
        SELECT count(*)::float8 AS df FROM chunk WHERE bm25 @@ quote_literal(q.tok)::tsquery
    ) d
    WHERE d.df > 0
),
pick AS (  -- 후보를 고를 토큰: 흔한 토큰은 빼고, 전부 흔하면 가장 드문 토큰 하나
    SELECT tok FROM qd WHERE ratio <= %(common)s
    UNION
    SELECT tok FROM (SELECT tok FROM qd ORDER BY df LIMIT 1) rarest
),
cand AS (  -- pick 토큰이 하나라도 있는 청크
    SELECT chunk_id, bm25 FROM chunk
    WHERE bm25 @@ (SELECT string_agg(quote_literal(tok), ' | ')::tsquery FROM pick)
      AND meta @> %(filter)s
),
terms AS (  -- 후보 청크의 토큰별 tf와 청크 길이
    SELECT cand.chunk_id, u.lexeme,
           cardinality(u.positions)::float8 AS tf,
           sum(cardinality(u.positions)) OVER (PARTITION BY cand.chunk_id)::float8 AS dl
    FROM cand CROSS JOIN LATERAL unnest(cand.bm25) u
),
scored AS (
    SELECT terms.chunk_id,
           sum(qd.idf * terms.tf * (%(k1)s + 1)
               / (terms.tf + %(k1)s * (1 - %(b)s + %(b)s * terms.dl / %(avgdl)s))) AS score
    FROM terms JOIN qd ON qd.tok = terms.lexeme
    GROUP BY terms.chunk_id
    ORDER BY score DESC, terms.chunk_id
    LIMIT %(k)s
)
SELECT {CHUNK_COLUMNS}, s.score
FROM scored s JOIN chunk c USING (chunk_id)
ORDER BY s.score DESC, c.chunk_id
"""

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
    mode: SearchMode = "hybrid",
) -> list[RetrievedChunk]:
    """질문에 맞는 청크를 k개 찾는다 (관련 높은 순).
    corp_name, report_type, period 중 값이 있는 조건으로만 좁혀서 찾는다.

    mode
        hybrid  임베딩 검색과 BM25 검색을 각각 PREFETCH개씩 하고 RRF로 합친다 (기본)
        dense   임베딩 검색만, bm25  BM25 검색만 (비교 실험·디버깅용)
    """
    conditions = {"corp_name": corp_name, "report_type": report_type, "period": period}
    meta_filter = Jsonb({key: value for key, value in conditions.items() if value})

    if mode == "dense":
        rows = await _dense(question, k, meta_filter)
    elif mode == "bm25":
        rows = await _bm25(question, k, meta_filter)
    else:
        dense, bm25 = await asyncio.gather(
            _dense(question, PREFETCH, meta_filter),
            _bm25(question, PREFETCH, meta_filter),
        )
        rows = _rrf([dense, bm25], k)

    return [RetrievedChunk(**row, dart_url=dart_url(row["rcept_no"])) for row in rows]


async def _dense(question: str, k: int, meta_filter: Jsonb) -> list[dict[str, Any]]:
    """임베딩 검색 상위 k개. score는 코사인 유사도."""
    embedding = await get_embeddings().aembed_query(question)
    async with pool.connection() as conn:
        cur = await conn.execute(DENSE_SQL, {"q": Vector(embedding), "k": k, "filter": meta_filter})
        return await cur.fetchall()


async def _bm25(question: str, k: int, meta_filter: Jsonb) -> list[dict[str, Any]]:
    """BM25 검색 상위 k개. score는 BM25 점수. 질문에 맞는 토큰이 없으면 빈 목록."""
    params = {
        "q": question,
        "k": k,
        "filter": meta_filter,
        "common": COMMON_RATIO,
        "k1": BM25_K1,
        "b": BM25_B,
        "avgdl": BM25_AVGDL,
    }
    async with pool.connection() as conn:
        cur = await conn.execute(BM25_SQL, params)
        return await cur.fetchall()


def _rrf(rankings: list[list[dict[str, Any]]], k: int) -> list[dict[str, Any]]:
    """순위 목록 여러 개를 RRF로 합쳐 상위 k개. 각 청크의 score는 RRF 점수로 바꾼다.
    두 검색 모두 상위인 청크가 가장 위로 오고, 한쪽에만 있는 청크는 순위대로 번갈아 들어온다."""
    rows: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            chunk_id = row["chunk_id"]
            rows.setdefault(chunk_id, row)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    top = sorted(scores, key=lambda chunk_id: -scores[chunk_id])[:k]
    return [{**rows[chunk_id], "score": scores[chunk_id]} for chunk_id in top]


async def list_filings(corp_name: str | None = None) -> list[FilingRef]:
    """조회 가능한 공시 목록 (최근 기간부터). corp_name이 없으면 전체 기업."""
    async with pool.connection() as conn:
        cur = await conn.execute(FILINGS_SQL, {"corp_name": corp_name})
        rows = await cur.fetchall()
    return [FilingRef(**row) for row in rows]

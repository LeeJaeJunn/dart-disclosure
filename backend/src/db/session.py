"""DB 커넥션 풀. 앱 전체가 풀 하나를 공유한다.

풀은 앱 시작 시 열고 종료 시 닫는다 (src/main.py의 lifespan).
사용:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT ...", {"k": 5})
        rows = await cur.fetchall()     # 각 행은 dict
"""

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.config import settings


async def _configure(conn: AsyncConnection) -> None:
    """새 연결마다 pgvector 타입을 등록한다 (파이썬 리스트 ↔ vector 변환)."""
    await register_vector_async(conn)


pool = AsyncConnectionPool(
    settings.database_url,
    open=False,                         # 앱 시작 시점에 연다
    configure=_configure,
    kwargs={"row_factory": dict_row},   # 조회 결과를 dict로 받는다
)

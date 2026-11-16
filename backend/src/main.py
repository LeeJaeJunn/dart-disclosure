from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.main import api_router
from src.db.session import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()       # 서버 시작: DB 커넥션 풀 열기
    yield
    await pool.close()      # 서버 종료: 풀 닫기


app = FastAPI(lifespan=lifespan)
app.include_router(api_router)

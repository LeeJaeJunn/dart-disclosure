from typing import Annotated

from fastapi import APIRouter, Query

from src.qa.answerer import answer
from src.qa.retriever import search
from src.qa.schemas import AskRequest, AskResponse, RetrievedChunk

router = APIRouter(prefix="/qa", tags=["qa"])


# 검색 결과 확인용 (LLM 답변 없이 검색만)
@router.get("/search")
async def search_chunks(
    question: Annotated[str, Query(min_length=1, description="검색할 질문")],
    k: Annotated[int, Query(ge=1, le=20, description="가져올 결과 수")] = 5,
) -> list[RetrievedChunk]:
    return await search(question, k)


# 테스트용: 질문 분류 없이 바로 검색 → 답변. pipeline(POST /qa/ask)을 만들면 삭제
@router.post("/answer")
async def search_and_answer(req: AskRequest) -> AskResponse:
    chunks = await search(req.question, req.top_k)
    return await answer(req.question, chunks)

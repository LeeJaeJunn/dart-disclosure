from typing import Annotated

from fastapi import APIRouter, Query

from src.qa.pipeline import ask
from src.qa.retriever import SearchMode, search
from src.qa.schemas import AskRequest, AskResponse, RetrievedChunk

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask")
async def ask_question(req: AskRequest) -> AskResponse:
    """질문에 답한다. 공시 질문이면 공시를 검색해 근거와 함께 답한다."""
    return await ask(req.question, req.top_k, req.history)


# 검색 결과 확인용 (LLM 답변 없이 검색만)
@router.get("/search")
async def search_chunks(
    question: Annotated[str, Query(min_length=1, description="검색할 질문")],
    k: Annotated[int, Query(ge=1, le=20, description="가져올 결과 수")] = 5,
    mode: Annotated[SearchMode, Query(description="hybrid: 임베딩+BM25 / dense: 임베딩만 / bm25: BM25만")] = "hybrid",
) -> list[RetrievedChunk]:
    return await search(question, k, mode=mode)

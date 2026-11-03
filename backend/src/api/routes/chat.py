from fastapi import APIRouter

from src.llm.openai import ChatRequest, ChatResponse
from src.llm.openai import chat as llm_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(req: ChatRequest) -> ChatResponse:
    return await llm_chat(req)

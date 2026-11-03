from openai import AsyncOpenAI
from pydantic import BaseModel
from src.config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


async def chat(req: ChatRequest) -> ChatResponse:
    response = await client.responses.create(
        model=settings.openai_model,
        input=req.message,
    )
    return ChatResponse(reply=response.output_text)
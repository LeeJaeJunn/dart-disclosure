"""LLM·임베딩 모델 생성. 기능 코드(rag 등)는 모델을 직접 만들지 않고 여기서 가져다 쓴다.

모델 이름은 .env(settings)에서 읽는다. 모델이나 제공자를 바꿀 때는 이 파일만 고친다.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config import settings


@lru_cache
def get_chat_model() -> ChatOpenAI:
    """답변·요약 생성용 채팅 모델 (OpenAI Responses API 사용)."""
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        use_responses_api=True,
    )


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """텍스트 임베딩 모델. DB의 chunk.embedding 과 반드시 같은 모델이어야 한다."""
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )

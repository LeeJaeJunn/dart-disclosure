import hashlib

from src.llm.models import get_embeddings

EMBEDDING_DIMENSIONS = 1536  # DB chunk.embedding의 vector(1536)과 같아야 한다
_BATCH_SIZE = 100


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# 내용이 같은 문장은 한 번만 호출하고, {content_hash(text): 벡터}로 반환한다.
async def embed_texts(texts: list[str]) -> dict[str, list[float]]:
    pending = {content_hash(text): text for text in texts}
    todo = list(pending.items())
    print(f"[embed] 대상 {len(texts)}개, 중복 제외 {len(todo)}개")

    vectors: dict[str, list[float]] = {}
    embeddings = get_embeddings()
    for start in range(0, len(todo), _BATCH_SIZE):
        batch = todo[start : start + _BATCH_SIZE]
        results = await embeddings.aembed_documents([text for _, text in batch])
        for (key, _), vector in zip(batch, results, strict=True):
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(f"임베딩 차원이 다릅니다: {len(vector)}")
            vectors[key] = vector
        print(f"[embed] {min(start + _BATCH_SIZE, len(todo))}/{len(todo)}개")
    return vectors

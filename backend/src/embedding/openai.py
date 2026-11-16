import hashlib
import json
import os
from pathlib import Path

from src.llm.models import get_embeddings

EMBEDDING_DIMENSIONS = 1536  # DB chunk.embedding의 vector(1536)과 같아야 한다
_BATCH_SIZE = 100


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# 결과를 내용 해시로 파일에 저장한다. 다시 실행하면 없는 문장만 호출한다.
async def embed_texts(texts: list[str], cache_path: Path) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    pending = {content_hash(text): text for text in texts}
    todo = [(key, text) for key, text in pending.items() if key not in cache]
    print(f"[embed] 대상 {len(pending)}개, 저장본 재사용 {len(pending) - len(todo)}개")

    embeddings = get_embeddings()
    for start in range(0, len(todo), _BATCH_SIZE):
        batch = todo[start : start + _BATCH_SIZE]
        vectors = await embeddings.aembed_documents([text for _, text in batch])
        for (key, _), vector in zip(batch, vectors, strict=True):
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(f"임베딩 차원이 다릅니다: {len(vector)}")
            cache[key] = vector
        _save(cache_path, cache)
        print(f"[embed] {min(start + _BATCH_SIZE, len(todo))}/{len(todo)}개")
    return cache


def _save(path: Path, cache: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache), encoding="utf-8")
    os.replace(temporary, path)

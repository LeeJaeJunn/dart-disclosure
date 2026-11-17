"""공시 1건 처리: DART 원문 → 파싱 → 청킹 → 임베딩. 중간 결과는 파일로 남기지 않는다.

    Disclosure (list.json 한 건)
     │  fetch_document()      ZIP을 풀어 본문 XML 문자열로
     ▼
    본문 XML ({rcept_no}.xml)
     │  parse_document()
     ▼
    ParsedDocument
     │  chunk_document()
     ▼
    ChunkedDocument
     │  embed_texts()         embed=true 청크의 text만
     ▼
    IngestResult
     │  save_filing()         src/ingest/loader.py
     ▼
    DB (filing / filing_table / chunk)

이 파일은 DB를 쓰지 않는다. 저장은 loader.save_filing()이 맡는다.
원문 XML은 보관하지 않는다. 규칙을 바꿔 다시 처리할 때는 DART에서 다시 받는다.
"""

from pydantic import BaseModel

from src.chunking.chunker import chunk_document
from src.chunking.models import Chunk, ChunkedDocument, ChunkingConfig, FilingInfo
from src.dart.client import Disclosure, DisclosureFile, fetch_document
from src.embedding.openai import content_hash, embed_texts
from src.parsing.document import parse_document


class IngestResult(BaseModel):
    document: ChunkedDocument  # filing, tables(filing_table), chunks(chunk)
    vectors: dict[str, list[float]]  # {content_hash(chunk.text): 벡터}

    # chunk.embedding에 넣을 값. embed=false인 청크는 None
    def embedding(self, chunk: Chunk) -> list[float] | None:
        return self.vectors[content_hash(chunk.text)] if chunk.embed else None


# is_latest는 여기서 정하지 않는다. 적재할 때 DB에서 같은 기간 공시끼리 비교해 정한다(loader.py).
async def ingest_filing(disclosure: Disclosure, config: ChunkingConfig | None = None) -> IngestResult:
    files = await fetch_document(disclosure.rcept_no)
    xml = _main_file(disclosure.rcept_no, files).content

    filing = FilingInfo(
        rcept_no=disclosure.rcept_no,
        corp_code=disclosure.corp_code,
        corp_name=disclosure.corp_name,
        report_nm=disclosure.report_nm,
        rcept_dt=disclosure.rcept_dt,
    )
    document = chunk_document(parse_document(xml), filing, config)
    vectors = await embed_texts([chunk.text for chunk in document.chunks if chunk.embed])

    return IngestResult(document=document, vectors=vectors)


# 원문 ZIP에는 본문({rcept_no}.xml) 외에 감사보고서 등 첨부 파일이 함께 온다. 본문만 쓴다.
def _main_file(rcept_no: str, files: list[DisclosureFile]) -> DisclosureFile:
    for file in files:
        if file.file_name == f"{rcept_no}.xml":
            return file
    names = ", ".join(file.file_name for file in files)
    raise ValueError(f"본문 파일 {rcept_no}.xml이 없습니다: {names}")

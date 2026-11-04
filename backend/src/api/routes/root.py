from typing import Annotated

from fastapi import APIRouter, Query

from src.dart.client import (
    CorpCode,
    Disclosure,
    DisclosureFile,
    DisclosureQuery,
    fetch_corp_codes,
    fetch_disclosures,
    fetch_document,
)

router = APIRouter(tags=["root"])


@router.get("/")
def root():
    return {"message": "Hello FastAPI"}


# 테스트용: 기업 API를 분리하면 삭제
@router.get("/test/corp-codes")
async def test_corp_codes(name: str = "", limit: int = 20) -> list[CorpCode]:
    corps = await fetch_corp_codes()
    return [corp for corp in corps if name in corp.corp_name][:limit]


# 테스트용: 공시 API를 분리하면 삭제
@router.get("/test/disclosures")
async def test_disclosures(
    query: Annotated[DisclosureQuery, Query()],
) -> list[Disclosure]:
    return await fetch_disclosures(query)


# 테스트용: 원문이 수 MB까지 커서 앞부분만 반환. 공시 API를 분리하면 삭제
@router.get("/test/documents/{rcept_no}")
async def test_documents(rcept_no: str, limit: int = 100000000) -> list[DisclosureFile]:
    files = await fetch_document(rcept_no)
    return [
        DisclosureFile(file_name=file.file_name, content=file.content[:limit])
        for file in files
    ]

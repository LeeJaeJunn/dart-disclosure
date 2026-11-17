from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.filing.repository import list_companies, list_filings
from src.filing.schemas import Company, Filing

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
async def get_companies() -> list[Company]:
    """공시가 저장된 기업 목록."""
    return await list_companies()


@router.get("/{corp_code}/filings")
async def get_company_filings(
    corp_code: str,
    latest_only: Annotated[
        bool, Query(description="true면 정정 전 공시를 빼고 최신 공시만 반환")
    ] = True,
) -> list[Filing]:
    """기업 1곳의 저장 공시 목록 (최근 공시일 순)."""
    filings = await list_filings(corp_code, latest_only)
    if not filings:
        raise HTTPException(status_code=404, detail="저장된 공시가 없는 기업입니다.")
    return filings

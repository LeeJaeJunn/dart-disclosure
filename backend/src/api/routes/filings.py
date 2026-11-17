from fastapi import APIRouter, HTTPException

from src.summary.repository import get_summary
from src.summary.schemas import FilingSummary

router = APIRouter(prefix="/filings", tags=["filings"])


@router.get("/{rcept_no}/summary")
async def get_filing_summary(rcept_no: str) -> FilingSummary:
    """공시 1건의 요약 (섹션별 결론, 본문 요약, 해석, 근거)."""
    summary = await get_summary(rcept_no)
    if summary is None:
        raise HTTPException(status_code=404, detail="요약이 없는 공시입니다.")
    return summary

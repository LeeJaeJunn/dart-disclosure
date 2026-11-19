"""공시 1건 적재: uv run python -m src.ingest <접수번호> --corp-code <고유번호> [--no-summary]

DART에서 원문을 받아 파싱·청킹·임베딩한 뒤 DB에 저장한다. 중간 결과는 파일로 남기지 않는다.
이어서 기업분석 보고서(analysis)를 만들어 저장한다 (src/summary/). --no-summary면 건너뛴다.
보고서 생성이 실패해도 공시는 이미 저장되어 남는다 (그 공시만 요약이 없다).
"""

import argparse
import asyncio

from src.chunking.models import ChunkedDocument
from src.dart.client import Disclosure, DisclosureQuery, fetch_disclosures
from src.db.session import pool
from src.ingest.loader import save_filing
from src.ingest.pipeline import ingest_filing
from src.summary.builder import build_analysis
from src.summary.repository import save_analysis


async def main() -> None:
    parser = argparse.ArgumentParser(description="DART 공시 1건을 처리해 DB에 적재한다.")
    parser.add_argument("rcept_no", help="접수번호 14자리. 예: 20240312000736")
    parser.add_argument("--corp-code", required=True, help="DART 기업 고유번호 8자리. 예: 00126380 (삼성전자)")
    parser.add_argument("--no-summary", action="store_true", help="기업분석 보고서(analysis)를 만들지 않는다")
    args = parser.parse_args()

    disclosure = await _find_disclosure(args.rcept_no, args.corp_code)
    result = await ingest_filing(disclosure)
    doc = result.document

    await pool.open()
    try:
        async with pool.connection() as conn:
            await save_filing(conn, result)
        embedded = sum(chunk.embed for chunk in doc.chunks)
        print(
            f"[ingest] {disclosure.corp_name} {disclosure.report_nm} ({disclosure.rcept_no}): "
            f"표 {len(doc.tables)}개, 청크 {len(doc.chunks)}개 (임베딩 {embedded}개)"
        )

        if not args.no_summary:
            await _save_summary(doc)
    finally:
        await pool.close()


# 공시 저장과 별도로 처리한다. 실패해도 공시는 남기고 요약만 없다.
async def _save_summary(doc: ChunkedDocument) -> None:
    try:
        analysis = await build_analysis(doc)
        async with pool.connection() as conn:
            await save_analysis(conn, analysis)
    except Exception as error:  # noqa: BLE001  요약 실패가 적재 결과를 바꾸지 않게 한다
        print(f"[summary] 실패 (공시는 저장됨): {type(error).__name__}: {error}")
        return

    counts = {status: sum(s.status == status for s in analysis.sections) for status in ("done", "no_evidence", "error")}
    print(
        f"[summary] 섹션 {len(analysis.sections)}개 (완료 {counts['done']}, 근거 없음 {counts['no_evidence']}, "
        f"실패 {counts['error']}), 토큰 입력 {analysis.usage['input_tokens']:,} / 출력 {analysis.usage['output_tokens']:,}"
    )
    for section in analysis.sections:
        if section.status == "error":
            print(f"[summary]   {section.title}: {section.error}")


# 접수번호 앞 8자리는 접수일이다. 그 날짜와 기업으로 list.json을 조회해 공시 정보를 찾는다.
async def _find_disclosure(rcept_no: str, corp_code: str) -> Disclosure:
    day = rcept_no[:8]
    query = DisclosureQuery(corp_code=corp_code, bgn_de=day, end_de=day)
    for disclosure in await fetch_disclosures(query):
        if disclosure.rcept_no == rcept_no:
            return disclosure
    raise SystemExit(f"공시를 찾지 못했습니다: 접수번호 {rcept_no}, 고유번호 {corp_code}")


if __name__ == "__main__":
    # psycopg 비동기 연결은 Windows 기본 이벤트 루프(Proactor)에서 동작하지 않는다.
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)

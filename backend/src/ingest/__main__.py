"""공시 1건 적재: uv run python -m src.ingest <접수번호> --corp-code <고유번호>

DART에서 원문을 받아 파싱·청킹·임베딩한 뒤 DB에 저장한다. 중간 결과는 파일로 남기지 않는다.
"""

import argparse
import asyncio

from src.dart.client import Disclosure, DisclosureQuery, fetch_disclosures
from src.db.session import pool
from src.ingest.loader import save_filing
from src.ingest.pipeline import ingest_filing


async def main() -> None:
    parser = argparse.ArgumentParser(description="DART 공시 1건을 처리해 DB에 적재한다.")
    parser.add_argument("rcept_no", help="접수번호 14자리. 예: 20240312000736")
    parser.add_argument("--corp-code", required=True, help="DART 기업 고유번호 8자리. 예: 00126380 (삼성전자)")
    args = parser.parse_args()

    disclosure = await _find_disclosure(args.rcept_no, args.corp_code)
    result = await ingest_filing(disclosure)

    await pool.open()
    try:
        async with pool.connection() as conn:
            await save_filing(conn, result)
    finally:
        await pool.close()

    doc = result.document
    embedded = sum(chunk.embed for chunk in doc.chunks)
    print(
        f"[ingest] {disclosure.corp_name} {disclosure.report_nm} ({disclosure.rcept_no}): "
        f"표 {len(doc.tables)}개, 청크 {len(doc.chunks)}개 (임베딩 {embedded}개)"
    )


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

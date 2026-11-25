"""CLI 인자로 지정한 조건에 맞는 DART 공시를 한 번 조회한다."""

import argparse
import asyncio

from src.dart.client import DisclosureQuery, fetch_disclosures


async def main() -> None:
    parser = argparse.ArgumentParser(description="조건에 맞는 DART 공시를 한 번 조회한다.")
    parser.add_argument("--corp-code", help="DART 기업 고유번호 8자리")
    parser.add_argument("--bgn-de", help="조회 시작일 (YYYYMMDD)")
    parser.add_argument("--end-de", help="조회 종료일 (YYYYMMDD)")
    parser.add_argument("--pblntf-ty", choices=tuple("ABCDEFGHIJ"), help="DART 공시 유형 (예: A 정기공시)")
    args = parser.parse_args()

    query = DisclosureQuery(
        corp_code=args.corp_code,
        bgn_de=args.bgn_de,
        end_de=args.end_de,
        pblntf_ty=args.pblntf_ty,
    )
    for disclosure in await fetch_disclosures(query):
        print(f"{disclosure.corp_name} | {disclosure.report_nm} | {disclosure.rcept_no}")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)

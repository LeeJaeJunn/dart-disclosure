"""CLI 인자로 지정한 조건에 맞는 미적재 DART 공시를 한 번 조회한다."""

import argparse
import asyncio
import sys

from src.dart.client import DartApiError, DisclosureQuery, fetch_disclosures
from src.db.session import pool
from src.filing.repository import list_filings


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
    print("DART 공시 목록 조회 중...", file=sys.stderr)
    disclosures = await fetch_disclosures(query)

    print(f"DART 조회 결과: {len(disclosures)}건")

    if not disclosures:
        print("조회 조건에 맞는 공시가 없습니다.")
        return

    corp_codes = dict.fromkeys(disclosure.corp_code for disclosure in disclosures)
    stored_rcept_nos: set[str] = set()
    async with pool:
        for corp_code in corp_codes:
            filings = await list_filings(corp_code, latest_only=False)
            stored_rcept_nos.update(filing.rcept_no for filing in filings)

    # 적재 공시와 미적재 공시 분류
    existing_disclosures = [
        d for d in disclosures
        if d.rcept_no in stored_rcept_nos
    ]

    new_disclosures = [
        d for d in disclosures
        if d.rcept_no not in stored_rcept_nos
    ]

    print(f"기존 적재 공시: {len(existing_disclosures)}건")
    print(f"미적재 공시: {len(new_disclosures)}건")

    print("\n[기존 적재 공시 - 제외 대상]")
    for d in existing_disclosures:
        print(f"{d.corp_name} | {d.report_nm} | {d.rcept_no}")

    print("\n[미적재 공시 - 신규 적재 대상]")
    for d in new_disclosures:
        print(f"{d.corp_name} | {d.report_nm} | {d.rcept_no}")


if __name__ == "__main__":
    try:
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    except DartApiError as error:
        raise SystemExit(str(error)) from None
    except KeyboardInterrupt:
        print("공시 조회를 중단했습니다.", file=sys.stderr)
        raise SystemExit(130) from None

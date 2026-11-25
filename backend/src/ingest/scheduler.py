"""DART 공시를 조회하고 선택적으로 적재하는 독립 실행 CLI."""

import argparse
import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from src.dart.client import Disclosure, DisclosureQuery, fetch_disclosures
from src.db.session import pool
from src.filing.repository import list_filings
from src.ingest.loader import save_filing
from src.ingest.pipeline import ingest_filing

KST = timezone(timedelta(hours=9))
DEFAULT_CORP_CODES = ("00126380", "00164779")
PERIODIC_REPORT = re.compile(r"^(?:\[[^\]]+\]\s*)*(?:사업보고서|반기보고서|분기보고서)(?=\s|\(|$)")
logger = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("양의 정수를 입력하세요.")
    return number


def _date_arg(value: str) -> date:
    if not re.fullmatch(r"[0-9]{8}", value):
        raise argparse.ArgumentTypeError("날짜는 YYYYMMDD 형식으로 입력하세요.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("유효한 날짜를 입력하세요.") from None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DART 신규 공시를 조회하고 선택적으로 적재한다.")
    parser.add_argument("--corp-code", help="DART 기업 고유번호 8자리 (기본: 삼성전자, SK하이닉스)")
    parser.add_argument("--bgn-de", type=_date_arg, help="조회 시작일 (YYYYMMDD, 기본: KST 오늘의 6일 전)")
    parser.add_argument("--end-de", type=_date_arg, help="조회 종료일 (YYYYMMDD, 기본: KST 오늘)")
    parser.add_argument("--pblntf-ty", choices=tuple("ABCDEFGHIJ"), default="A", help="DART 공시 유형 (기본: A)")
    parser.add_argument("--interval", type=_positive_int, help="한 주기가 끝난 뒤 다음 실행까지 대기할 초 (생략 시 1회)")
    parser.add_argument("--ingest", action="store_true", help="기존 파이프라인으로 실제 적재 (생략 시 Dry Run)")
    parser.add_argument("--limit", type=_positive_int, help="--ingest 사용 시 한 주기당 최대 적재 시도 건수")
    args = parser.parse_args()
    if args.corp_code is not None and not re.fullmatch(r"[0-9]{8}", args.corp_code):
        parser.error("--corp-code는 숫자 8자리여야 합니다.")
    start, end = _date_range(args)
    if start > end:
        parser.error("조회 시작일은 종료일보다 늦을 수 없습니다.")
    return args


def _date_range(args: argparse.Namespace) -> tuple[date, date]:
    today = datetime.now(KST).date()
    return args.bgn_de or today - timedelta(days=6), args.end_de or today


async def _ingest_disclosures(disclosures: list[Disclosure]) -> bool:
    succeeded = 0
    for disclosure in disclosures:
        stage = "원문 처리·임베딩"
        try:
            result = await ingest_filing(disclosure)
            stage = "DB 저장"
            async with pool.connection() as conn:
                await save_filing(conn, result)
        except Exception as error:
            logger.error("적재 실패 | %s | %s | %s", disclosure.rcept_no, stage, type(error).__name__)
        else:
            succeeded += 1
            logger.info("적재 성공 | %s", disclosure.rcept_no)
    failed = len(disclosures) - succeeded
    logger.info("적재 결과 | 성공 %d건 | 실패 %d건", succeeded, failed)
    return failed == 0


async def run_once(args: argparse.Namespace) -> bool:
    """조회·중복 검사와 선택적 적재를 수행하고 성공 여부를 반환한다."""
    start, end = _date_range(args)
    corp_codes = (args.corp_code,) if args.corp_code else DEFAULT_CORP_CODES
    logger.info(
        "조회 시작 | %s | 기업 %s | 기간 %s~%s | 공시 유형 %s",
        "실제 적재" if args.ingest else "Dry Run", ", ".join(corp_codes), start, end, args.pblntf_ty,
    )
    stage = "조회 기간 확인"
    try:
        if start > end:
            logger.error("조회 시작일은 종료일보다 늦을 수 없습니다.")
            return False

        stage = "DART 목록 조회"
        disclosures: dict[str, Disclosure] = {}
        for corp_code in corp_codes:
            query = DisclosureQuery(
                corp_code=corp_code,
                bgn_de=start.strftime("%Y%m%d"),
                end_de=end.strftime("%Y%m%d"),
                pblntf_ty=args.pblntf_ty,
                last_reprt_at="N",
            )
            rows = await fetch_disclosures(query)
            logger.info("DART 조회 결과 | %s | %d건", corp_code, len(rows))
            for row in rows:
                if args.pblntf_ty != "A" or PERIODIC_REPORT.match(row.report_nm):
                    disclosures.setdefault(row.rcept_no, row)

        stage = "DB 연결 및 공시 조회"
        stored_rcept_nos: set[str] = set()
        for corp_code in dict.fromkeys(row.corp_code for row in disclosures.values()):
            filings = await list_filings(corp_code, latest_only=False)
            stored_rcept_nos.update(filing.rcept_no for filing in filings)

        existing = [row for row in disclosures.values() if row.rcept_no in stored_rcept_nos]
        pending = [row for row in disclosures.values() if row.rcept_no not in stored_rcept_nos]
        for label, rows in (("기존 적재 공시", existing), ("미적재 공시", pending)):
            logger.info("%s | %d건", label, len(rows))
            for row in rows:
                logger.info("%s | %s | %s | %s", label, row.corp_name, row.report_nm, row.rcept_no)

        if not args.ingest:
            logger.info("Dry Run | 적재 예정 후보 %d건 | 실제 적재 0건 (생략)", len(pending))
            return True

        targets = pending[:args.limit]
        logger.info("실제 적재 대상 | %d건", len(targets))
        return await _ingest_disclosures(targets)
    except Exception as error:
        # HTTP 오류 URL과 DB 예외 본문에 접속 정보가 포함될 수 있다.
        logger.error("%s 실패 | %s", stage, type(error).__name__)
        return False
    finally:
        logger.info("조회 주기 종료")


async def main(args: argparse.Namespace) -> int:
    async with pool:
        while True:
            succeeded = await run_once(args)
            if args.interval is None:
                logger.info("다음 실행 없음 (1회 실행)")
                return 0 if succeeded else 1
            next_run = datetime.now(KST) + timedelta(seconds=args.interval)
            logger.info("다음 실행 예정 | %s", next_run.isoformat(timespec="seconds"))
            await asyncio.sleep(args.interval)


class _KstFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, KST).isoformat(timespec="seconds")


def _configure_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = _KstFormatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler("scheduler.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    # 풀의 원본 연결 오류 대신 run_once에서 기록하는 오류 유형을 출력한다.
    logging.getLogger("psycopg.pool").setLevel(logging.CRITICAL)


if __name__ == "__main__":
    args = _parse_args()
    _configure_logging()
    try:
        exit_code = asyncio.run(main(args), loop_factory=asyncio.SelectorEventLoop)
    except KeyboardInterrupt:
        logger.info("사용자 요청으로 스케줄러 종료")
        exit_code = 130
    except Exception as error:
        logger.error("스케줄러 실행 실패 | %s", type(error).__name__)
        exit_code = 1
    raise SystemExit(exit_code)

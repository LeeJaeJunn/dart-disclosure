import argparse
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

from src.dart.client import DartApiError, Disclosure
from src.ingest import scheduler


def disclosure(number: str, name: str = "사업보고서 (2025.12)") -> Disclosure:
    return Disclosure(
        rcept_no=number, report_nm=name, rcept_dt="20261125", corp_code="00126380",
        corp_name="삼성전자", corp_cls="Y", flr_nm="", rm="",
    )


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original = disclosure("20261125000001")
        self.correction = disclosure("20261125000002", "[기재정정]사업보고서 (2025.12)")
        self.args = argparse.Namespace(
            corp_code="00126380", bgn_de=None, end_de=None,
            pblntf_ty="A", ingest=False, limit=None, interval=None,
        )
        self.fetch = self.enterContext(patch.object(scheduler, "fetch_disclosures", new_callable=AsyncMock))
        self.list_filings = self.enterContext(patch.object(scheduler, "list_filings", new_callable=AsyncMock))
        self.ingest = self.enterContext(patch.object(scheduler, "ingest_filing", new_callable=AsyncMock))
        self.save = self.enterContext(patch.object(scheduler, "save_filing", new_callable=AsyncMock))
        self.pool = self.enterContext(patch.object(scheduler, "pool", new_callable=MagicMock))
        self.list_filings.return_value = []

    async def test_dry_run_classifies_and_never_ingests(self):
        for rows, stored, counts in (
            ([self.original], [self.original], (1, 0)),
            ([self.original], [], (0, 1)),
            ([self.original, self.correction], [self.original], (1, 1)),
            ([], [], (0, 0)),
        ):
            with self.subTest(counts=counts), self.assertLogs(scheduler.logger, "INFO") as logs:
                self.fetch.return_value = rows
                self.list_filings.return_value = stored
                self.list_filings.reset_mock()
                self.assertEqual(await scheduler.main(self.args), 0)
            self.assertIn(f"기존 적재 공시 | {counts[0]}건", "\n".join(logs.output))
            self.assertIn(f"미적재 공시 | {counts[1]}건", "\n".join(logs.output))
            if rows:
                self.list_filings.assert_awaited_once_with("00126380", latest_only=False)
            else:
                self.list_filings.assert_not_awaited()
        self.ingest.assert_not_awaited()
        self.save.assert_not_awaited()
        self.pool.connection.assert_not_called()

    async def test_ingests_only_new_correction_with_existing_pipeline(self):
        self.args.ingest = True
        self.fetch.return_value = [self.original, self.correction]
        self.list_filings.return_value = [self.original]
        self.assertEqual(await scheduler.main(self.args), 0)
        self.ingest.assert_awaited_once_with(self.correction)
        self.save.assert_awaited_once_with(
            self.pool.connection.return_value.__aenter__.return_value,
            self.ingest.return_value,
        )

    async def test_limit_counts_failed_attempt(self):
        self.args.ingest = True
        self.args.limit = 1
        self.fetch.return_value = [self.original, self.correction]
        self.ingest.side_effect = RuntimeError("secret")
        with self.assertLogs(scheduler.logger, "INFO") as logs:
            self.assertEqual(await scheduler.main(self.args), 1)
        self.ingest.assert_awaited_once_with(self.original)
        self.save.assert_not_awaited()
        self.assertNotIn("secret", "\n".join(logs.output))

    async def test_continues_after_individual_ingest_failure(self):
        self.args.ingest = True
        self.fetch.return_value = [self.original, self.correction]
        result = Mock()
        self.ingest.side_effect = [RuntimeError("embedding failed"), result]

        with self.assertLogs(scheduler.logger, "INFO") as logs:
            self.assertEqual(await scheduler.main(self.args), 1)

        self.assertEqual(self.ingest.await_args_list, [call(self.original), call(self.correction)])
        self.save.assert_awaited_once_with(
            self.pool.connection.return_value.__aenter__.return_value, result,
        )
        messages = "\n".join(logs.output)
        self.assertIn(f"적재 실패 | {self.original.rcept_no}", messages)
        self.assertIn(f"적재 성공 | {self.correction.rcept_no}", messages)

    async def test_db_failure_returns_nonzero(self):
        self.fetch.return_value = [self.original]
        self.list_filings.side_effect = OSError("secret")
        with self.assertLogs(scheduler.logger, "ERROR") as logs:
            self.assertEqual(await scheduler.main(self.args), 1)
        self.assertIn("DB 연결 및 공시 조회 실패 | OSError", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    async def test_repeats_after_error_with_fresh_kst_dates(self):
        self.args.interval = 60
        self.fetch.side_effect = [DartApiError("secret"), []]
        clock = Mock(wraps=datetime)
        clock.now.side_effect = [
            datetime(2026, 11, day, hour, tzinfo=scheduler.KST)
            for day, hour in ((25, 23), (25, 23), (26, 0), (26, 0))
        ]
        sleep = AsyncMock(side_effect=[None, KeyboardInterrupt()])
        with patch.object(scheduler, "datetime", clock), patch.object(scheduler.asyncio, "sleep", sleep):
            with self.assertLogs(scheduler.logger, "INFO"), self.assertRaises(KeyboardInterrupt):
                await scheduler.main(self.args)
        self.assertEqual(sleep.await_args_list, [call(60), call(60)])
        queries = [entry.args[0] for entry in self.fetch.await_args_list]
        self.assertEqual([(q.bgn_de, q.end_de) for q in queries],
                         [("20261119", "20261125"), ("20261120", "20261126")])
        self.pool.__aenter__.assert_awaited_once()
        self.pool.__aexit__.assert_awaited_once()

    async def test_default_companies_and_report_filter(self):
        self.args.corp_code = None
        other = disclosure("20261125000003", "주요사항보고서")
        self.fetch.side_effect = [[self.correction, other], []]
        with self.assertLogs(scheduler.logger, "INFO") as logs:
            self.assertEqual(await scheduler.main(self.args), 0)
        queries = [entry.args[0] for entry in self.fetch.await_args_list]
        self.assertEqual([q.corp_code for q in queries], ["00126380", "00164779"])
        self.assertTrue(all(q.pblntf_ty == "A" and q.last_reprt_at == "N" for q in queries))
        self.assertIn(self.correction.rcept_no, "\n".join(logs.output))
        self.assertNotIn(other.rcept_no, "\n".join(logs.output))

    def test_cli_validation_and_explicit_conditions(self):
        for options in (["--limit", "0"], ["--interval", "-1"], ["--corp-code", "123"],
                        ["--bgn-de", "20260230"], ["--bgn-de", "20261125", "--end-de", "20261124"]):
            with self.subTest(options=options), patch("sys.argv", ["scheduler", *options]), patch("sys.stderr"):
                with self.assertRaises(SystemExit) as error:
                    scheduler._parse_args()
                self.assertEqual(error.exception.code, 2)
        with patch("sys.argv", [
            "scheduler", "--corp-code", "00164779", "--bgn-de", "20260101",
            "--end-de", "20261125", "--pblntf-ty", "B",
        ]):
            args = scheduler._parse_args()
        self.assertEqual(scheduler._date_range(args), (date(2026, 1, 1), date(2026, 11, 25)))
        self.assertEqual((args.corp_code, args.pblntf_ty), ("00164779", "B"))

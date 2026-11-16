import argparse
from pathlib import Path

from src.chunking.chunker import chunk_document
from src.chunking.models import ChunkingConfig, FilingInfo
from src.parsing.models import ParsedDocument


def main() -> None:
    defaults = ChunkingConfig()
    parser = argparse.ArgumentParser(description="파싱된 공시 JSON을 청크 JSON으로 변환한다.")
    parser.add_argument("input", type=Path, help="src.parsing이 만든 JSON 파일")
    parser.add_argument("--rcept-no", required=True)
    parser.add_argument("--corp-code", required=True)
    parser.add_argument("--corp-name", required=True)
    parser.add_argument("--report-nm", required=True, help='예: "사업보고서 (2023.12)"')
    parser.add_argument("--rcept-dt", required=True, help="YYYYMMDD")
    parser.add_argument("--not-latest", dest="is_latest", action="store_false", help="기재정정 전 공시")
    parser.add_argument("--target-chars", type=int, default=defaults.target_chars)
    parser.add_argument("--max-chars", type=int, default=defaults.max_chars)
    parser.add_argument("--table-chars", type=int, default=defaults.table_chars)
    parser.add_argument("--out", type=Path, help="기본값: data/chunks/<접수번호>.json")
    args = parser.parse_args()

    document = ParsedDocument.model_validate_json(args.input.read_text(encoding="utf-8"))
    filing = FilingInfo(
        rcept_no=args.rcept_no,
        corp_code=args.corp_code,
        corp_name=args.corp_name,
        report_nm=args.report_nm,
        rcept_dt=args.rcept_dt,
        is_latest=args.is_latest,
    )
    config = ChunkingConfig(
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        table_chars=args.table_chars,
    )
    result = chunk_document(document, filing, config)

    out = args.out or Path("data/chunks") / f"{filing.rcept_no}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()

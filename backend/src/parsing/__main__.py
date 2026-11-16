import argparse
import gzip
from pathlib import Path

from src.parsing.document import parse_document


def main() -> None:
    parser = argparse.ArgumentParser(description="DART 공시 원문 XML을 파싱해 JSON으로 저장한다.")
    parser.add_argument("input", type=Path, help=".xml 또는 .xml.gz 파일")
    parser.add_argument("--out", type=Path, help="기본값: data/parsed/<입력 파일명>.json")
    args = parser.parse_args()

    opener = gzip.open if args.input.suffix == ".gz" else open
    with opener(args.input, "rt", encoding="utf-8") as file:
        document = parse_document(file.read())

    name = args.input.name.removesuffix(".gz").removesuffix(".xml")
    out = args.out or Path("data/parsed") / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document.model_dump_json(indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()

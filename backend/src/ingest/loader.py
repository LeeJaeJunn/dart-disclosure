"""IngestResult를 DB에 저장한다. 적재 SQL은 이 파일에만 둔다.

공시 1건을 통째로 교체한다. 같은 rcept_no가 있으면 지우고 다시 넣으므로 몇 번 실행해도 결과가 같다.
filing을 지우면 ON DELETE CASCADE로 그 공시의 analysis(LLM 분석 보고서)도 지워진다.
규칙이 바뀌어 다시 적재한 공시는 분석도 다시 만든다.
"""

from pgvector import Vector
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from src.ingest.pipeline import IngestResult

# 같은 기간 정기보고서 중 접수번호가 가장 큰(가장 나중에 접수된) 공시만 최신으로 둔다.
# 접수번호는 접수일(YYYYMMDD) + 순번이라 크기 비교가 곧 접수 순서다.
_PERIODIC_REPORTS = ("사업보고서", "반기보고서", "분기보고서")

INSERT_FILING = """
INSERT INTO filing (rcept_no, corp_code, corp_name, report_nm, report_type, period,
                    rcept_dt, is_latest, dart_url, parser_version, chunker_version)
VALUES (%(rcept_no)s, %(corp_code)s, %(corp_name)s, %(report_nm)s, %(report_type)s, %(period)s,
        %(rcept_dt)s, %(is_latest)s, %(dart_url)s, %(parser_version)s, %(chunker_version)s)
"""

INSERT_TABLE = """
INSERT INTO filing_table (table_id, rcept_no, section_id, table_index, title, group_title,
                          xbrl_code, unit_raw, as_of, period_label, basis, basis_source,
                          context_before, notes, header, cells)
VALUES (%(table_id)s, %(rcept_no)s, %(section_id)s, %(table_index)s, %(title)s, %(group_title)s,
        %(xbrl_code)s, %(unit_raw)s, %(as_of)s, %(period_label)s, %(basis)s, %(basis_source)s,
        %(context_before)s, %(notes)s, %(header)s, %(cells)s)
"""

INSERT_CHUNK = """
INSERT INTO chunk (chunk_id, rcept_no, section_id, section_path, kind, table_id,
                   text, raw, meta, embedding)
VALUES (%(chunk_id)s, %(rcept_no)s, %(section_id)s, %(section_path)s, %(kind)s, %(table_id)s,
        %(text)s, %(raw)s, %(meta)s, %(embedding)s)
"""

UPDATE_LATEST = """
UPDATE filing
SET is_latest = (rcept_no = (
    SELECT max(rcept_no) FROM filing
    WHERE corp_code = %(corp_code)s AND report_type = %(report_type)s AND period = %(period)s
))
WHERE corp_code = %(corp_code)s AND report_type = %(report_type)s AND period = %(period)s
"""


async def save_filing(conn: AsyncConnection, result: IngestResult) -> None:
    doc = result.document
    filing = doc.filing
    async with conn.transaction():
        await conn.execute("DELETE FROM filing WHERE rcept_no = %s", (filing.rcept_no,))
        await conn.execute(
            INSERT_FILING,
            {
                **filing.model_dump(),
                "parser_version": doc.parser_version,
                "chunker_version": doc.chunker_version,
            },
        )
        async with conn.cursor() as cur:
            await cur.executemany(
                INSERT_TABLE,
                [
                    {
                        **table.model_dump(exclude={"context_before", "notes", "header", "rows"}),
                        "context_before": Jsonb(table.context_before),
                        "notes": Jsonb(table.notes),
                        "header": Jsonb(table.header),
                        "cells": Jsonb([[cell.model_dump() for cell in row] for row in table.rows]),
                    }
                    for table in doc.tables
                ],
            )
            await cur.executemany(
                INSERT_CHUNK,
                [
                    {
                        **chunk.model_dump(exclude={"embed", "meta"}),
                        "meta": Jsonb(chunk.meta),
                        "embedding": _vector(result.embedding(chunk)),
                    }
                    for chunk in doc.chunks
                ],
            )
        # 정정공시를 넣으면 같은 기간의 옛 공시가 최신이 아니게 된다. 옛 공시를 나중에 넣어도 결과는 같다.
        if filing.report_type in _PERIODIC_REPORTS:
            await conn.execute(UPDATE_LATEST, filing.model_dump(include={"corp_code", "report_type", "period"}))


def _vector(values: list[float] | None) -> Vector | None:
    return Vector(values) if values is not None else None

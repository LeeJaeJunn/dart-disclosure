-- BM25 키워드 검색용 컬럼 (chunk.bm25)
--
-- 실행 (저장소 루트에서, DB마다 한 번):
--   docker compose exec -T db psql -U disclosure -d disclosure < backend/sql/bm25.sql
-- 여러 번 실행해도 된다.
--
-- chunk.bm25는 DB가 chunk.text로부터 자동 계산한다 (generated column).
-- 적재 코드는 이 컬럼을 넣지 않는다. 행이 INSERT·UPDATE되면 PostgreSQL이 다시 계산한다.
-- 검색 SQL과 BM25 점수 공식은 src/qa/retriever.py에 있다.
--
-- 토큰 규칙을 바꾸면 이미 저장된 값은 다시 계산되지 않는다.
-- 이때는 컬럼을 지우고(ALTER TABLE chunk DROP COLUMN bm25) 이 파일을 다시 실행한다.

-- 토큰 규칙 (프로토타입 RegexTokenizer와 같음)
--   한글: 어절 + 두 글자씩 자른 조각  (매출액은 → 매출액은, 매출, 출액, 액은)  조사가 붙어도 매칭되게
--   영문: 소문자                      (HBM → hbm)
--   숫자: 콤마 제거                   (131,895,033 → 131895033)
CREATE OR REPLACE FUNCTION bm25_tokens(body text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  WITH w AS (
    SELECT t.m[1] AS word, t.ord
    FROM regexp_matches(lower(body), '[가-힣]+|[a-z]+|\d[\d,.]*', 'g') WITH ORDINALITY AS t(m, ord)
  )
  SELECT coalesce(array_agg(tok ORDER BY ord, pos), '{}')
  FROM (
    SELECT ord, 0 AS pos,
           CASE WHEN word ~ '^\d' THEN rtrim(replace(word, ',', ''), '.') ELSE word END AS tok
    FROM w
    UNION ALL
    SELECT ord, i, substr(word, i, 2)
    FROM w, generate_series(1, char_length(word) - 1) AS i
    WHERE word ~ '^[가-힣]'
  ) s
$$;

-- 토큰 → tsvector ('토큰':나온 위치들). 위치 개수가 BM25의 tf(나온 횟수)가 된다.
CREATE OR REPLACE FUNCTION bm25_tsv(body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT to_tsvector('simple', array_to_string(bm25_tokens(body), ' '))
$$;

-- 검색 대상은 text, table_kv (프로토타입과 같음).
-- section은 섹션 전체라 내용이 중복되고, table은 table_kv와 내용이 같아서 뺀다.
ALTER TABLE chunk ADD COLUMN IF NOT EXISTS bm25 tsvector
  GENERATED ALWAYS AS (CASE WHEN kind IN ('text', 'table_kv') THEN bm25_tsv(text) END) STORED;

CREATE INDEX IF NOT EXISTS ix_chunk_bm25 ON chunk USING gin (bm25);

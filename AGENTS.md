# AGENTS.md

DART 공시 기반 질의응답 서비스. 국내 상장기업 공시를 수집·구조화하고, 요약·질의응답·기간별 비교를 제공한다.
서비스 목표, 기능, 데이터 구조 등 전체 설계는 [docs/design.md](docs/design.md)를 참고한다.

## 단계

Phase 4와 Company Knowledge(기업 지식 비교·누적·업데이트)는 추후 구현이므로 요청이 없으면 구현하지 않는다.
자세한 범위는 [docs/design.md](docs/design.md)의 `추후 구현` 섹션을 참고한다.

## 구조

```
Disclosure/
├── backend/            # FastAPI (Python 3.14, uv)
│   ├── pyproject.toml
│   ├── .env            # 비밀값. 커밋 금지 (.env.example 참고)
│   └── src/
│       ├── main.py     # FastAPI app (entrypoint: src.main:app)
│       ├── config.py   # pydantic-settings로 .env 로드
│       ├── api/
│       │   ├── main.py # 기능별 라우터를 api_router로 통합
│       │   └── routes/ # 기능별 엔드포인트 (root.py, chat.py)
│       ├── dart/       # DART OpenAPI 호출
│       └── llm/        # OpenAI 호출
├── frontend/           # Vite + React 19 + TypeScript, pnpm
└── docs/
    ├── design.md       # 서비스 설계 문서
    └── discussion.md   # 팀 논의 사항 (미확정)
```

## DB 구조

PostgreSQL 18 + pgvector. 루트의 `docker-compose.yml`로 실행한다. (`localhost:5433`, DB·User·Password 모두 `disclosure`)
현재 스키마는 팀원이 공유한 덤프(`disclosure-*.dump`)로 복원한 것이며, 마이그레이션 코드는 아직 없다.
모든 테이블은 `rcept_no`(접수번호)로 `filing`에 연결되고, 공시를 삭제하면 하위 데이터도 함께 삭제된다(`ON DELETE CASCADE`).

```
filing                        # 공시 메타데이터 (공시 1건 = 1행)
├── rcept_no         text         [필수] PK  접수번호
├── corp_code        text         [필수] DART 기업 고유번호
├── corp_name        text         [필수] 기업명
├── report_nm        text         [필수] 공시명 (예: 사업보고서 (2023.12))
├── report_type      text         [필수] 공시 유형 (예: 사업보고서)
├── period           text         [필수] 보고 기간 (예: 2023.12)
├── rcept_dt         text         [필수] 공시일 (YYYYMMDD)
├── is_latest        boolean      [필수] 같은 기간 공시 중 최신(정정 반영) 여부, 기본값 true
├── dart_url         text         [필수] DART 원문 링크
├── parser_version   text         [필수] 파서 버전 (예: p3)
├── chunker_version  text         [필수] 청크 분할 버전 (예: c3-cb144e)
└── loaded_at        timestamptz  [필수] 적재 시각, 기본값 now()

filing_table                  # 공시 안의 표를 구조화한 데이터
├── table_id         text         [필수] PK
├── rcept_no         text         [필수] FK → filing
├── section_id       text         [필수] 표가 속한 목차 섹션 ID
├── table_index      integer      [필수] 공시 안에서 표 순서
├── title            text         [선택] 표 제목 (예: 12. 차입금)
├── group_title      text         [선택] 상위 묶음 제목
├── xbrl_code        text         [선택] XBRL 코드 (예: {XBRL}NT_S_D822405)
├── unit_raw         text         [선택] 단위 원문 (예: 백만원)
├── as_of            text         [선택] 기준일
├── period_label     text         [선택] 당기 | 전기 등
├── basis            text         [필수] consolidated(연결) | separate(별도) | unknown
├── basis_source     text         [선택] basis 판단 근거 (xbrl | preceding_heading)
├── context_before   jsonb        [필수] 표 앞 문맥 문장 배열
├── notes            jsonb        [필수] 표 주석 배열
├── header           jsonb        [필수] 열 헤더 배열
└── cells            jsonb        [필수] 셀 2차원 배열 ({raw, row, column, type, unit})

chunk                         # RAG 검색 단위 (청크 + 임베딩)
├── chunk_id         text         [필수] PK
├── rcept_no         text         [필수] FK → filing
├── section_id       text         [필수] 목차 섹션 ID
├── section_path     text         [필수] 목차 경로 (예: III. 재무에 관한 사항 > 5. 재무제표 주석)
├── kind             text         [필수] section(섹션 전체) | text(본문) | table(표) | table_kv(표를 "항목=값"으로 편 것)
├── table_id         text         [선택] FK → filing_table (kind가 table, table_kv일 때)
├── text             text         [필수] 검색·임베딩용 텍스트 (앞에 [기업 | 공시 | 섹션] 문맥 포함)
├── raw              text         [필수] 원문 텍스트
├── meta             jsonb        [필수] 필터용 메타데이터 (corp_code, corp_name, report_nm, report_type,
│                                        period, year, rcept_dt, section_title, section_level, tags 등)
└── embedding        vector(1536) [선택] 임베딩. section은 전부, table은 대부분 비어 있음

analysis                      # LLM 기업분석 보고서 (공시 1건 × 템플릿 1개 = 1행)
├── rcept_no         text         [필수] PK, FK → filing
├── template         text         [필수] PK  분석 양식 (예: company_analysis)
├── title            text         [필수] 보고서 제목
├── version          text         [필수] 분석 로직·프롬프트 버전
├── model            text         [필수] 사용한 LLM 모델
├── parser_version   text         [필수] 사용한 파서 버전
├── chunker_version  text         [필수] 사용한 청크 분할 버전
├── usage            jsonb        [필수] {input_tokens, output_tokens, usd}
├── created_at       timestamptz  [필수] 생성 시각, 기본값 now()
└── sections         jsonb        [필수] 섹션 객체 배열
    └── [ ]                           # summary, overview, financials, sales, operations, risk, management, shareholders
        ├── id, kind, title, status   섹션 식별자, summary | section, 제목, 생성 상태
        ├── headline        string        한 줄 결론
        ├── overview        string        본문 요약 (원문에서 확인한 사실)
        ├── interpretation  string[]      LLM 해석
        ├── watch           string[]      지켜볼 항목
        ├── table_markdown  string        섹션 표 (없으면 "")
        ├── sources         object[]      근거 {rcept_no, source, section, period, quote, url, chunk_id, verified, problems, rcept_dt, report_nm}
        ├── check           object        근거 검증 요약 {n_evidence, n_unverified, table_unverified_numbers}
        └── diag            object        디버깅용 진단 정보
```

알려진 문제 (팀원과 정리 예정, 자세한 내용과 선택지는 [docs/discussion.md](docs/discussion.md))

- `analysis.sections[].sources[].chunk_id`가 `wiki:` 접두어를 갖고 있어 `chunk.chunk_id`와 바로 연결되지 않는다.
- `analysis.sections[].sources[]`의 `rcept_dt`, `report_nm`이 null이다. 공시 정보는 `filing`에서 조인해 쓴다.
- 기업 테이블이 없다. 기업명은 `filing`, `chunk.meta`에 문자열로 중복 저장되어 있다.

## 명령어

백엔드 (`backend/`에서 실행)

- 개발 서버: `uv run fastapi dev` → http://localhost:8000, API 문서는 `/docs`
- 패키지 추가: `uv add <package>` (`pip install` 사용 금지)
- 의존성 동기화: `uv sync`

프론트엔드 (`frontend/`에서 실행)

- 개발 서버: `pnpm dev`
- 빌드: `pnpm build`
- 린트: `pnpm lint` (ESLint)
- 패키지 추가: `pnpm add <package>` (npm, yarn 사용 금지)

## 규칙

- 백엔드 기능 코드는 `backend/src/` 아래 기능별 폴더에 작성한다. (예: `src/llm/`)
- 엔드포인트는 `src/api/routes/`에 기능별 파일로 작성하고, `src/api/main.py`에 `include_router`로 등록한다. `src/main.py`에 직접 추가하지 않는다.
- 환경 변수와 API 키는 `backend/.env`에 두고 `config.py`의 `Settings`를 통해서만 읽는다. 새 설정을 추가하면 `.env.example`도 함께 갱신한다.
- 요청과 응답 스키마는 Pydantic 모델로 정의한다.
- LLM 호출은 `openai` SDK의 Responses API(`client.responses.create`)를 사용하고, 모델 이름은 코드에 하드코딩하지 않고 `settings.openai_model`을 사용한다.
- 공시 데이터에서 나온 모든 답변과 요약에는 근거(공시명, 공시일, 접수번호, 원문 위치, DART 링크)를 연결한다. 원문에서 확인한 사실과 LLM의 해석은 구분한다.
- 팀원과 논의가 필요한 사항은 `docs/discussion.md`에 기존 항목 형식(상태, 현황, 선택지, 결론)으로 추가한다. 이 파일의 `결정됨`이 아닌 항목은 확정된 방향으로 보고 구현하지 않는다.

## 기술 방향 (계획, 미확정)

- DB: PostgreSQL + pgvector (메타데이터, Company Knowledge, 벡터 검색을 한 DB에서 처리)
- 질의응답 파이프라인(Phase 3)과 Company Knowledge 업데이트 로직에 LangGraph 도입. Phase 1~2는 LangChain으로 구현한다.
- DART OpenAPI: `corpCode.xml`(기업 고유번호), `list.json`(공시 목록), `document.xml`(공시 원문)

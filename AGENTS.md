# AGENTS.md

DART 공시 기반 질의응답 서비스. 국내 상장기업 공시를 수집·구조화하고, 요약·질의응답·기간별 비교를 제공한다.
서비스 목표, 기능, 데이터 구조 등 전체 설계는 [docs/design.md](docs/design.md)를 참고한다.

## 현재 단계

Phase 1(공시 수집 및 기업 페이지) 시작 전. 현재 구현된 것은 FastAPI 기본 앱과 OpenAI 호출 테스트용 `POST /chat`뿐이다.

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
└── docs/design.md      # 서비스 설계 문서
```

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

## 기술 방향 (계획, 미확정)

- DB: PostgreSQL + pgvector (메타데이터, Company Knowledge, 벡터 검색을 한 DB에서 처리)
- 질의응답 파이프라인(Phase 3)과 Company Knowledge 업데이트 로직에 LangGraph 도입. Phase 1~2는 일반 함수로 구현한다.
- DART OpenAPI: `corpCode.xml`(기업 고유번호), `list.json`(공시 목록), `document.xml`(공시 원문)

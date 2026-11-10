# Disclosure

DART에 공개된 국내 상장기업의 공시를 수집·구조화하고, 요약·질의응답·기간별 비교를 제공하는 서비스입니다.

서비스 목표와 기능, 데이터 구조는 [설계 문서](docs/design.md)를 참고하세요.

## 사전 준비

- Python 3.14, [uv](https://docs.astral.sh/uv/)
- Node.js, [pnpm](https://pnpm.io/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (DB 실행용)
- OpenAI API 키

## 실행

### 데이터베이스

PostgreSQL 18 + pgvector를 Docker로 실행합니다. 프로젝트 루트에서 실행하세요.

```bash
docker compose up -d     # DB 실행
docker compose ps        # STATUS가 (healthy)이면 준비 완료
```

처음 한 번은 pgvector 확장을 켭니다.

```bash
docker compose exec db psql -U disclosure -d disclosure -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

| 항목                       | 값           |
| -------------------------- | ------------ |
| Host                       | `localhost`  |
| Port                       | `5433`       |
| Database / User / Password | `disclosure` |

- 중지: `docker compose down` (데이터는 유지)
- 데이터까지 초기화: `docker compose down -v`
- 로그 확인: `docker compose logs db`

### 백엔드

```bash
cd backend
uv sync
cp .env.example .env    # OPENAI_API_KEY 입력
uv run fastapi dev
```

http://localhost:8000 에서 실행되며, API 문서는 `/docs`에서 볼 수 있습니다.

### 프론트엔드

```bash
cd frontend
pnpm install
pnpm dev
```

터미널에 표시되는 주소로 접속하세요. `/api/*` 요청은 백엔드(8000번 포트)로 전달되므로 백엔드를 함께 실행해야 합니다.

## 디렉터리 규칙

### 백엔드

- 기능 코드는 `backend/src/` 아래에 기능별 폴더를 만들어 작성합니다. (예: `src/llm/`)
- GET, POST 같은 엔드포인트는 `src/api/routes/`에 기능별 파일로 작성합니다. (예: `routes/chat.py`)
- 새 라우트 파일을 만들면 `src/api/main.py`에 `include_router`로 등록합니다.

```
backend/src/
├── main.py          # 앱 생성, api_router 등록
├── config.py        # 환경 변수 설정
├── api/
│   ├── main.py      # 라우터 통합
│   └── routes/      # 엔드포인트
│       └── chat.py
└── llm/             # 기능별 폴더
    └── openai.py
```

## 커밋 규칙

```
타입: 변경 내용 요약
```

| 타입       | 용도                      |
| ---------- | ------------------------- |
| `feat`     | 새로운 기능               |
| `fix`      | 버그 수정                 |
| `refactor` | 동작 변경 없는 코드 개선  |
| `docs`     | 문서 수정                 |
| `test`     | 테스트 추가, 수정         |
| `chore`    | 설정, 의존성 등 기타 작업 |

- 요약은 한글로, 무엇을 바꿨는지 짧게 적습니다.
- 커밋 하나에는 관련된 변경만 담습니다.
- `.env`와 API 키는 커밋하지 않습니다.

예시

```
feat: DART 공시 목록 조회 추가
fix: 오래된 공시의 파일명 경로 제거
docs: 커밋 규칙 추가
```

## 브랜치 규칙

`main`은 항상 실행되는 상태로 유지합니다. `main`에 직접 커밋하지 않고, 작업은 브랜치에서 한 뒤 `main`에 merge합니다.

### 브랜치 이름

```
작업자/작업내용
```

- 작업자는 각자의 영문 이름이나 GitHub 아이디를 씁니다.
- 작업 내용은 영어 소문자와 `-`로 짧게 적습니다.

예시

```
jaejun/qa-retriever
jaejun/qa-ask-api
```

### 작업 순서

```bash
# 1. 브랜치 만들기
git switch main
git pull                                       # 최신 main 받기
git switch -c jaejun/qa-retriever

# 2. 작업 후 커밋 (필요하면 브랜치도 push해서 백업)
git push -u origin jaejun/qa-retriever

# 3. main에 merge
git switch main
git pull                                       # 그사이 바뀐 main 받기
git merge --no-ff jaejun/qa-retriever          # 브랜치 작업을 merge 커밋으로 묶어서 합치기
git push                                       # merge 결과 올리기
```

### 주의

- 작업이 길어지면 중간에 `main`을 받아 충돌을 미리 해결합니다. (`git pull origin main`)
- merge 중 충돌이 나면 해결한 뒤 실행되는지 확인하고 push합니다.

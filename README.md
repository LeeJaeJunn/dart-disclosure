# Disclosure

DART에 공개된 국내 상장기업의 공시를 수집·구조화하고, 요약·질의응답·기간별 비교를 제공하는 서비스입니다.

서비스 목표와 기능, 데이터 구조는 [설계 문서](docs/design.md)를 참고하세요.

## 사전 준비

- Python 3.14, [uv](https://docs.astral.sh/uv/)
- Node.js, [pnpm](https://pnpm.io/)
- OpenAI API 키

## 실행

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

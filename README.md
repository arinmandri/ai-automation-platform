# Automation Platform

[![CI](https://github.com/arinmandri/ai-automation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/arinmandri/ai-automation-platform/actions/workflows/ci.yml)

AI 업무 자동화 B2B SaaS의 Phase 1 기반 저장소입니다. 현재 범위는 재현 가능한 개발 환경, PostgreSQL 멀티테넌트 보안, 실행 lease/fencing 기반 함수 및 CI입니다. 인증과 실제 AI 실행 엔진은 아직 포함하지 않습니다.

## 요구사항

- Docker와 Docker Compose v2
- `uv`
- Python 3.13은 `uv`가 자동으로 설치할 수 있음

컨테이너 기준 버전은 PostgreSQL 17과 Redis 7.4입니다.

## 빠른 시작

```bash
cp .env.example .env
docker compose up -d --wait postgres redis
docker compose run --rm migrate
docker compose up -d api worker
```

PowerShell에서는 첫 명령 대신 다음을 사용합니다.

```powershell
Copy-Item .env.example .env
```

상태 확인:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

종료:

```bash
docker compose down
```

데이터 볼륨까지 삭제하는 `docker compose down -v`는 로컬 데이터를 영구 삭제하므로 테스트 환경에서만 사용합니다.

## 로컬 개발

의존성 설치:

```bash
uv sync --all-groups
```

API를 호스트에서 실행하려면 `.env`의 PostgreSQL 및 Redis hostname을 각각 `localhost`로 변경합니다.

```bash
uv run uvicorn automation_service.main:app --reload
```

Worker:

```bash
uv run celery -A automation_service.worker:celery_app worker --loglevel=INFO
```

## 마이그레이션

컨테이너에서 적용:

```bash
docker compose run --rm migrate
```

새 migration 생성:

```bash
uv run alembic revision -m "describe change"
```

초기화 스크립트는 환경별 login role을 만들고, migration login에 `app_migrator` membership을 부여합니다. Alembic은 연결 직후 `SET ROLE app_owner`를 실행하므로 생성되는 테이블과 함수는 로그인 불가능한 `app_owner`가 소유합니다.

runtime 역할은 다음과 같습니다.

| 역할 | 책임 |
|---|---|
| `app_api` | 명시적으로 허용된 tenant 테이블 읽기/쓰기 |
| `app_worker` | tenant 데이터 읽기 및 fencing 보안 함수 실행 |
| `app_control` | 향후 Scheduler/Dispatcher 보안 함수 실행 |
| `app_owner` | `NOLOGIN` 객체 소유자 |
| `app_migrator` | `app_owner`로 역할 전환 가능한 migration 그룹 |

## 테스트

통합 테스트는 migration이 적용된 로컬 PostgreSQL을 사용합니다.

Bash:

```bash
export DATABASE_URL='postgresql+asyncpg://automation_api:local-api-change-me@localhost:5432/automation'
export TEST_ADMIN_DATABASE_URL='postgresql+asyncpg://postgres:local-admin-change-me@localhost:5432/automation'
export TEST_API_DATABASE_URL="$DATABASE_URL"
export TEST_WORKER_DATABASE_URL='postgresql+asyncpg://automation_worker:local-worker-change-me@localhost:5432/automation'
uv run pytest --cov
```

PowerShell:

```powershell
$env:DATABASE_URL='postgresql+asyncpg://automation_api:local-api-change-me@localhost:5432/automation'
$env:TEST_ADMIN_DATABASE_URL='postgresql+asyncpg://postgres:local-admin-change-me@localhost:5432/automation'
$env:TEST_API_DATABASE_URL=$env:DATABASE_URL
$env:TEST_WORKER_DATABASE_URL='postgresql+asyncpg://automation_worker:local-worker-change-me@localhost:5432/automation'
uv run pytest --cov
```

정적 검사:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

통합 테스트는 다음을 검증합니다.

- `workspaces.id` 및 tenant table의 RLS 격리
- cross-tenant INSERT 거부
- active membership 없는 TenantSession 거부
- API 역할의 users 조회, DELETE, ALTER 및 control 함수 접근 거부
- 모든 애플리케이션 테이블의 `app_owner` 소유권
- stale fencing token의 step/checkpoint/attempt 원자적 거부

## 프로젝트 구조

```text
.
├── .github/workflows/ci.yml
├── alembic/
│   ├── env.py
│   └── versions/20261125_0001_initial.py
├── docker/postgres/init/00-bootstrap.sh
├── docs/phase1-report.md
├── src/automation_service/
│   ├── api/health.py
│   ├── db/session.py
│   ├── db/tenant.py
│   ├── config.py
│   ├── main.py
│   └── worker.py
├── tests/
│   ├── integration/
│   └── unit/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── uv.lock
```

## 보안 주의사항

- `.env`는 커밋하지 않습니다.
- `.env.example` 값은 로컬 전용 예시이며 운영에서 사용할 수 없습니다.
- API/Worker/Migrator DB 계정은 서로 다른 비밀번호를 사용합니다.
- queue payload의 workspace ID를 신뢰하지 않고 `control.claim_execution()` 결과를 사용합니다.
- Worker의 실행 변경은 직접 DML이 아니라 fencing 검증 함수를 사용합니다.

구현 결과와 남은 기술 부채는 [Phase 1 보고서](docs/phase1-report.md)를 참고하십시오.

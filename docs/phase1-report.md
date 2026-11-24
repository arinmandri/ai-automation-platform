# Phase 1 구현 보고서

## 범위

Phase 1은 프로젝트 기반, PostgreSQL 17 스키마, DB 역할/RLS, FastAPI health check, Celery worker 부트스트랩, 테스트 및 CI를 포함합니다. Cognito 인증, Scheduler/Dispatcher 프로세스, 실제 AI 호출 및 외부 연동 실행은 범위 밖입니다.

## v0.2 대비 반영된 변경

1. `workspaces` RLS는 존재하지 않는 `workspace_id` 대신 `id = app.current_workspace_id()`를 사용합니다.
2. `app_api`의 전체 테이블 CRUD를 제거하고 테이블별 최소 권한을 열거했습니다.
3. 모든 application object는 `SET ROLE app_owner` 상태에서 migration되어 `NOLOGIN app_owner`가 소유합니다.
4. 환경별 login role은 PostgreSQL bootstrap 스크립트가 생성합니다. `app_migrator`만 `app_owner`로 역할 전환할 수 있습니다.
5. execution ID를 전역 UUID primary key로 변경했습니다. cross-tenant claim은 execution ID 하나로 안전하게 식별됩니다.
6. `control.apply_execution_progress()`가 execution lease, attempt, step 및 checkpoint를 하나의 트랜잭션에서 검증합니다.
7. `RECONCILING`과 `UNKNOWN` 상태를 execution과 step에 추가했습니다.
8. `external_call_attempts`를 추가해 승인 소비와 외부 호출 사이 상태를 `PREPARED → SENT → CONFIRMED`로 기록할 수 있게 했습니다.
9. 예산 예약에 `period_start`, `deduplication_key`, `settlement_key`를 추가하고 reservation당 usage event를 하나로 제한했습니다.
10. invitations, documents, connection operations와 tenant 복합 FK를 추가했습니다.
11. Alembic version table은 `public` CREATE 권한을 넓히지 않고 `app_owner` 소유의 `app_meta` schema에 저장합니다.
12. 초기 DDL script는 SQLAlchemy의 async driver bridge를 통해 asyncpg simple-query protocol로 실행합니다.

## 승인 소비와 외부 호출 복구 정책

승인 실행 엔진은 Phase 2 구현 대상이지만 데이터 모델의 확정 정책은 다음과 같습니다.

- approval `CONSUMED` 변경과 `external_call_attempts(PREPARED)` INSERT를 같은 DB 트랜잭션에서 수행합니다.
- 네트워크 전송 직전에 call attempt를 `SENT`로 갱신합니다.
- 제공사 응답과 provider request ID를 확보하면 `CONFIRMED`로 변경합니다.
- `PREPARED`에서 장애가 발생한 경우 제공사 idempotency key가 있으면 동일 key로 전송할 수 있습니다.
- `SENT` 이후 결과가 없으면 execution을 `RECONCILING`으로 전환합니다.
- 제공사 조회 API로 결과를 확인할 수 없고 작업이 비멱등이면 `UNKNOWN`으로 전환하며 자동 재호출하지 않습니다.
- 승인을 재사용하지 않습니다. payload 변경에는 새 approval이 필요합니다.

## 승인·취소·lease 추가 전이

Phase 2 상태 머신에는 다음 전이를 반드시 포함합니다.

| 현재 상태 | 이벤트 | 다음 상태 |
|---|---|---|
| `WAITING_APPROVAL` | 승인 만료 | `REJECTED` (`APPROVAL_EXPIRED`) |
| `WAITING_APPROVAL` | 사용자 취소 | `CANCELLED` |
| `WAITING_APPROVAL` | 승인 | `QUEUED` |
| `RUNNING` | lease 만료 + 취소 요청 없음 | `QUEUED` |
| `CANCEL_REQUESTED` | lease 만료 | `CANCELLED` |
| `RUNNING` | 외부 결과 불명 | `RECONCILING` |
| `RECONCILING` | 결과 확인 | `SUCCEEDED` 또는 `FAILED` |
| `RECONCILING` | 확인 불가 | `UNKNOWN` |

## 예산 정합성 정책

- reservation은 생성 시점의 `period_start`에 영구 귀속합니다. 월 경계가 지나도 다른 period로 이동하지 않습니다.
- `deduplication_key`로 같은 모델 호출의 중복 예약을 방지합니다.
- `settlement_key`와 reservation당 unique usage event로 중복 정산을 방지합니다.
- 실제 비용이 예약액보다 크면 실제 비용 전액을 `spent_microusd`에 기록합니다. 이로 인해 hard limit을 넘을 수 있으나 회계 원장을 축소하지 않습니다.
- 초과 발생 후 신규 예약은 차단하고 `BUDGET_OVERAGE` 운영 이벤트를 생성합니다.
- 원자적 reserve/settle 보안 함수는 AI 실행 엔진과 함께 Phase 2에서 구현합니다.

## 검증 결과

GitHub Actions 실행: <https://github.com/arinmandri/ai-automation-platform/actions/runs/45464434735>

검증 환경은 Ubuntu runner, Python 3.13.18, PostgreSQL 17, Redis 7.4입니다.

- Ruff lint: 통과
- Ruff format check: 통과
- mypy strict: 통과
- pytest: 13 passed, 1 warning, 1.61초
- coverage: 92.56% (`fail_under=80` 통과)
- Alembic 초기 upgrade: 통과
- Alembic downgrade-to-base 후 재-upgrade: 통과
- API/Worker Docker image build: 통과

남은 warning은 FastAPI/Starlette TestClient가 현재 `httpx` adapter를 deprecated로 표시하는 upstream 경고입니다. 테스트 실패나 runtime 오류는 아니며 의존성 조합이 안정화되면 갱신합니다.

## 미구현 항목 및 기술 부채

- Scheduler/Dispatcher/Reconciler 보안 함수와 프로세스
- 승인 및 외부 호출 상태 머신의 application service
- 예산 reserve/settle 함수와 overage event
- Cognito identity mapping과 workspace 생성 보안 함수
- Slack/REST/Webhook Safe HTTP Client
- Alembic migration 이후 SQLAlchemy domain model 매핑
- 운영용 KMS envelope encryption
- API request ID와 구조화 access log middleware
- Redis TLS/AUTH는 로컬 Compose에서 비활성화되어 있으며 운영 IaC에서 활성화해야 함

## Phase 2 착수 조건

- CI에서 migration upgrade/downgrade 통과
- RLS와 최소 권한 통합 테스트 통과
- stale fencing token 통합 테스트 통과
- Docker image build 통과
- GitHub main branch 보호와 required CI check 설정
- Phase 2 상태 전이 및 승인 복구 정책을 테스트 케이스로 먼저 고정

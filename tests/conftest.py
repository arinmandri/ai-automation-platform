import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"{name} is required for integration tests")
    return value


@pytest_asyncio.fixture(scope="session")
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(required_env("TEST_ADMIN_DATABASE_URL"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def api_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(required_env("TEST_API_DATABASE_URL"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def worker_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(required_env("TEST_WORKER_DATABASE_URL"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def tenant_data(admin_engine: AsyncEngine) -> dict[str, str]:
    values = {
        "user_1": "10000000-0000-0000-0000-000000000001",
        "user_2": "10000000-0000-0000-0000-000000000002",
        "workspace_1": "20000000-0000-0000-0000-000000000001",
        "workspace_2": "20000000-0000-0000-0000-000000000002",
        "agent": "30000000-0000-0000-0000-000000000001",
        "agent_version": "40000000-0000-0000-0000-000000000001",
        "execution": "50000000-0000-0000-0000-000000000001",
    }
    async with admin_engine.begin() as connection:
        await connection.execute(text("SET ROLE app_owner"))
        await connection.execute(
            text(
                """
                TRUNCATE TABLE
                    app.audit_logs,
                    app.ai_usage_events,
                    app.budget_reservations,
                    app.workspace_budgets,
                    app.idempotency_keys,
                    app.outbox_events,
                    app.external_call_attempts,
                    app.approval_requests,
                    app.execution_steps,
                    app.execution_attempts,
                    app.executions,
                    app.schedules,
                    app.connection_operations,
                    app.connections,
                    app.agent_versions,
                    app.agents,
                    app.documents,
                    app.invitations,
                    app.memberships,
                    app.workspaces,
                    app.user_identities,
                    app.users
                CASCADE
                """
            )
        )
        statements = [
            """
            INSERT INTO app.users (id, cognito_sub, normalized_email)
            VALUES
                (:user_1, 'sub-1', 'one@example.com'),
                (:user_2, 'sub-2', 'two@example.com')
            """,
            """
            INSERT INTO app.workspaces (id, name, slug)
            VALUES
                (:workspace_1, 'Tenant One', 'tenant-one'),
                (:workspace_2, 'Tenant Two', 'tenant-two')
            """,
            """
            INSERT INTO app.memberships (workspace_id, user_id, role)
            VALUES
                (:workspace_1, :user_1, 'OWNER'),
                (:workspace_2, :user_2, 'OWNER')
            """,
            """
            INSERT INTO app.agents (id, workspace_id, name, created_by)
            VALUES (:agent, :workspace_1, 'Test Agent', :user_1)
            """,
            """
            INSERT INTO app.agent_versions (
                id, workspace_id, agent_id, version, instructions,
                model_config, created_by
            ) VALUES (
                :agent_version, :workspace_1, :agent, 1, 'test',
                '{"model":"test"}'::jsonb, :user_1
            )
            """,
            """
            UPDATE app.agents
               SET current_version_id = :agent_version
             WHERE id = :agent
            """,
            """
            INSERT INTO app.executions (
                id, workspace_id, agent_version_id, trigger_type,
                status, input, next_dispatch_at, created_by
            ) VALUES (
                :execution, :workspace_1, :agent_version, 'MANUAL',
                'QUEUED', '{}'::jsonb, now(), :user_1
            )
            """,
        ]
        for statement in statements:
            await connection.execute(text(statement), values)
    return values

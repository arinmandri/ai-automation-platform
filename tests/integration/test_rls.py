from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from automation_service.db.tenant import (
    TenantAccessDeniedError,
    TenantPrincipal,
    TenantSessionFactory,
)

pytestmark = pytest.mark.integration


async def set_tenant_context(connection: object, workspace_id: str, actor_id: str) -> None:
    await connection.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.workspace_id', :value, true)"),
        {"value": workspace_id},
    )
    await connection.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.actor_id', :value, true)"),
        {"value": actor_id},
    )


async def test_workspace_and_tenant_rows_are_isolated(
    api_engine: AsyncEngine,
    tenant_data: dict[str, str],
) -> None:
    async with api_engine.begin() as connection:
        await set_tenant_context(
            connection,
            tenant_data["workspace_1"],
            tenant_data["user_1"],
        )
        visible_workspaces = (
            (await connection.execute(text("SELECT id FROM app.workspaces ORDER BY id")))
            .scalars()
            .all()
        )
        visible_memberships = (
            (await connection.execute(text("SELECT workspace_id FROM app.memberships")))
            .scalars()
            .all()
        )

    assert visible_workspaces == [UUID(tenant_data["workspace_1"])]
    assert visible_memberships == [UUID(tenant_data["workspace_1"])]


async def test_rls_rejects_cross_tenant_insert(
    api_engine: AsyncEngine,
    tenant_data: dict[str, str],
) -> None:
    with pytest.raises(DBAPIError):
        async with api_engine.begin() as connection:
            await set_tenant_context(
                connection,
                tenant_data["workspace_1"],
                tenant_data["user_1"],
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO app.invitations (
                        workspace_id, normalized_email, role, token_hash,
                        invited_by, expires_at
                    ) VALUES (
                        :workspace_id, 'intruder@example.com', 'MEMBER',
                        'not-a-real-token', :user_id, now() + interval '1 day'
                    )
                    """
                ),
                {
                    "workspace_id": tenant_data["workspace_2"],
                    "user_id": tenant_data["user_1"],
                },
            )


async def test_tenant_session_factory_requires_active_membership(
    api_engine: AsyncEngine,
    tenant_data: dict[str, str],
) -> None:
    sessions = async_sessionmaker(api_engine, expire_on_commit=False)
    factory = TenantSessionFactory(sessions)

    principal = TenantPrincipal(
        workspace_id=UUID(tenant_data["workspace_1"]),
        user_id=UUID(tenant_data["user_1"]),
    )
    async with factory.session(principal) as session:
        name = await session.scalar(text("SELECT name FROM app.workspaces"))
    assert name == "Tenant One"

    unauthorized = TenantPrincipal(
        workspace_id=UUID(tenant_data["workspace_2"]),
        user_id=UUID(tenant_data["user_1"]),
    )
    with pytest.raises(TenantAccessDeniedError):
        async with factory.session(unauthorized):
            pass

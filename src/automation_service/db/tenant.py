from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TenantAccessDeniedError(PermissionError):
    pass


@dataclass(frozen=True)
class TenantPrincipal:
    workspace_id: UUID
    user_id: UUID


class TenantSessionFactory:
    """Creates transaction-scoped sessions with PostgreSQL RLS context."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def session(self, principal: TenantPrincipal) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.workspace_id', :value, true)"),
                {"value": str(principal.workspace_id)},
            )
            await session.execute(
                text("SELECT set_config('app.actor_id', :value, true)"),
                {"value": str(principal.user_id)},
            )
            await session.execute(
                text("SELECT set_config('app.actor_type', 'user', true)"),
            )

            membership = await session.scalar(
                text(
                    """
                    SELECT 1
                      FROM app.memberships
                     WHERE workspace_id = :workspace_id
                       AND user_id = :user_id
                       AND status = 'ACTIVE'
                    """
                ),
                {
                    "workspace_id": principal.workspace_id,
                    "user_id": principal.user_id,
                },
            )
            if membership is None:
                raise TenantAccessDeniedError("active workspace membership is required")

            yield session

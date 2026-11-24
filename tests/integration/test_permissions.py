import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM app.users",
        "DELETE FROM app.workspaces",
        "ALTER TABLE app.workspaces DISABLE ROW LEVEL SECURITY",
        "SELECT * FROM control.claim_execution(gen_random_uuid(), gen_random_uuid(), 60)",
    ],
)
async def test_api_role_has_no_excess_privileges(
    api_engine: AsyncEngine,
    tenant_data: dict[str, str],
    statement: str,
) -> None:
    del tenant_data
    with pytest.raises(DBAPIError):
        async with api_engine.begin() as connection:
            await connection.execute(text(statement))


async def test_application_objects_are_owned_by_app_owner(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT n.nspname, c.relname, r.rolname
                      FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                      JOIN pg_roles r ON r.oid = c.relowner
                     WHERE n.nspname IN ('app', 'app_meta', 'control')
                       AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
                    """
                )
            )
        ).all()

    assert rows
    assert {row.rolname for row in rows} == {"app_owner"}

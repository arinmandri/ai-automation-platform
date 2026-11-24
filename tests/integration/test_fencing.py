from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_progress_updates_validate_execution_attempt_step_and_checkpoint_atomically(
    worker_engine: AsyncEngine,
    admin_engine: AsyncEngine,
    tenant_data: dict[str, str],
) -> None:
    worker_id = uuid4()
    step_id = uuid4()

    async with worker_engine.begin() as connection:
        claim = (
            await connection.execute(
                text(
                    """
                    SELECT * FROM control.claim_execution(
                        :execution_id, :worker_id, 60
                    )
                    """
                ),
                {
                    "execution_id": tenant_data["execution"],
                    "worker_id": worker_id,
                },
            )
        ).one()

    with pytest.raises(DBAPIError):
        async with worker_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    SELECT control.apply_execution_progress(
                        :execution_id, :attempt_id, :worker_id, :stale_fence,
                        :step_id, 0, 'MODEL', 'SUCCEEDED',
                        CAST(:step_input AS jsonb), CAST(:step_output AS jsonb),
                        'step-0', CAST(:checkpoint AS jsonb)
                    )
                    """
                ),
                {
                    "execution_id": tenant_data["execution"],
                    "attempt_id": claim.attempt_id,
                    "worker_id": worker_id,
                    "stale_fence": claim.fencing_token - 1,
                    "step_id": step_id,
                    "step_input": "{}",
                    "step_output": '{"answer":1}',
                    "checkpoint": '{"next":1}',
                },
            )

    async with admin_engine.connect() as connection:
        step_count = await connection.scalar(
            text("SELECT count(*) FROM app.execution_steps WHERE id = :id"),
            {"id": step_id},
        )
        checkpoint = await connection.scalar(
            text("SELECT checkpoint FROM app.executions WHERE id = :id"),
            {"id": tenant_data["execution"]},
        )

    assert step_count == 0
    assert checkpoint is None

    async with worker_engine.begin() as connection:
        await connection.execute(
            text(
                """
                SELECT control.apply_execution_progress(
                    :execution_id, :attempt_id, :worker_id, :fence,
                    :step_id, 0, 'MODEL', 'SUCCEEDED',
                    CAST(:step_input AS jsonb), CAST(:step_output AS jsonb),
                    'step-0', CAST(:checkpoint AS jsonb)
                )
                """
            ),
            {
                "execution_id": tenant_data["execution"],
                "attempt_id": claim.attempt_id,
                "worker_id": worker_id,
                "fence": claim.fencing_token,
                "step_id": step_id,
                "step_input": "{}",
                "step_output": '{"answer":1}',
                "checkpoint": '{"next":1}',
            },
        )

    async with admin_engine.connect() as connection:
        stored_fence = await connection.scalar(
            text("SELECT fencing_token FROM app.execution_steps WHERE id = :id"),
            {"id": step_id},
        )
        checkpoint = await connection.scalar(
            text("SELECT checkpoint FROM app.executions WHERE id = :id"),
            {"id": tenant_data["execution"]},
        )

    assert stored_fence == claim.fencing_token
    assert checkpoint == {"next": 1}

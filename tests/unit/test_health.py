import os
from collections.abc import AsyncIterator
from typing import Any

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://unused:unused@localhost/unused",
)

from fastapi.testclient import TestClient

from automation_service.dependencies import get_db_session
from automation_service.main import app


def test_liveness() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": None}


class FakeSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def execute(self, _: Any) -> None:
        if self.error is not None:
            raise self.error


def override_session(session: FakeSession) -> None:
    async def dependency() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db_session] = dependency


def test_readiness_success() -> None:
    override_session(FakeSession())
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_failure() -> None:
    override_session(FakeSession(RuntimeError("database unavailable")))
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}

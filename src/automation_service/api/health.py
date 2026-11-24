from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from automation_service.dependencies import get_db_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str | None = None


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable", database="unavailable")
    return HealthResponse(status="ok", database="ok")

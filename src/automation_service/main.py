from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from automation_service import __version__
from automation_service.api.health import router as health_router
from automation_service.config import get_settings
from automation_service.dependencies import database
from automation_service.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await database.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title="Automation Platform API",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()

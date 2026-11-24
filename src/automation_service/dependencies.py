from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from automation_service.config import get_settings
from automation_service.db.session import Database

_settings = get_settings()
database = Database(_settings.database_url.get_secret_value())


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in database.session():
        yield session

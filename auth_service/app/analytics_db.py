from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

analytics_engine = create_async_engine(
    settings.analytics_database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

analytics_session = async_sessionmaker(
    analytics_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_analytics_db():
    async with analytics_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

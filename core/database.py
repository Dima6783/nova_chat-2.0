"""
core/database.py — Асинхронная БД через SQLAlchemy
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings


# ── Движок БД ─────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,        # True для отладки SQL-запросов
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# ── Фабрика сессий ────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


async def get_db():
    """Dependency для FastAPI — возвращает сессию БД"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Создать все таблицы при старте (только для разработки)"""
    async with engine.begin() as conn:
        from models import user, chat, message, media, call  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

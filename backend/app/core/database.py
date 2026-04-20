import asyncio
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_BACKEND_ROOT = Path(__file__).parent.parent.parent

# Async engine — used by FastAPI routes and the job manager
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync engine — used by job handlers running in asyncio.to_thread
# Replace the driver name only, preserving the full path (including leading slashes)
_sync_url = str(settings.database_url).replace("sqlite+aiosqlite://", "sqlite://")
sync_engine = create_engine(
    _sync_url,
    connect_args={"check_same_thread": False},
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


def _apply_pragmas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.close()


event.listens_for(engine.sync_engine, "connect")(_apply_pragmas)
event.listens_for(sync_engine, "connect")(_apply_pragmas)


class Base(DeclarativeBase):
    pass


async def verify_connection() -> None:
    async with engine.connect() as conn:
        await conn.exec_driver_sql("SELECT 1")


async def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


async def close_db() -> None:
    await engine.dispose()
    sync_engine.dispose()

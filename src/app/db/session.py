from __future__ import annotations

import os
import re

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_RAW_URL = os.environ["DATABASE_URL"]
# asyncpg (unlike libpq) does not accept `sslmode` as a connect kwarg — strip it
# from the URL and pass SSL through connect_args instead.
DATABASE_URL = re.sub(r"[?&]sslmode=[^&]+", "", _RAW_URL)
_CONNECT_ARGS = {"ssl": True} if ("sslmode" in _RAW_URL or "neon.tech" in _RAW_URL) else {}

engine = create_async_engine(
    DATABASE_URL,
    connect_args=_CONNECT_ARGS,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, database_url: str) -> None:
        url = make_url(database_url)
        engine_kwargs: dict[str, object] = {
            "future": True,
            "pool_pre_ping": True,
        }
        self._is_sqlite = url.drivername.startswith("sqlite")
        self._sqlite_is_memory = self._is_sqlite and url.database in {None, "", ":memory:"}
        if self._is_sqlite:
            engine_kwargs["connect_args"] = {"timeout": 30}
        self._engine = create_async_engine(database_url, **engine_kwargs)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)
        if self._is_sqlite:
            self._configure_sqlite_pragmas()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self._engine.dispose()

    def _configure_sqlite_pragmas(self) -> None:
        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            if not self._sqlite_is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

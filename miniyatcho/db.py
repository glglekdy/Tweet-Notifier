"""SQLite 연결 하나를 봇 전체가 공유한다.

기능마다 자기 테이블만 쓰고, 스키마는 각 기능이 setup 에서 ensure_schema 로 만든다.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.open() 을 먼저 호출해야 합니다.")
        return self._conn

    async def ensure_schema(self, ddl: str) -> None:
        await self.conn.executescript(ddl)
        await self.conn.commit()

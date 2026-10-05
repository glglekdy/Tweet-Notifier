"""트위터 알림 기능의 테이블과 CRUD."""

from __future__ import annotations

import time
from dataclasses import dataclass

import aiosqlite

from miniyatcho.db import Database

# 트위터 스노플레이크 ID 의 기준 시각 (2010-11-04, ms)
TWITTER_EPOCH_MS = 1288834974657

SCHEMA = """
CREATE TABLE IF NOT EXISTS twitter_target (
    user_id      TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    client_name  TEXT NOT NULL,
    last_seen_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS twitter_subscription (
    user_id    TEXT    NOT NULL REFERENCES twitter_target(user_id) ON DELETE CASCADE,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    role_id    INTEGER,
    retweets   INTEGER NOT NULL DEFAULT 1,
    quotes     INTEGER NOT NULL DEFAULT 1,
    message    TEXT,                 -- 맞춤 멘트. NULL 이면 기본 멘트
    PRIMARY KEY (user_id, channel_id)
);
"""


async def ensure_schema(db: Database) -> None:
    """테이블을 만들고, 예전 버전 DB 에 없는 칸을 추가한다. 여러 번 실행해도 안전하다."""
    await db.ensure_schema(SCHEMA)
    async with db.conn.execute("PRAGMA table_info(twitter_subscription)") as cur:
        columns = {row["name"] for row in await cur.fetchall()}
    if "message" not in columns:
        await db.ensure_schema("ALTER TABLE twitter_subscription ADD COLUMN message TEXT;")


def snowflake_now(now_ms: int | None = None) -> int:
    """지금 시각에 해당하는 트윗 ID. 이보다 큰 ID 는 지금 이후에 올라온 트윗이다."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return (now_ms - TWITTER_EPOCH_MS) << 22


@dataclass(frozen=True)
class Target:
    user_id: str
    username: str
    client_name: str
    last_seen_id: int


@dataclass(frozen=True)
class Subscription:
    user_id: str
    guild_id: int
    channel_id: int
    role_id: int | None
    retweets: bool
    quotes: bool
    message: str | None = None


def _target(row: aiosqlite.Row) -> Target:
    return Target(row["user_id"], row["username"], row["client_name"], row["last_seen_id"])


def _subscription(row: aiosqlite.Row) -> Subscription:
    return Subscription(
        row["user_id"], row["guild_id"], row["channel_id"], row["role_id"],
        bool(row["retweets"]), bool(row["quotes"]), row["message"],
    )


class TwitterStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def _all(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.db.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def _write(self, sql: str, params: tuple = ()) -> None:
        await self.db.conn.execute(sql, params)
        await self.db.conn.commit()

    # ── 추적 대상 ──

    async def get_target(self, user_id: str) -> Target | None:
        rows = await self._all("SELECT * FROM twitter_target WHERE user_id = ?", (user_id,))
        return _target(rows[0]) if rows else None

    async def find_target_by_username(self, username: str) -> Target | None:
        rows = await self._all("SELECT * FROM twitter_target WHERE username = ?", (username.lower(),))
        return _target(rows[0]) if rows else None

    async def all_targets(self) -> list[Target]:
        return [_target(r) for r in await self._all("SELECT * FROM twitter_target ORDER BY username")]

    async def targets_for_client(self, client_name: str) -> list[Target]:
        rows = await self._all("SELECT * FROM twitter_target WHERE client_name = ? ORDER BY username", (client_name,))
        return [_target(r) for r in rows]

    async def count_by_client(self) -> dict[str, int]:
        rows = await self._all("SELECT client_name, COUNT(*) AS n FROM twitter_target GROUP BY client_name")
        return {r["client_name"]: r["n"] for r in rows}

    async def add_target(self, target: Target) -> None:
        """새 대상을 넣는다. 이미 있으면 username 만 갱신한다 (담당·last_seen 유지)."""
        await self._write(
            "INSERT INTO twitter_target (user_id, username, client_name, last_seen_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
            (target.user_id, target.username.lower(), target.client_name, target.last_seen_id),
        )

    async def set_client(self, user_id: str, client_name: str) -> None:
        await self._write("UPDATE twitter_target SET client_name = ? WHERE user_id = ?", (client_name, user_id))

    async def set_last_seen(self, user_id: str, tweet_id: int) -> None:
        await self._write("UPDATE twitter_target SET last_seen_id = ? WHERE user_id = ?", (tweet_id, user_id))

    async def delete_target(self, user_id: str) -> None:
        await self._write("DELETE FROM twitter_target WHERE user_id = ?", (user_id,))

    # ── 구독 ──

    async def upsert_subscription(self, sub: Subscription) -> None:
        """구독을 넣는다. 이미 있으면 역할·리트윗·인용만 덮어쓰고 맞춤 멘트는 유지한다."""
        await self._write(
            "INSERT INTO twitter_subscription (user_id, guild_id, channel_id, role_id, retweets, quotes, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, channel_id) DO UPDATE SET "
            "role_id = excluded.role_id, retweets = excluded.retweets, quotes = excluded.quotes",
            (sub.user_id, sub.guild_id, sub.channel_id, sub.role_id, int(sub.retweets), int(sub.quotes), sub.message),
        )

    async def set_message(self, user_id: str, channel_id: int, message: str | None) -> None:
        await self._write(
            "UPDATE twitter_subscription SET message = ? WHERE user_id = ? AND channel_id = ?",
            (message, user_id, channel_id),
        )

    async def subscriptions_for(self, user_id: str) -> list[Subscription]:
        rows = await self._all(
            "SELECT * FROM twitter_subscription WHERE user_id = ? ORDER BY channel_id", (user_id,)
        )
        return [_subscription(r) for r in rows]

    async def get_subscription(self, user_id: str, channel_id: int) -> Subscription | None:
        rows = await self._all(
            "SELECT * FROM twitter_subscription WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)
        )
        return _subscription(rows[0]) if rows else None

    async def guild_subscriptions(self, guild_id: int) -> list[tuple[Target, Subscription]]:
        rows = await self._all(
            "SELECT t.user_id, t.username, t.client_name, t.last_seen_id, "
            "s.guild_id, s.channel_id, s.role_id, s.retweets, s.quotes, s.message "
            "FROM twitter_subscription s JOIN twitter_target t ON t.user_id = s.user_id "
            "WHERE s.guild_id = ? ORDER BY t.username, s.channel_id",
            (guild_id,),
        )
        return [(_target(r), _subscription(r)) for r in rows]

    async def delete_subscription(self, user_id: str, channel_id: int) -> None:
        await self._write(
            "DELETE FROM twitter_subscription WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)
        )

    async def usernames_in_guild(self, guild_id: int) -> list[str]:
        rows = await self._all(
            "SELECT DISTINCT t.username FROM twitter_subscription s "
            "JOIN twitter_target t ON t.user_id = s.user_id WHERE s.guild_id = ? ORDER BY t.username",
            (guild_id,),
        )
        return [r["username"] for r in rows]

"""봇 본체.

Dishost 는 RAM 128MB 이므로 discord.py 의 캐시를 최대한 끈다. 슬래시 커맨드만 쓰기 때문에
멤버·메시지 캐시가 필요 없고, 이 둘이 상주 메모리의 대부분을 차지한다.

기능은 miniyatcho/features/<이름>/ 확장 하나로 붙이고 EXTENSIONS 에 등록한다.
한 기능의 로드가 실패해도 봇은 뜨고 나머지 기능은 동작한다.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Config
from .db import Database

log = logging.getLogger("miniyatcho")

EXTENSIONS: tuple[str, ...] = (
    "miniyatcho.features.twitter",
)


class Miniyatcho(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True  # 슬래시 커맨드와 채널·역할 조회에 필요한 최소치

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            # ── 메모리 절약 ──
            chunk_guilds_at_startup=False,
            member_cache_flags=discord.MemberCacheFlags.none(),
            max_messages=None,
        )
        self.config = config
        self.db = Database(config.db_path)
        self.failed_extensions: list[str] = []

    async def setup_hook(self) -> None:
        await self.db.open()

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("기능 로드: %s", ext)
            except Exception:
                log.exception("기능 로드 실패: %s (나머지 기능은 계속 동작합니다)", ext)
                self.failed_extensions.append(ext)

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("슬래시 커맨드 %d개를 서버 %s 에 동기화했습니다", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("슬래시 커맨드 %d개를 전역 동기화했습니다 (반영까지 최대 1시간)", len(synced))

    async def on_ready(self) -> None:
        log.info("%s 로그인 완료 (서버 %d개)", self.user, len(self.guilds))

    async def close(self) -> None:
        # 확장을 먼저 내려 각 기능이 백그라운드 작업을 정리하게 한 뒤 DB 를 닫는다.
        for ext in list(self.extensions):
            try:
                await self.unload_extension(ext)
            except Exception:
                log.exception("기능 언로드 실패: %s", ext)
        await super().close()
        await self.db.close()

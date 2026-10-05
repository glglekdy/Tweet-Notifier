"""관리자 알림 채널로 경고를 보낸다.

Dishost 로그는 들어가서 보기 번거로우므로, 운영자가 손써야 하는 상황(봇 계정 로그인 실패,
조회 제한 장기화)만 디스코드 채널로 알린다. 같은 key 는 clear 되기 전까지 다시 보내지 않는다.
"""

from __future__ import annotations

import logging

import discord

log = logging.getLogger("miniyatcho.twitter")


class Alerter:
    def __init__(self, bot: discord.Client, channel_id: int | None) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self._active: set[str] = set()

    async def raise_(self, key: str, text: str) -> None:
        log.warning("[관리자 알림] %s", text)
        if key in self._active:
            return
        self._active.add(key)
        if self.channel_id is None:
            return

        await self.bot.wait_until_ready()
        try:
            channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
            await channel.send(f"⚠️ {text}", allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            log.error("관리자 알림 채널(%s)로 보내지 못했습니다: %r", self.channel_id, exc)

    def clear(self, key: str) -> None:
        self._active.discard(key)

from unittest.mock import AsyncMock

import discord

from miniyatcho.bot import EXTENSIONS, Miniyatcho
from miniyatcho.config import Config


def make_bot(tmp_path):
    return Miniyatcho(Config.load({"DISCORD_TOKEN": "d", "TWITTER_TOKEN": "a:t", "DATA_DIR": str(tmp_path)}))


def test_memory_settings(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.intents.value == discord.Intents(guilds=True).value
    assert bot._connection.max_messages is None  # discord.py 는 공개 속성으로 노출하지 않음


async def test_failed_extension_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr("miniyatcho.bot.EXTENSIONS", ("miniyatcho.features.does_not_exist",))
    bot = make_bot(tmp_path)
    monkeypatch.setattr(bot.tree, "sync", AsyncMock(return_value=[]))
    await bot.setup_hook()
    assert bot.failed_extensions == ["miniyatcho.features.does_not_exist"]
    await bot.db.close()


def test_extensions_list():
    assert EXTENSIONS == ("miniyatcho.features.twitter",)

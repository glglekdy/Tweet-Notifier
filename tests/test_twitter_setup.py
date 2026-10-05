from types import SimpleNamespace

from miniyatcho.features.twitter import _start
from miniyatcho.features.twitter.accounts import ClientPool
from miniyatcho.features.twitter.alerts import Alerter
from tests.fakes import FakeBot, FakeChannel


async def test_start_failure_is_reported_not_swallowed(store, tmp_path):
    pool = ClientPool((("a", "t"),), tmp_path)

    async def boom():
        raise RuntimeError("x")
    pool.login_all = boom
    ch = FakeChannel(99)
    bot = FakeBot([ch])
    bot.config = SimpleNamespace(check_seconds=18)
    await _start(bot, store, pool, Alerter(bot, 99))  # 예외가 밖으로 새지 않아야 함
    assert len(ch.sent) == 1

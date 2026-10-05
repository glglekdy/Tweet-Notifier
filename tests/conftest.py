import pytest

from miniyatcho.db import Database
from miniyatcho.features.twitter.store import TwitterStore, ensure_schema


@pytest.fixture
async def store(tmp_path):
    db = Database(tmp_path / "t.db")
    await db.open()
    await ensure_schema(db)
    yield TwitterStore(db)
    await db.close()


@pytest.fixture
def poller_env(store, tmp_path):
    from types import SimpleNamespace

    from miniyatcho.features.twitter.accounts import ClientPool, ClientState
    from miniyatcho.features.twitter.alerts import Alerter
    from miniyatcho.features.twitter.poller import ClientPoller
    from miniyatcho.features.twitter.store import Subscription, Target  # noqa: F401
    from tests.fakes import FakeApp, FakeBot

    async def make(channels=(), subs=(), notifications=()):
        await store.add_target(Target("100", "foo", "a", 10))
        for sub in subs:
            await store.upsert_subscription(sub)
        pool = ClientPool((("a", "t"),), tmp_path)
        pool.states["a"] = ClientState("a", FakeApp("a", notifications=notifications if isinstance(notifications, Exception) else list(notifications)))
        bot = FakeBot(channels)
        poller = ClientPoller(bot, "a", pool, store, Alerter(bot, None), 18, send_retry_delay=0)
        return SimpleNamespace(poller=poller, store=store, pool=pool)

    return make

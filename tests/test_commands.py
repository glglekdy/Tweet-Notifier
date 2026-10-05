import pytest

from miniyatcho.features.twitter.accounts import ClientPool, ClientState
from miniyatcho.features.twitter.commands import do_add, do_remove, normalize_username
from miniyatcho.features.twitter.store import Subscription, Target
from tests.fakes import FakeApp, FakeUser


@pytest.fixture
def pool(tmp_path):
    p = ClientPool((("a", "t"), ("b", "t")), tmp_path)
    for name in ("a", "b"):
        p.states[name] = ClientState(name, FakeApp(name, users={"foo": FakeUser("100", "foo")}))
    return p


def test_normalize_username():
    for raw in ["foo", "@Foo", " FOO ", "https://x.com/Foo", "https://twitter.com/foo/", "x.com/foo/status/1"]:
        assert normalize_username(raw) == "foo"
    for raw in ["", "@", "foo bar", "a" * 16, "https://example.com/foo", "한글"]:
        assert normalize_username(raw) is None


async def add(store, pool, **kw):
    args = dict(username="foo", guild_id=1, channel_id=10, role_id=None, retweets=True, quotes=True, client=None)
    return await do_add(store, pool, **{**args, **kw})


async def test_add_new_picks_least_loaded_and_follows(store, pool):
    await store.add_target(Target("200", "bar", "a", 0))
    msg = await add(store, pool)
    assert "담당: b" in msg
    assert pool.states["b"].app.calls == [("follow", "100"), ("notify_on", "100")]
    t = await store.get_target("100")
    assert t.client_name == "b" and t.last_seen_id > 0


async def test_add_unknown_user(store, pool):
    assert "찾을 수 없어요" in await add(store, pool, username="nobody")
    assert await store.all_targets() == []


async def test_add_invalid_username(store, pool):
    assert await add(store, pool, username="foo bar") == "올바른 트위터 아이디가 아니에요."


async def test_add_no_ok_clients(store, pool):
    pool.mark_failed("a", "x")
    pool.mark_failed("b", "x")
    assert "로그인된 봇 계정이 없어요" in await add(store, pool)


async def test_add_follow_failure_writes_nothing(store, pool):
    async def boom(uid):
        raise RuntimeError("x")
    pool.states["a"].app.follow_user = boom
    assert "팔로우에 실패했어요" in await add(store, pool, client="a")
    assert await store.all_targets() == []


async def test_add_move_client_unwatches_old(store, pool):
    await add(store, pool, client="a")
    await add(store, pool, channel_id=11, client="b")
    assert (await store.get_target("100")).client_name == "b"
    assert ("unfollow", "100") in pool.states["a"].app.calls
    assert len(await store.subscriptions_for("100")) == 2


async def test_add_same_channel_overwrites(store, pool):
    await add(store, pool, role_id=7)
    await add(store, pool, role_id=None, retweets=False)
    assert await store.subscriptions_for("100") == [Subscription("100", 1, 10, None, False, True)]


async def test_remove_last_subscription_unwatches_and_deletes(store, pool):
    await add(store, pool, client="a")
    msg = await do_remove(store, pool, username="@foo", guild_id=1, channel_id=10)
    assert "중지했어요" in msg
    assert await store.get_target("100") is None
    assert ("unfollow", "100") in pool.states["a"].app.calls


async def test_remove_keeps_target_when_other_guild_subscribed(store, pool):
    await add(store, pool, client="a")
    await add(store, pool, guild_id=2, channel_id=20)
    await do_remove(store, pool, username="foo", guild_id=1, channel_id=10)
    assert await store.get_target("100") is not None
    assert ("unfollow", "100") not in pool.states["a"].app.calls


async def test_remove_rejects_other_guild_channel(store, pool):
    await add(store, pool, guild_id=2, channel_id=20)
    assert "추적하고 있지 않아요" in await do_remove(store, pool, username="foo", guild_id=1, channel_id=20)
    assert len(await store.subscriptions_for("100")) == 1


async def test_add_user_info_none_means_not_found(store, pool):
    async def none_info(username):
        return None
    pool.states["a"].app.get_user_info = none_info
    assert "찾을 수 없어요" in await add(store, pool, client="a")
    assert await store.all_targets() == []


async def test_add_protected_user_means_not_found(store, pool):
    from tweety.exceptions import UserProtected
    async def protected(username):
        raise UserProtected(403, "x", None)
    pool.states["a"].app.get_user_info = protected
    assert "찾을 수 없어요" in await add(store, pool, client="a")


async def test_add_lookup_error_returns_message(store, pool):
    async def boom(username):
        raise RuntimeError("network")
    pool.states["a"].app.get_user_info = boom
    msg = await add(store, pool, client="a")
    assert "가져오지 못했어요" in msg and "RuntimeError" in msg


async def test_add_warns_when_existing_owner_is_down(store, pool):
    await add(store, pool, client="a")
    pool.mark_failed("a", "x")
    msg = await add(store, pool, channel_id=11)
    assert "알림이 오지 않아요" in msg


async def test_remove_reports_unfollow_failure(store, pool):
    await add(store, pool, client="a")
    async def boom(uid):
        raise RuntimeError("x")
    pool.states["a"].app.disable_user_notification = boom
    msg = await do_remove(store, pool, username="foo", guild_id=1, channel_id=10)
    assert "중지했어요" in msg and "언팔로우하지 못했어요" in msg
    assert await store.get_target("100") is None


async def test_remove_reports_skipped_unfollow_when_owner_down(store, pool):
    await add(store, pool, client="a")
    pool.mark_failed("a", "x")
    msg = await do_remove(store, pool, username="foo", guild_id=1, channel_id=10)
    assert "언팔로우하지 못했어요" in msg


async def test_app_command_error_handler_always_answers():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from miniyatcho.features.twitter.commands import TwitterCog
    cog = TwitterCog(store=None, pool=None)
    followup = SimpleNamespace(send=AsyncMock())
    itn = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True, send_message=AsyncMock()), followup=followup)
    await cog.cog_app_command_error(itn, Exception("x"))
    followup.send.assert_awaited_once()


from miniyatcho.features.twitter.commands import do_set_message  # noqa: E402


async def test_set_message_and_reset(store, pool):
    await add(store, pool)
    msg = await do_set_message(store, username="@foo", guild_id=1, channel_id=10, message="{author} 떴다\n{url}")
    assert "바꿨어요" in msg
    assert (await store.get_subscription("100", 10)).message == "{author} 떴다\n{url}"
    msg = await do_set_message(store, username="foo", guild_id=1, channel_id=10, message="   ")
    assert "기본 멘트" in msg
    assert (await store.get_subscription("100", 10)).message is None


async def test_set_message_too_long(store, pool):
    await add(store, pool)
    assert "1500" in await do_set_message(store, username="foo", guild_id=1, channel_id=10, message="a" * 1501)
    assert (await store.get_subscription("100", 10)).message is None


async def test_set_message_other_guild_rejected(store, pool):
    await add(store, pool, guild_id=2, channel_id=20)
    assert "추적하고 있지 않아요" in await do_set_message(store, username="foo", guild_id=1, channel_id=20, message="x {url}")
    assert (await store.get_subscription("100", 20)).message is None

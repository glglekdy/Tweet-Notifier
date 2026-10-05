import discord

from miniyatcho.features.twitter.alerts import Alerter
from miniyatcho.features.twitter.poller import Backoff, select_new_tweets, wants
from miniyatcho.features.twitter.store import Subscription
from tests.fakes import FakeBot, FakeChannel, FakeGuild, FakeResponse, FakeRole, FakeTweet, FakeUser

U = FakeUser("100", "foo", "푸")


def tw(i, **kw):
    return FakeTweet(str(i), U, url=f"https://x.com/foo/status/{i}", **kw)


def test_select_new_tweets_filters_and_sorts():
    other = FakeTweet("50", FakeUser("999", "bar"))
    assert [t.id for t in select_new_tweets([tw(12), other, tw(9), tw(11)], "100", 10)] == ["11", "12"]


def test_select_burst_keeps_newest():
    got = select_new_tweets([tw(i) for i in range(1, 9)], "100", 0)
    assert [t.id for t in got] == ["4", "5", "6", "7", "8"]


def test_select_skips_malformed():
    bad = [FakeTweet(None, U), FakeTweet("7", None), FakeTweet("abc", U)]
    assert [t.id for t in select_new_tweets(bad + [tw(8)], "100", 0)] == ["8"]


def test_wants():
    s = Subscription("100", 1, 10, None, retweets=False, quotes=True)
    assert wants(tw(1), s) and wants(tw(1, is_quoted=True), s) and not wants(tw(1, is_retweet=True), s)


def test_backoff():
    b = Backoff(18)
    assert [b.fail(), b.fail(), b.fail(), b.fail(), b.fail(), b.fail()] == [36, 72, 144, 288, 576, 600]
    b.reset()
    assert b.current == 18


async def test_dispatch_sends_and_saves_last_seen(poller_env):
    ch = FakeChannel(10, FakeGuild([FakeRole(7)]))
    env = await poller_env(channels=[ch], subs=[Subscription("100", 1, 10, 7, True, True)],
                           notifications=[tw(11), tw(12, is_retweet=True)])
    assert await env.poller.poll_once() is True
    assert [c for c, _ in ch.sent] == [
        "<@&7> **푸**님이 새 게시물을 올렸어요\nhttps://fxtwitter.com/foo/status/11",
        "<@&7> **푸**님이 리트윗했어요\nhttps://fxtwitter.com/foo/status/12"]
    assert (await env.store.get_target("100")).last_seen_id == 12


async def test_dispatch_respects_retweet_off(poller_env):
    ch = FakeChannel(10)
    env = await poller_env(channels=[ch], subs=[Subscription("100", 1, 10, None, False, True)],
                           notifications=[tw(11, is_retweet=True)])
    await env.poller.poll_once()
    assert ch.sent == [] and (await env.store.get_target("100")).last_seen_id == 11


async def test_dispatch_continues_after_forbidden(poller_env):
    bad = FakeChannel(10, error=discord.Forbidden(FakeResponse(403), "no"))
    good = FakeChannel(11)
    env = await poller_env(channels=[bad, good],
                           subs=[Subscription("100", 1, 10, None, True, True), Subscription("100", 1, 11, None, True, True)],
                           notifications=[tw(11)])
    await env.poller.poll_once()
    assert len(good.sent) == 1 and (await env.store.get_target("100")).last_seen_id == 11


async def test_deleted_role_sends_without_mention(poller_env):
    ch = FakeChannel(10)  # 역할 7 없음
    env = await poller_env(channels=[ch], subs=[Subscription("100", 1, 10, 7, True, True)], notifications=[tw(11)])
    await env.poller.poll_once()
    assert ch.sent[0][0].startswith("**푸**")


async def test_rate_limit_backs_off(poller_env):
    from tweety.exceptions import RateLimitReached
    env = await poller_env(notifications=RateLimitReached(88, "RateLimitExceeded", None))
    assert await env.poller.poll_once() is True
    assert env.poller.backoff.current == 36


async def test_auth_error_stops_and_marks_failed(poller_env):
    from tweety.exceptions import DeniedLogin
    env = await poller_env(notifications=DeniedLogin())
    assert await env.poller.poll_once() is False
    assert not env.pool.states["a"].ok


async def test_other_error_skips_round(poller_env):
    env = await poller_env(notifications=KeyError("x"))
    assert await env.poller.poll_once() is True


async def test_alerter_dedupes():
    ch = FakeChannel(99)
    a = Alerter(FakeBot([ch]), 99)
    await a.raise_("a:auth", "x")
    await a.raise_("a:auth", "x")
    assert len(ch.sent) == 1
    a.clear("a:auth")
    await a.raise_("a:auth", "x")
    assert len(ch.sent) == 2


async def test_cancel_during_swallowing_fetch_stops_loop(poller_env):
    # tweety 의 generator 는 CancelledError 를 삼키고 정상 반환한다. 그래도 루프는 멈춰야 한다.
    import asyncio
    env = await poller_env()
    app = env.pool.states["a"].app
    entered = asyncio.Event()

    swallowed = []

    async def swallowing_fetch():
        entered.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            if swallowed:  # 두 번째 취소부터는 그대로 전파해 테스트 종료 시 루프가 멈추게 한다
                raise
            swallowed.append(1)
            return []
        return []

    app.get_tweet_notifications = swallowing_fetch
    env.poller.backoff = Backoff(0)
    task = asyncio.create_task(env.poller.run())
    await entered.wait()
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=1)
    if task not in done:
        task.cancel()
        await asyncio.wait({task}, timeout=1)
    assert task in done and task.cancelled()


async def test_dispatch_uses_subscription_message(poller_env):
    ch = FakeChannel(10)
    env = await poller_env(channels=[ch], subs=[Subscription("100", 1, 10, None, True, True)], notifications=[tw(11)])
    await env.store.set_message("100", 10, "{author}(@{username}) 새 글!\n{url}")
    await env.poller.poll_once()
    assert ch.sent[0][0] == "푸(@foo) 새 글!\nhttps://fxtwitter.com/foo/status/11"

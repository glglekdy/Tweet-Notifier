from miniyatcho.features.twitter.store import Subscription, Target, snowflake_now

T = Target("100", "foo", "sub1", 5)


def test_snowflake_now():
    assert snowflake_now(1288834974657 + 1000) == 1000 << 22


async def test_add_and_get_target(store):
    await store.add_target(T)
    assert await store.get_target("100") == T
    assert await store.find_target_by_username("FOO") == T


async def test_add_target_existing_keeps_client_and_last_seen(store):
    await store.add_target(T)
    await store.add_target(Target("100", "foo2", "sub2", 999))
    assert await store.get_target("100") == Target("100", "foo2", "sub1", 5)


async def test_upsert_subscription_overwrites(store):
    await store.add_target(T)
    await store.upsert_subscription(Subscription("100", 1, 10, 7, True, True))
    await store.upsert_subscription(Subscription("100", 1, 10, None, False, True))
    assert await store.subscriptions_for("100") == [Subscription("100", 1, 10, None, False, True)]


async def test_delete_target_cascades(store):
    await store.add_target(T)
    await store.upsert_subscription(Subscription("100", 1, 10, None, True, True))
    await store.delete_target("100")
    assert await store.subscriptions_for("100") == []


async def test_count_by_client_and_set_client(store):
    await store.add_target(T)
    await store.add_target(Target("200", "bar", "sub1", 0))
    await store.set_client("200", "sub2")
    assert await store.count_by_client() == {"sub1": 1, "sub2": 1}
    assert [t.user_id for t in await store.targets_for_client("sub2")] == ["200"]


async def test_set_last_seen(store):
    await store.add_target(T)
    await store.set_last_seen("100", 42)
    assert (await store.get_target("100")).last_seen_id == 42


async def test_guild_views(store):
    await store.add_target(T)
    await store.add_target(Target("200", "bar", "sub1", 0))
    await store.upsert_subscription(Subscription("100", 1, 10, None, True, True))
    await store.upsert_subscription(Subscription("200", 1, 11, None, True, True))
    await store.upsert_subscription(Subscription("200", 2, 20, None, True, True))
    assert await store.usernames_in_guild(1) == ["bar", "foo"]
    assert [(t.username, s.channel_id) for t, s in await store.guild_subscriptions(1)] == [("bar", 11), ("foo", 10)]


async def test_set_message_and_readd_keeps_it(store):
    await store.add_target(T)
    await store.upsert_subscription(Subscription("100", 1, 10, None, True, True))
    await store.set_message("100", 10, "{author} 떴다\n{url}")
    await store.upsert_subscription(Subscription("100", 1, 10, 7, False, True))  # /twitter add 다시 해도
    sub = await store.get_subscription("100", 10)
    assert sub.message == "{author} 떴다\n{url}" and sub.role_id == 7
    await store.set_message("100", 10, None)
    assert (await store.get_subscription("100", 10)).message is None


async def test_ensure_schema_migrates_old_table(tmp_path):
    from miniyatcho.db import Database
    from miniyatcho.features.twitter.store import TwitterStore, ensure_schema
    db = Database(tmp_path / "old.db")
    await db.open()
    await db.ensure_schema(
        "CREATE TABLE twitter_target (user_id TEXT PRIMARY KEY, username TEXT NOT NULL, client_name TEXT NOT NULL, last_seen_id INTEGER NOT NULL);"
        "CREATE TABLE twitter_subscription (user_id TEXT NOT NULL, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, role_id INTEGER, retweets INTEGER NOT NULL DEFAULT 1, quotes INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (user_id, channel_id));"
        "INSERT INTO twitter_target VALUES ('100','foo','a',0);"
        "INSERT INTO twitter_subscription (user_id, guild_id, channel_id) VALUES ('100',1,10);"
    )
    await ensure_schema(db)
    await ensure_schema(db)  # 두 번 실행해도 안전
    sub = await TwitterStore(db).get_subscription("100", 10)
    assert sub.message is None
    await db.close()

from pathlib import Path

import pytest

from miniyatcho.config import Config, ConfigError, parse_twitter_tokens

BASE = {"DISCORD_TOKEN": "d", "TWITTER_TOKEN": "a:tok1"}


def test_parse_twitter_tokens_basic():
    assert parse_twitter_tokens("sub1:aaa, sub2:bbb") == (("sub1", "aaa"), ("sub2", "bbb"))


def test_parse_twitter_tokens_trailing_comma_and_spaces():
    assert parse_twitter_tokens(" sub1 : aaa ,") == (("sub1", "aaa"),)


def test_parse_twitter_tokens_duplicate_alias():
    with pytest.raises(ConfigError):
        parse_twitter_tokens("a:1,a:2")


def test_parse_twitter_tokens_missing_colon():
    with pytest.raises(ConfigError):
        parse_twitter_tokens("justtoken")


def test_parse_twitter_tokens_bad_alias():
    with pytest.raises(ConfigError):
        parse_twitter_tokens("부계:aaa")


def test_parse_twitter_tokens_empty():
    with pytest.raises(ConfigError):
        parse_twitter_tokens(" , ")


def test_load_defaults():
    c = Config.load(BASE)
    assert c.discord_token == "d"
    assert c.twitter_tokens == (("a", "tok1"),)
    assert c.guild_id is None and c.alert_channel_id is None
    assert c.check_seconds == 18
    assert c.data_dir == Path("data")
    assert c.db_path == Path("data") / "miniyatcho.db"
    assert c.sessions_dir == Path("data") / "sessions"


def test_load_check_seconds_floor():
    assert Config.load({**BASE, "TWITTER_CHECK_SECONDS": "3"}).check_seconds == 10


def test_load_optional_ids():
    c = Config.load({**BASE, "GUILD_ID": "123", "ALERT_CHANNEL_ID": " 456 "})
    assert (c.guild_id, c.alert_channel_id) == (123, 456)


@pytest.mark.parametrize("key", ["DISCORD_TOKEN", "TWITTER_TOKEN"])
def test_load_missing_required(key):
    env = dict(BASE)
    env[key] = ""
    with pytest.raises(ConfigError):
        Config.load(env)


def test_load_non_numeric_id():
    with pytest.raises(ConfigError):
        Config.load({**BASE, "GUILD_ID": "abc"})


def test_parse_twitter_tokens_error_does_not_leak_token():
    with pytest.raises(ConfigError) as info:
        parse_twitter_tokens("ok:1,abcdef0123456789secret")
    assert "abcdef" not in str(info.value)
    assert "2" in str(info.value)  # 몇 번째 항목인지는 알려준다

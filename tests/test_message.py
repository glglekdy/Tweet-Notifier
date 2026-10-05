from miniyatcho.features.twitter.message import format_notification, to_fx_url, tweet_kind
from tests.fakes import FakeTweet, FakeUser

U = FakeUser("1", "foo")


def test_tweet_kind():
    assert tweet_kind(FakeTweet("1", U)) == "tweet"
    assert tweet_kind(FakeTweet("1", U, is_retweet=True)) == "retweet"
    assert tweet_kind(FakeTweet("1", U, is_quoted=True)) == "quote"
    assert tweet_kind(FakeTweet("1", U, is_retweet=True, is_quoted=True)) == "retweet"


def test_to_fx_url():
    assert to_fx_url("https://twitter.com/foo/status/1") == "https://fxtwitter.com/foo/status/1"
    assert to_fx_url("https://x.com/foo/status/1") == "https://fxtwitter.com/foo/status/1"
    assert to_fx_url("https://www.x.com/foo/status/1") == "https://fxtwitter.com/foo/status/1"
    assert to_fx_url("https://example.com/a") == "https://example.com/a"


def test_format_with_role():
    assert format_notification(author_name="ﾅﾁｮﾈｺ", kind="tweet",
                               url="https://x.com/n/status/9", role_mention="<@&5>") == \
        "<@&5> **ﾅﾁｮﾈｺ**님이 새 게시물을 올렸어요\nhttps://fxtwitter.com/n/status/9"


def test_format_without_role_and_escapes_name():
    assert format_notification(author_name="a*b_c", kind="quote",
                               url="https://x.com/n/status/9", role_mention=None) == \
        "**a\*b\_c**님이 인용했어요\nhttps://fxtwitter.com/n/status/9"


def test_tweet_kind_rt_prefix_text_is_not_retweet():
    # tweety 는 본문이 "RT" 로 시작하면 is_retweet=True 로 본다. 'RT 추첨' 같은 일반 글은 게시물이어야 한다.
    t = FakeTweet("1", U, is_retweet=True, _original_tweet={"full_text": "RT 추첨 이벤트 합니다"})
    assert tweet_kind(t) == "tweet"


def test_tweet_kind_real_retweet_from_raw():
    t = FakeTweet("1", U, is_retweet=True, _original_tweet={"full_text": "RT @bar: hi", "retweeted_status_id_str": "5"})
    assert tweet_kind(t) == "retweet"
    t2 = FakeTweet("1", U, is_retweet=False, _original_tweet={"full_text": "RT @bar: hi"})
    assert tweet_kind(t2) == "retweet"


from miniyatcho.features.twitter.message import DEFAULT_TEMPLATE, render_template  # noqa: E402

V = dict(author_name="푸", username="foo", kind="retweet", url="https://x.com/foo/status/9")


def test_default_template_matches_old_format():
    assert render_template(None, role_mention="<@&5>", **V) == \
        "<@&5> **푸**님이 리트윗했어요\nhttps://fxtwitter.com/foo/status/9"
    assert render_template(DEFAULT_TEMPLATE, role_mention=None, **V) == \
        "**푸**님이 리트윗했어요\nhttps://fxtwitter.com/foo/status/9"


def test_custom_template_all_placeholders():
    t = "📢 {mention}\n{author}(@{username}) {action}!\n{url}"
    assert render_template(t, role_mention="<@&5>", **V) == \
        "📢 <@&5>\n푸(@foo) 리트윗했어요!\nhttps://fxtwitter.com/foo/status/9"


def test_template_without_url_appends_link():
    assert render_template("{author} 떴다", role_mention=None, **V) == "푸 떴다\nhttps://fxtwitter.com/foo/status/9"


def test_unknown_placeholder_and_braces_stay_literal():
    assert render_template("{foo} {author} {} {url}", role_mention=None, **V) == \
        "{foo} 푸 {} https://fxtwitter.com/foo/status/9"


def test_author_name_is_not_resubstituted():
    v = dict(V, author_name="{url}")
    assert render_template("{author} {url}", role_mention=None, **v) == \
        "{url} https://fxtwitter.com/foo/status/9"

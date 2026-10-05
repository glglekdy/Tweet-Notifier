"""트위터 알림 메시지 문구."""

from __future__ import annotations

import re
from typing import Literal

from discord.utils import escape_markdown

TweetKind = Literal["tweet", "retweet", "quote"]

ACTION_TEXT: dict[TweetKind, str] = {
    "tweet": "새 게시물을 올렸어요",
    "retweet": "리트윗했어요",
    "quote": "인용했어요",
}

DEFAULT_TEMPLATE = "{mention} **{author}**님이 {action}\n{url}"
MAX_TEMPLATE_LENGTH = 1500
PLACEHOLDERS = ("mention", "author", "username", "action", "url")
_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")

# 디스코드는 x.com 링크 미리보기가 빈약하다. fxtwitter 는 본문·이미지·영상을 펼쳐 준다.
_TWITTER_URL_RE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/")


def _is_retweet(tweet) -> bool:
    # tweety 의 is_retweet 은 본문이 "RT" 로 시작하기만 해도 참이라, 'RT 추첨' 같은 일반 글을 리트윗으로 본다.
    # 원본 데이터가 있으면 리트윗 원문 ID 나 "RT @" 접두로 판정한다.
    raw = getattr(tweet, "_original_tweet", None)
    if isinstance(raw, dict):
        if raw.get("retweeted_status_id_str") or raw.get("retweeted_status_result"):
            return True
        return str(raw.get("full_text", "")).startswith("RT @")
    return bool(tweet.is_retweet)


def tweet_kind(tweet) -> TweetKind:
    if _is_retweet(tweet):
        return "retweet"
    if tweet.is_quoted:
        return "quote"
    return "tweet"


def to_fx_url(url: str) -> str:
    return _TWITTER_URL_RE.sub("https://fxtwitter.com/", url)


def render_template(
    template: str | None,
    *,
    author_name: str,
    username: str,
    kind: TweetKind,
    url: str,
    role_mention: str | None,
) -> str:
    """멘트의 자리표시를 채운다. 모르는 {…} 는 글자 그대로 두고, {url} 이 없으면 링크를 끝에 붙인다."""
    template = template or DEFAULT_TEMPLATE
    link = to_fx_url(url)
    if not role_mention:
        # 기본 멘트처럼 "{mention} " 로 시작할 때 앞에 빈칸이 남지 않게 한다.
        template = template.replace("{mention} ", "")
    values = {
        "mention": role_mention or "",
        "author": escape_markdown(author_name),
        "username": username,
        "action": ACTION_TEXT[kind],
        "url": link,
    }
    # 한 번에 치환해야 이름 속의 "{url}" 같은 글자가 다시 치환되지 않는다.
    text = _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)
    if "{url}" not in template:
        text = f"{text}\n{link}"
    return text


def format_notification(*, author_name: str, kind: TweetKind, url: str, role_mention: str | None) -> str:
    return render_template(None, author_name=author_name, username="", kind=kind, url=url, role_mention=role_mention)

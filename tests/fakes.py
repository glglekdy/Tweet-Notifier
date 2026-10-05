"""테스트 대역. tweety 와 discord 객체 중 이 봇이 실제로 쓰는 속성만 흉내 낸다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeUser:
    id: str
    username: str
    name: str = "표시이름"


@dataclass
class FakeTweet:
    id: str | None
    author: FakeUser | None
    is_retweet: bool = False
    is_quoted: bool = False
    url: str = "https://twitter.com/foo/status/1"
    _original_tweet: dict | None = None  # tweety 의 원본 legacy 딕셔너리


class FakeSession:
    def __init__(self, saved_token=None):
        self.saved_token = saved_token

    def cookies_dict(self):
        return {"auth_token": self.saved_token} if self.saved_token else {}


class FakeApp:
    """tweety Twitter 대역. connect/load_auth_token 결과와 호출 기록을 조절한다."""

    def __init__(self, path, *, saved_token=None, connect_ok=True, login_errors=0, users=None, notifications=None):
        self.path, self.session = path, FakeSession(saved_token)
        self.connect_ok, self.login_errors = connect_ok, login_errors
        self.users = users or {}  # username(소문자) -> FakeUser
        self.notifications = notifications if notifications is not None else []  # list 또는 Exception
        self.calls: list[tuple] = []

    async def connect(self):
        self.calls.append(("connect",))
        return object() if self.connect_ok else None

    async def load_auth_token(self, token):
        self.calls.append(("load", token))
        if self.login_errors:
            self.login_errors -= 1
            from tweety.exceptions import DeniedLogin
            raise DeniedLogin()

    async def get_user_info(self, username):
        from tweety.exceptions import UserNotFound
        try:
            return self.users[username.lower()]
        except KeyError:
            raise UserNotFound() from None

    async def get_tweet_notifications(self):
        if isinstance(self.notifications, Exception):
            raise self.notifications
        return self.notifications

    async def follow_user(self, uid):
        self.calls.append(("follow", uid))

    async def enable_user_notification(self, uid):
        self.calls.append(("notify_on", uid))
        return True

    async def disable_user_notification(self, uid):
        self.calls.append(("notify_off", uid))
        return True

    async def unfollow_user(self, uid):
        self.calls.append(("unfollow", uid))


class FakeResponse:
    def __init__(self, status):
        self.status, self.reason = status, "x"


class FakeRole:
    def __init__(self, id):
        self.id, self.mention = id, f"<@&{id}>"


class FakeGuild:
    def __init__(self, roles=()):
        self._roles = {r.id: r for r in roles}

    def get_role(self, id):
        return self._roles.get(id)


class FakeChannel:
    def __init__(self, id, guild=None, error=None):
        self.id, self.guild, self.error, self.sent = id, guild or FakeGuild(), error, []

    async def send(self, content, allowed_mentions=None):
        if self.error:
            raise self.error
        self.sent.append((content, allowed_mentions))


class FakeBot:
    def __init__(self, channels=()):
        self.channels = {c.id: c for c in channels}

    def get_channel(self, id):
        return self.channels.get(id)

    async def fetch_channel(self, id):
        import discord
        raise discord.NotFound(FakeResponse(404), "unknown channel")

    async def wait_until_ready(self):
        pass

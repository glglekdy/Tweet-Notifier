"""부계정마다 알림 탭을 주기적으로 조회해 새 트윗을 디스코드로 보낸다.

부계정이 추적 대상을 팔로우하고 알림(종)을 켜 두었으므로, 대상이 몇 개든 알림 탭 한 번만
조회하면 된다. 새 트윗 판정은 트윗 ID(시간순으로 커지는 스노플레이크) > last_seen_id.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
import discord

from .accounts import AUTH_ERRORS, ClientPool, RateLimitReached
from .alerts import Alerter
from .message import render_template, tweet_kind
from .store import Subscription, Target, TwitterStore

log = logging.getLogger("miniyatcho.twitter")

MAX_BURST = 5          # 한 대상에서 한 번에 보낼 최대 트윗 수 (오래 꺼졌다 켜졌을 때 폭주 방지)
MAX_BACKOFF = 600      # 조회 제한 시 최대 간격(초)
RATE_ALERT_AFTER = 600 # 조회 제한이 이만큼 이어지면 관리자 알림(초)
SEND_RETRIES = 3

TRANSIENT_SEND_ERRORS = (discord.DiscordServerError, aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError)


def _tweet_id(tweet) -> int | None:
    try:
        return int(tweet.id)
    except (TypeError, ValueError):
        return None


def select_new_tweets(tweets: list, user_id: str, last_seen_id: int, limit: int = MAX_BURST) -> list:
    picked = []
    for tweet in tweets:
        author = getattr(tweet, "author", None)
        tid = _tweet_id(tweet)
        if author is None or tid is None:
            continue  # 삭제·비공개·광고 등 형식이 깨진 항목
        if str(getattr(author, "id", "")) == user_id and tid > last_seen_id:
            picked.append((tid, tweet))
    picked.sort(key=lambda pair: pair[0])
    return [tweet for _, tweet in picked[-limit:]]


def wants(tweet, sub: Subscription) -> bool:
    kind = tweet_kind(tweet)
    if kind == "retweet":
        return sub.retweets
    if kind == "quote":
        return sub.quotes
    return True


class Backoff:
    def __init__(self, base: int, cap: int = MAX_BACKOFF) -> None:
        self.base, self.cap = base, cap
        self.current = base

    def fail(self) -> int:
        self.current = min(self.current * 2, self.cap)
        return self.current

    def reset(self) -> None:
        self.current = self.base


class ClientPoller:
    def __init__(
        self,
        bot: discord.Client,
        name: str,
        pool: ClientPool,
        store: TwitterStore,
        alerter: Alerter,
        base_interval: int,
        send_retry_delay: float = 2.0,
    ) -> None:
        self.bot, self.name, self.pool, self.store, self.alerter = bot, name, pool, store, alerter
        self.backoff = Backoff(base_interval)
        self.send_retry_delay = send_retry_delay
        self._rate_limited_since: float | None = None
        self._retry_tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        log.info("봇 계정 '%s': 조회 루프 시작 (%d초 간격)", self.name, self.backoff.base)
        while True:
            await asyncio.sleep(self.backoff.current)
            try:
                if not await self.poll_once():
                    log.error("봇 계정 '%s': 조회 루프를 멈춥니다", self.name)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                # 루프가 죽으면 그 부계정의 알림이 전부 끊기므로, 예상 못 한 오류도 로그만 남기고 계속 돈다.
                log.exception("봇 계정 '%s': 조회 중 예상치 못한 오류", self.name)

    async def poll_once(self) -> bool:
        targets = await self.store.targets_for_client(self.name)
        if not targets:
            return True

        app = self.pool.get(self.name).app
        try:
            tweets = await app.get_tweet_notifications()
        except RateLimitReached:
            await self._on_rate_limited()
            return True
        except AUTH_ERRORS as exc:
            reason = f"인증 오류: {type(exc).__name__}"
            self.pool.mark_failed(self.name, reason)
            await self.alerter.raise_(
                f"{self.name}:auth",
                f"봇 계정 '{self.name}' {reason}. .env 의 토큰을 바꾸고 재시작해 주세요.",
            )
            return False
        except Exception as exc:
            log.warning("봇 계정 '%s': 이번 조회를 건너뜁니다 (%r)", self.name, exc)
            return True
        finally:
            # tweety 의 페이지 생성기는 CancelledError 를 삼키고 정상 반환한다.
            # 그대로 두면 종료 시 cancel() 이 먹히지 않아 봇이 꺼지지 않는다.
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError

        self.backoff.reset()
        self._rate_limited_since = None
        self.alerter.clear(f"{self.name}:ratelimit")
        self.pool.mark_success(self.name)

        for target in targets:
            new = select_new_tweets(tweets, target.user_id, target.last_seen_id)
            if new:
                await self.dispatch(target, new)
        return True

    async def _on_rate_limited(self) -> None:
        wait = self.backoff.fail()
        now = time.monotonic()
        if self._rate_limited_since is None:
            self._rate_limited_since = now
        log.warning("봇 계정 '%s': 트위터 조회 제한, %d초 뒤 다시 시도", self.name, wait)
        if now - self._rate_limited_since >= RATE_ALERT_AFTER:
            await self.alerter.raise_(
                f"{self.name}:ratelimit",
                f"봇 계정 '{self.name}' 이(가) 10분 넘게 트위터 조회 제한에 걸려 있어요.",
            )

    async def dispatch(self, target: Target, tweets: list) -> None:
        subs = await self.store.subscriptions_for(target.user_id)
        for tweet in tweets:
            log.info("@%s 새 트윗 %s", target.username, tweet.id)
            for sub in subs:
                if wants(tweet, sub):
                    await self._send(sub, tweet)
            # 보낸 뒤에 저장한다: 도중에 죽으면 재시작 후 한 번 더 갈 수는 있어도 빠지지는 않는다.
            await self.store.set_last_seen(target.user_id, int(tweet.id))

    async def _send(self, sub: Subscription, tweet) -> None:
        try:
            channel = self.bot.get_channel(sub.channel_id) or await self.bot.fetch_channel(sub.channel_id)
        except (discord.NotFound, discord.Forbidden) as exc:
            log.warning("채널 %s 을(를) 찾을 수 없거나 권한이 없어 건너뜁니다 (%r)", sub.channel_id, exc)
            return

        role = channel.guild.get_role(sub.role_id) if sub.role_id else None
        if role is not None:
            mention = role.mention
            allowed = discord.AllowedMentions(roles=[role], users=False, everyone=False)
        else:
            mention, allowed = None, discord.AllowedMentions.none()

        content = render_template(
            sub.message,
            author_name=tweet.author.name,
            username=tweet.author.username,
            kind=tweet_kind(tweet),
            url=tweet.url,
            role_mention=mention,
        )
        try:
            await channel.send(content, allowed_mentions=allowed)
        except (discord.NotFound, discord.Forbidden) as exc:
            log.warning("채널 %s 에 보낼 수 없어 건너뜁니다 (%r)", sub.channel_id, exc)
        except TRANSIENT_SEND_ERRORS as exc:
            log.warning("채널 %s 발송 일시 오류, 백그라운드에서 재시도합니다 (%r)", sub.channel_id, exc)
            task = asyncio.create_task(self._retry_send(channel, content, allowed))
            self._retry_tasks.add(task)
            task.add_done_callback(self._retry_tasks.discard)
        except Exception:
            log.exception("채널 %s 발송 중 예상치 못한 오류", sub.channel_id)

    async def _retry_send(self, channel, content: str, allowed: discord.AllowedMentions) -> None:
        delay = self.send_retry_delay
        for attempt in range(1, SEND_RETRIES + 1):
            await asyncio.sleep(delay)
            try:
                await channel.send(content, allowed_mentions=allowed)
                log.info("채널 %s 재시도 %d회 만에 발송 성공", channel.id, attempt)
                return
            except TRANSIENT_SEND_ERRORS as exc:
                log.warning("채널 %s 재시도 %d/%d 실패 (%r)", channel.id, attempt, SEND_RETRIES, exc)
                delay *= 2
            except Exception as exc:
                log.error("채널 %s 재시도 중 복구할 수 없는 오류 (%r)", channel.id, exc)
                return
        log.error("채널 %s: %d회 재시도 후에도 보내지 못했습니다", channel.id, SEND_RETRIES)

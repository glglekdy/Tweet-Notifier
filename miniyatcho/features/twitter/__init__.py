"""트위터 알림 기능.

봇용 트위터 부계정으로 추적 대상을 팔로우·알림 설정해 두고, 부계정마다 알림 탭을 주기적으로
조회해 새 게시물·리트윗·인용을 지정 채널에 역할 멘션과 함께 보낸다.

추적 방식은 Yuuzi261/Tweetcord (MIT) 를 참고했다. THIRD_PARTY_NOTICES.md 참고.
"""

from __future__ import annotations

import asyncio
import logging

from .accounts import ClientPool
from .alerts import Alerter
from .commands import TwitterCog
from .poller import ClientPoller
from .store import TwitterStore, ensure_schema

log = logging.getLogger("miniyatcho.twitter")

TEARDOWN_TIMEOUT = 5

# 이 기능이 띄운 백그라운드 작업. teardown 에서 정리한다.
_tasks: set[asyncio.Task] = set()


def _spawn(coro, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _start(bot, store: TwitterStore, pool: ClientPool, alerter: Alerter) -> None:
    # 디스코드 로그인과 동시에 진행되도록 setup 을 막지 않고 백그라운드에서 돈다.
    try:
        await _start_inner(bot, store, pool, alerter)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # 여기서 죽으면 어떤 부계정도 조회를 시작하지 못하므로 반드시 알린다.
        log.exception("트위터 알림 시작 중 오류")
        await alerter.raise_("twitter:start", f"트위터 알림을 시작하지 못했어요: {type(exc).__name__}. 로그를 확인해 주세요.")


async def _start_inner(bot, store: TwitterStore, pool: ClientPool, alerter: Alerter) -> None:
    await pool.login_all()

    for name, state in pool.states.items():
        if not state.ok:
            await alerter.raise_(f"{name}:auth", f"봇 계정 '{name}' {state.error}. .env 의 토큰을 확인해 주세요.")

    for target in await store.all_targets():
        if target.client_name not in pool.states:
            log.warning(
                "@%s 의 담당 봇 계정 '%s' 가 .env 에 없습니다. /twitter add 의 '봇계정' 으로 옮겨 주세요.",
                target.username, target.client_name,
            )

    for name in pool.ok_names():
        poller = ClientPoller(bot, name, pool, store, alerter, bot.config.check_seconds)
        _spawn(poller.run(), f"twitter-poller-{name}")


async def setup(bot) -> None:
    await ensure_schema(bot.db)
    store = TwitterStore(bot.db)
    pool = ClientPool(bot.config.twitter_tokens, bot.config.sessions_dir)
    alerter = Alerter(bot, bot.config.alert_channel_id)
    await bot.add_cog(TwitterCog(store, pool))
    _spawn(_start(bot, store, pool, alerter), "twitter-start")


async def teardown(bot) -> None:
    for task in list(_tasks):
        task.cancel()
    if _tasks:
        # 취소를 무시하는 작업이 있어도 종료가 멈추지 않도록 기다리는 시간을 제한한다.
        _, pending = await asyncio.wait(set(_tasks), timeout=TEARDOWN_TIMEOUT)
        if pending:
            log.warning("트위터 작업 %d개가 %d초 안에 멈추지 않았습니다", len(pending), TEARDOWN_TIMEOUT)

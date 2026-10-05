"""봇용 트위터 부계정 관리: 로그인·세션 재사용, 상태, 담당 선택, 팔로우."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tweety import Twitter
from tweety.exceptions import (  # noqa: F401  (RateLimitReached, UserNotFound, UserProtected 는 다른 모듈이 여기서 가져감)
    AuthenticationRequired,
    DeniedLogin,
    InvalidCredentials,
    LockedAccount,
    RateLimitReached,
    SuspendedAccount,
    UserNotFound,
    UserProtected,
)

log = logging.getLogger("miniyatcho.twitter")

# 이 예외들은 재시도해도 풀리지 않는다. 토큰을 바꾸고 재시작해야 한다.
AUTH_ERRORS: tuple[type[Exception], ...] = (
    DeniedLogin, InvalidCredentials, AuthenticationRequired, LockedAccount, SuspendedAccount,
)

LOGIN_ATTEMPTS = 2


@dataclass
class ClientState:
    name: str
    app: Twitter | None = None
    error: str | None = None
    last_success: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.app is not None and self.error is None


class ClientPool:
    def __init__(
        self,
        tokens: tuple[tuple[str, str], ...],
        sessions_dir: Path,
        factory: Callable[[str], Twitter] = Twitter,
        retry_delay: float = 5.0,
    ) -> None:
        self._tokens = dict(tokens)
        self.sessions_dir = Path(sessions_dir)
        self._factory = factory
        self._retry_delay = retry_delay
        self.states: dict[str, ClientState] = {name: ClientState(name) for name, _ in tokens}

    async def login_all(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        for name, token in self._tokens.items():
            await self._login(name, token)

    def _create(self, name: str) -> Twitter | None:
        """세션 파일을 읽어 클라이언트를 만든다. 파일이 깨졌으면 지우고 한 번 더 만든다."""
        session_path = self.sessions_dir / name
        try:
            return self._factory(str(session_path))
        except Exception as exc:
            # tweety 는 세션 파일을 원자적으로 쓰지 않아, 쓰는 도중 프로세스가 죽으면 파일이 깨진다.
            log.warning("봇 계정 '%s': 세션 파일을 읽지 못해 지우고 다시 만듭니다 (%r)", name, exc)
        session_path.with_name(f"{name}.tw_session").unlink(missing_ok=True)
        try:
            return self._factory(str(session_path))
        except Exception as exc:
            log.error("봇 계정 '%s': 클라이언트를 만들지 못했습니다 (%r)", name, exc)
            self.mark_failed(name, f"초기화 실패: {type(exc).__name__}")
            return None

    async def _login(self, name: str, token: str) -> None:
        app = self._create(name)
        if app is None:
            return

        # 매번 새로 로그인하면 트위터가 의심하기 쉬우므로, 저장된 세션의 토큰이 같으면 그대로 쓴다.
        try:
            saved = app.session.cookies_dict().get("auth_token")
            if saved and saved == token and await app.connect():
                self._set_ok(name, app)
                log.info("봇 계정 '%s': 저장된 세션으로 접속", name)
                return
            if saved and saved != token:
                log.info("봇 계정 '%s': .env 토큰이 바뀌어 새로 로그인합니다", name)
        except Exception as exc:
            log.warning("봇 계정 '%s': 저장된 세션을 쓰지 못했습니다 (%s)", name, exc)

        last_exc: Exception | None = None
        for attempt in range(1, LOGIN_ATTEMPTS + 1):
            try:
                await app.load_auth_token(token)
                self._set_ok(name, app)
                log.info("봇 계정 '%s': 로그인 성공", name)
                return
            except Exception as exc:
                last_exc = exc
                log.error("봇 계정 '%s': 로그인 실패 (%d/%d): %r", name, attempt, LOGIN_ATTEMPTS, exc)
                if attempt < LOGIN_ATTEMPTS:
                    await asyncio.sleep(self._retry_delay)
        self.mark_failed(name, f"로그인 실패: {type(last_exc).__name__}")

    def _set_ok(self, name: str, app: Twitter) -> None:
        state = self.states[name]
        state.app, state.error = app, None

    def ok_names(self) -> list[str]:
        return [name for name, state in self.states.items() if state.ok]

    def get(self, name: str) -> ClientState | None:
        return self.states.get(name)

    def mark_failed(self, name: str, reason: str) -> None:
        self.states[name].error = reason

    def mark_success(self, name: str) -> None:
        self.states[name].last_success = datetime.now(timezone.utc)


def pick_client(ok_names: list[str], counts: dict[str, int]) -> str | None:
    """담당 계정이 가장 적은 부계정. 동률이면 .env 에 먼저 적힌 것."""
    if not ok_names:
        return None
    return min(ok_names, key=lambda name: counts.get(name, 0))


async def watch(app: Twitter, user_id: str) -> None:
    await app.follow_user(user_id)
    await app.enable_user_notification(user_id)


async def unwatch(app: Twitter, user_id: str) -> None:
    await app.disable_user_notification(user_id)
    await app.unfollow_user(user_id)

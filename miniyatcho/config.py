"""환경변수(.env) 를 읽어 불변 설정 객체로 만든다.

Dishost 는 패널의 환경변수 탭에 넣은 값도 os.environ 으로 들어오므로, .env 파일이
없어도 동일하게 동작한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_CHECK_SECONDS = 18
MIN_CHECK_SECONDS = 10


class ConfigError(Exception):
    """설정값이 없거나 형식이 틀렸을 때. 메시지는 사용자에게 그대로 보여준다."""


def parse_twitter_tokens(raw: str) -> tuple[tuple[str, str], ...]:
    """`별명:auth_token,별명:auth_token` 을 (별명, 토큰) 튜플로 바꾼다. .env 순서 유지."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for position, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if not item:
            continue  # 끝의 쉼표 등
        if ":" not in item:
            # 항목 내용은 대개 토큰 그 자체라 로그에 남기지 않는다.
            raise ConfigError(f"TWITTER_TOKEN 의 {position}번째 항목에 '별명:토큰' 형식의 ':' 가 없습니다.")
        alias, token = (part.strip() for part in item.split(":", 1))
        if not alias or not token:
            raise ConfigError("TWITTER_TOKEN 에 별명이나 토큰이 비어 있는 항목이 있습니다.")
        if not ALIAS_RE.match(alias):
            raise ConfigError(f"TWITTER_TOKEN 별명 '{alias}' 는 영문·숫자·_·- 만 쓸 수 있습니다.")
        if alias in seen:
            raise ConfigError(f"TWITTER_TOKEN 별명 '{alias}' 가 두 번 이상 나옵니다.")
        seen.add(alias)
        result.append((alias, token))
    if not result:
        raise ConfigError("TWITTER_TOKEN 이 비어 있습니다. '별명:auth_token' 을 하나 이상 넣어주세요.")
    return tuple(result)


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    value = (env.get(key) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{key} 는 숫자여야 합니다: '{value}'") from None


@dataclass(frozen=True)
class Config:
    discord_token: str
    twitter_tokens: tuple[tuple[str, str], ...]
    guild_id: int | None
    alert_channel_id: int | None
    check_seconds: int
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "miniyatcho.db"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "Config":
        if env is None:
            load_dotenv()
            env = os.environ

        discord_token = (env.get("DISCORD_TOKEN") or "").strip()
        if not discord_token:
            raise ConfigError("DISCORD_TOKEN 이 비어 있습니다.")

        raw_tokens = (env.get("TWITTER_TOKEN") or "").strip()
        if not raw_tokens:
            raise ConfigError("TWITTER_TOKEN 이 비어 있습니다. '별명:auth_token' 을 하나 이상 넣어주세요.")

        check_seconds = _optional_int(env, "TWITTER_CHECK_SECONDS")
        if check_seconds is None:
            check_seconds = DEFAULT_CHECK_SECONDS

        return cls(
            discord_token=discord_token,
            twitter_tokens=parse_twitter_tokens(raw_tokens),
            guild_id=_optional_int(env, "GUILD_ID"),
            alert_channel_id=_optional_int(env, "ALERT_CHANNEL_ID"),
            check_seconds=max(check_seconds, MIN_CHECK_SECONDS),
            data_dir=Path((env.get("DATA_DIR") or "").strip() or "data"),
        )

"""/twitter 명령어.

명령 처리 로직(do_add, do_remove)은 디스코드 객체 없이 테스트할 수 있게 함수로 빼고,
Cog 는 인자를 풀어 넘기고 응답만 보내는 얇은 껍데기로 둔다.
"""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from .accounts import ClientPool, UserNotFound, UserProtected, pick_client, unwatch, watch
from .message import DEFAULT_TEMPLATE, MAX_TEMPLATE_LENGTH, render_template
from .store import Subscription, Target, TwitterStore, snowflake_now

log = logging.getLogger("miniyatcho.twitter")

_URL_RE = re.compile(r"^(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/([^/?#]+)", re.IGNORECASE)
_USERNAME_RE = re.compile(r"^[a-z0-9_]{1,15}$")
EMBED_LIMIT = 4096


def normalize_username(raw: str) -> str | None:
    """`@Foo`, `foo`, `https://x.com/Foo/status/1` 등을 `foo` 로. 형식이 틀리면 None."""
    text = raw.strip()
    match = _URL_RE.match(text)
    if match:
        text = match.group(1)
    text = text.removeprefix("@").lower()
    return text if _USERNAME_RE.match(text) else None


async def do_add(
    store: TwitterStore,
    pool: ClientPool,
    *,
    username: str,
    guild_id: int,
    channel_id: int,
    role_id: int | None,
    retweets: bool,
    quotes: bool,
    client: str | None,
) -> str:
    name = normalize_username(username)
    if name is None:
        return "올바른 트위터 아이디가 아니에요."

    ok = pool.ok_names()
    if not ok:
        return "로그인된 봇 계정이 없어요. /twitter accounts 로 상태를 확인해 주세요."
    if client is not None and client not in ok:
        return f"'{client}' 봇 계정은 지금 쓸 수 없어요."

    try:
        user = await pool.get(client or ok[0]).app.get_user_info(name)
    except (UserNotFound, UserProtected):
        user = None
    except Exception as exc:
        log.warning("@%s 계정 정보 조회 실패: %r", name, exc)
        return f"트위터에서 계정 정보를 가져오지 못했어요: {type(exc).__name__}. 잠시 뒤 다시 시도해 주세요."
    # tweety 는 없는 계정에 예외 대신 None 을 돌려준다. 비공개·정지 계정은 UserProtected.
    if user is None or getattr(user, "id", None) is None:
        return f"@{name} 계정을 찾을 수 없어요. (없거나 비공개·정지된 계정)"
    user_id = str(user.id)
    username_lower = str(user.username).lower()

    target = await store.get_target(user_id)
    if client is not None:
        owner = client
    elif target is not None:
        owner = target.client_name
    else:
        owner = pick_client(ok, await store.count_by_client())

    note = ""
    if target is None or target.client_name != owner:
        try:
            await watch(pool.get(owner).app, user_id)
        except Exception as exc:
            log.warning("봇 계정 '%s' 가 @%s 팔로우에 실패: %r", owner, name, exc)
            return f"팔로우에 실패했어요: {type(exc).__name__}"

    if target is None:
        await store.add_target(Target(user_id, username_lower, owner, snowflake_now()))
    else:
        if target.client_name != owner:
            old = target.client_name
            await store.set_client(user_id, owner)
            old_state = pool.get(old)
            unwatched = False
            if old_state is not None and old_state.ok:
                try:
                    await unwatch(old_state.app, user_id)
                    unwatched = True
                except Exception as exc:
                    log.warning("봇 계정 '%s' 에서 @%s 언팔로우 실패: %r", old, name, exc)
            if not unwatched:
                note = f"\n(이전 봇 계정 '{old}'에서 언팔로우하지 못했어요.)"
        await store.add_target(Target(user_id, username_lower, owner, target.last_seen_id))

    owner_state = pool.get(owner)
    if owner_state is None or not owner_state.ok:
        note += (
            f"\n⚠️ 담당 봇 계정 '{owner}' 이(가) 지금 동작하지 않아 알림이 오지 않아요. "
            "/twitter add 의 '봇계정' 으로 다른 계정을 지정해 주세요."
        )

    await store.upsert_subscription(Subscription(user_id, guild_id, channel_id, role_id, retweets, quotes))
    return f"@{username_lower} 추적을 시작했어요 → <#{channel_id}> (담당: {owner}){note}"


async def do_remove(store: TwitterStore, pool: ClientPool, *, username: str, guild_id: int, channel_id: int) -> str:
    name = normalize_username(username)
    if name is None:
        return "올바른 트위터 아이디가 아니에요."

    not_tracking = f"이 채널에서 @{name} 를 추적하고 있지 않아요."
    target = await store.find_target_by_username(name)
    if target is None:
        return not_tracking
    sub = await store.get_subscription(target.user_id, channel_id)
    if sub is None or sub.guild_id != guild_id:
        return not_tracking

    await store.delete_subscription(target.user_id, channel_id)
    note = ""
    if not await store.subscriptions_for(target.user_id):
        state = pool.get(target.client_name)
        unwatched = False
        if state is not None and state.ok:
            try:
                await unwatch(state.app, target.user_id)
                unwatched = True
            except Exception as exc:
                log.warning("봇 계정 '%s' 에서 @%s 언팔로우 실패: %r", target.client_name, name, exc)
        if not unwatched:
            note = f"\n(봇 계정 '{target.client_name}'에서 언팔로우하지 못했어요. 필요하면 직접 언팔로우해 주세요.)"
        await store.delete_target(target.user_id)
    return f"@{name} 추적을 중지했어요 (<#{channel_id}>).{note}"


async def _find_subscription(
    store: TwitterStore, name: str, guild_id: int, channel_id: int,
) -> tuple[Target, Subscription] | None:
    target = await store.find_target_by_username(name)
    if target is None:
        return None
    sub = await store.get_subscription(target.user_id, channel_id)
    if sub is None or sub.guild_id != guild_id:
        return None
    return target, sub


def preview_message(template: str | None, username: str, role_mention: str | None) -> str:
    return render_template(
        template, author_name="표시이름", username=username, kind="tweet",
        url=f"https://x.com/{username}/status/1234567890", role_mention=role_mention,
    )


async def do_set_message(store: TwitterStore, *, username: str, guild_id: int, channel_id: int, message: str) -> str:
    """구독의 맞춤 멘트를 바꾼다. 비어 있으면 기본 멘트로 되돌린다."""
    name = normalize_username(username)
    if name is None:
        return "올바른 트위터 아이디가 아니에요."
    found = await _find_subscription(store, name, guild_id, channel_id)
    if found is None:
        return f"이 채널에서 @{name} 를 추적하고 있지 않아요."
    target, sub = found

    message = message.strip()
    if len(message) > MAX_TEMPLATE_LENGTH:
        return f"멘트는 {MAX_TEMPLATE_LENGTH}자까지 쓸 수 있어요. (지금 {len(message)}자)"
    role = f"<@&{sub.role_id}>" if sub.role_id else None
    if not message:
        await store.set_message(target.user_id, channel_id, None)
        return f"@{name} (<#{channel_id}>) 멘트를 기본 멘트로 되돌렸어요.\n\n미리보기:\n{preview_message(None, name, role)}"
    await store.set_message(target.user_id, channel_id, message)
    return f"@{name} (<#{channel_id}>) 멘트를 바꿨어요.\n\n미리보기:\n{preview_message(message, name, role)}"


class MessageModal(discord.ui.Modal, title="알림 멘트 바꾸기"):
    def __init__(self, store: TwitterStore, username: str, channel_id: int, current: str | None) -> None:
        super().__init__()
        self.store, self.username, self.channel_id = store, username, channel_id
        self.template = discord.ui.TextInput(
            label="멘트 (비우면 기본 멘트)",
            style=discord.TextStyle.paragraph,
            default=current or DEFAULT_TEMPLATE,
            placeholder="{mention} {author} {username} {action} {url}",
            required=False,
            max_length=MAX_TEMPLATE_LENGTH,
        )
        self.add_item(self.template)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await do_set_message(
            self.store, username=self.username, guild_id=interaction.guild_id,
            channel_id=self.channel_id, message=self.template.value or "",
        )
        await interaction.response.send_message(
            result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("멘트 저장 중 오류", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("멘트를 저장하다 오류가 났어요. 잠시 뒤 다시 시도해 주세요.", ephemeral=True)


def _on_off(value: bool) -> str:
    return "켬" if value else "끔"


def _clip(lines: list[str]) -> str:
    text = "\n".join(lines)
    return text if len(text) <= EMBED_LIMIT else text[: EMBED_LIMIT - 1] + "…"


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class TwitterCog(commands.GroupCog, group_name="twitter", group_description="트위터 알림 설정"):
    def __init__(self, store: TwitterStore, pool: ClientPool) -> None:
        self.store = store
        self.pool = pool
        super().__init__()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # 응답을 defer 한 뒤 예외가 나면 사용자 화면이 '생각 중…' 에 멈추므로 항상 답한다.
        log.exception("/twitter 명령 처리 중 오류", exc_info=error)
        message = "명령을 처리하다 오류가 났어요. 잠시 뒤 다시 시도해 주세요."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:
            log.exception("오류 응답도 보내지 못했습니다")

    @app_commands.command(name="add", description="트위터 계정의 새 글을 이 채널로 알려줘요")
    @app_commands.rename(
        username="계정", channel="채널", role="역할", retweets="리트윗", quotes="인용", client="봇계정",
    )
    @app_commands.describe(
        username="트위터 아이디 (@ 없이, 또는 프로필 링크)",
        channel="알림을 보낼 채널",
        role="알림 때 멘션할 역할 (비우면 멘션 없음)",
        retweets="리트윗도 알릴지 (기본: 켬)",
        quotes="인용도 알릴지 (기본: 켬)",
        client="이 계정을 맡을 봇 계정 (비우면 자동 선택)",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        username: str,
        channel: discord.TextChannel | discord.Thread,
        role: discord.Role | None = None,
        retweets: bool = True,
        quotes: bool = True,
        client: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await do_add(
            self.store, self.pool,
            username=username, guild_id=interaction.guild_id, channel_id=channel.id,
            role_id=role.id if role else None, retweets=retweets, quotes=quotes, client=client,
        )
        await interaction.followup.send(message, ephemeral=True)

    @add.autocomplete("client")
    async def _client_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=name, value=name)
            for name in self.pool.ok_names() if current.lower() in name.lower()
        ][:25]

    @app_commands.command(name="remove", description="트위터 계정 알림을 그만 받아요")
    @app_commands.rename(username="계정", channel="채널")
    @app_commands.describe(username="추적 중인 트위터 아이디", channel="알림을 받던 채널")
    async def remove(
        self,
        interaction: discord.Interaction,
        username: str,
        channel: discord.TextChannel | discord.Thread,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        message = await do_remove(
            self.store, self.pool, username=username, guild_id=interaction.guild_id, channel_id=channel.id,
        )
        await interaction.followup.send(message, ephemeral=True)

    @remove.autocomplete("username")
    async def _username_autocomplete(self, interaction: discord.Interaction, current: str):
        names = await self.store.usernames_in_guild(interaction.guild_id)
        return [
            app_commands.Choice(name=f"@{name}", value=name)
            for name in names if current.lower().lstrip("@") in name
        ][:25]

    @app_commands.command(name="message", description="알림 멘트를 바꿔요 (입력창이 열려요)")
    @app_commands.rename(username="계정", channel="채널")
    @app_commands.describe(username="추적 중인 트위터 아이디", channel="알림을 받는 채널")
    async def message(
        self,
        interaction: discord.Interaction,
        username: str,
        channel: discord.TextChannel | discord.Thread,
    ) -> None:
        name = normalize_username(username)
        found = await _find_subscription(self.store, name, interaction.guild_id, channel.id) if name else None
        if found is None:
            await interaction.response.send_message(
                f"이 채널에서 @{name or username} 를 추적하고 있지 않아요.", ephemeral=True,
            )
            return
        _, sub = found
        # 입력창은 첫 응답이어야 하므로 defer 하지 않는다.
        await interaction.response.send_modal(MessageModal(self.store, name, channel.id, sub.message))

    @message.autocomplete("username")
    async def _message_username_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._username_autocomplete(interaction, current)

    @app_commands.command(name="list", description="이 서버에서 추적 중인 트위터 계정을 보여줘요")
    async def list_(self, interaction: discord.Interaction) -> None:
        rows = await self.store.guild_subscriptions(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("이 서버에서 추적 중인 계정이 없어요.", ephemeral=True)
            return

        lines = []
        for target, sub in rows:
            if sub.role_id is None:
                role_text = "멘션 없음"
            elif interaction.guild.get_role(sub.role_id) is None:
                role_text = "삭제된 역할"
            else:
                role_text = f"<@&{sub.role_id}>"
            line = (
                f"@{target.username} → <#{sub.channel_id}> · {role_text} · "
                f"리트윗 {_on_off(sub.retweets)} · 인용 {_on_off(sub.quotes)} · 담당 {target.client_name}"
            )
            if sub.message:
                line += " · ✏️ 맞춤 멘트"
            owner_state = self.pool.get(target.client_name)
            if owner_state is None:
                line += " ⚠️ .env 에 없는 봇 계정"
            elif not owner_state.ok:
                line += " ❌ 봇 계정 오류"
            lines.append(line)

        embed = discord.Embed(title="트위터 알림 목록", description=_clip(lines), color=0x1D9BF0)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="accounts", description="봇이 쓰는 트위터 계정 상태를 보여줘요")
    async def accounts(self, interaction: discord.Interaction) -> None:
        counts = await self.store.count_by_client()
        lines = []
        for name, state in self.pool.states.items():
            last = f"<t:{int(state.last_success.timestamp())}:R>" if state.last_success else "없음"
            line = f"{'✅' if state.ok else '❌'} {name} · 담당 {counts.get(name, 0)}개 · 마지막 조회 {last}"
            if not state.ok:
                line += f" · {state.error or '로그인 전'}"
            lines.append(line)
        embed = discord.Embed(title="봇 트위터 계정", description=_clip(lines), color=0x1D9BF0)
        await interaction.response.send_message(embed=embed, ephemeral=True)

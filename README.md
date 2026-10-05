# Tweet-Notifier

트위터(X) 계정의 새 글을 디스코드로 알려주는 봇입니다.
공식 API 키 없이, 봇용 트위터 계정의 로그인 쿠키만으로 동작합니다.

지정한 트위터 계정이 **게시물 · 리트윗 · 인용**을 올리면, 지정한 채널에 **역할 멘션**과 함께 알려줍니다.

```
/twitter add 계정:nyachodayo 채널:#덕질 역할:@팬
```

<sub>Python 3.11+ · discord.py 2.x · tweety-ns · MIT License</sub>

## 특징

- **봇용 트위터 계정을 여러 개 돌려씁니다.** 새 추적 대상은 가장 한가한 계정에 자동으로 배정되고,
  계정 하나가 막혀도 나머지는 계속 동작합니다.
- **미리보기가 잘 보입니다.** 링크를 fxtwitter 로 바꿔 보내서 본문 · 이미지 · 영상이 디스코드에 펼쳐집니다.
- **알림이 쏟아지지 않습니다.** 처음 추적할 때 과거 트윗은 보내지 않고, 오래 꺼졌다 켜져도 계정당 최근 5개까지만 보냅니다.
- **문제가 생기면 알려줍니다.** `ALERT_CHANNEL_ID` 를 넣으면 봇 계정 로그인 실패나 조회 제한이 오래 이어질 때 그 채널로 경고합니다.
- **메모리 128MB 안에서 돕니다.** 무료 호스팅(Dishost) 상한을 전제로 디스코드 캐시를 꺼 두었습니다.
  (실측: Windows 에서 부계정 1개 · 추적 1개 · 서버 1개 기준 약 90MB)

---

## 명령어

모두 **서버 관리** 권한이 있는 사람만 쓸 수 있고, 응답은 본인에게만 보입니다.

| 명령 | 설명 |
|---|---|
| `/twitter add 계정 채널 [역할] [리트윗] [인용] [봇계정]` | 추적을 시작합니다. 리트윗 · 인용은 기본으로 켜져 있습니다. `봇계정` 을 비우면 자동으로 고르고, 이미 추적 중인 계정에 다른 봇계정을 고르면 그쪽으로 옮깁니다. 같은 채널에 다시 쓰면 설정을 덮어씁니다. |
| `/twitter remove 계정 채널` | 추적을 중지합니다. 그 계정을 구독하는 채널이 하나도 남지 않으면 봇 계정에서도 언팔로우합니다. |
| `/twitter message 계정 채널` | 알림 멘트를 바꿉니다. 입력창이 열리고, 비우고 저장하면 기본 멘트로 돌아갑니다. |
| `/twitter list` | 이 서버의 추적 목록 (채널 · 역할 · 리트윗/인용 설정 · 담당 봇계정 · ✏️ 맞춤 멘트 여부) |
| `/twitter accounts` | 봇 트위터 계정별 상태 (로그인 ✅/❌ · 담당 수 · 마지막 조회 시각) |

`계정` 에는 `nyachodayo`, `@nyachodayo`, `https://x.com/nyachodayo` 모두 쓸 수 있습니다.

알림은 이렇게 옵니다.

```
@팬 **ﾅﾁｮﾈｺ**님이 새 게시물을 올렸어요
https://fxtwitter.com/nyachodayo/status/1869000108697960952
```

### 알림 멘트 바꾸기

`/twitter message` 로 구독(계정 × 채널)마다 멘트를 따로 정할 수 있습니다. 쓸 수 있는 자리표시:

| 자리표시 | 바뀌는 내용 |
|---|---|
| `{mention}` | 역할 멘션 |
| `{author}` | 표시 이름 |
| `{username}` | 트위터 아이디 |
| `{action}` | 새 게시물을 올렸어요 / 리트윗했어요 / 인용했어요 |
| `{url}` | fxtwitter 링크 |

- 기본 멘트: `{mention} **{author}**님이 {action}` + 줄바꿈 + `{url}`
- `{url}` 을 빼면 링크를 맨 끝에 자동으로 붙입니다 (미리보기 유지).
- 멘트에 `@everyone` 을 적어도 실제로 울리는 건 지정한 역할뿐입니다. 최대 1500자.

---

## 설치

```shell
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # Linux / macOS
```

`.env.example` 을 `.env` 로 복사하고 값을 채운 뒤 실행합니다.

```shell
python app.py
```

### 설정값 (`.env`)

| 키 | 필수 | 설명 |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | 디스코드 봇 토큰 |
| `TWITTER_TOKEN` | ✅ | `별명:auth_token` 을 쉼표로 이어 적습니다. 예: `sub1:abcd...,sub2:efgh...` |
| `GUILD_ID` | | 테스트 서버 ID. 넣으면 명령어가 그 서버에 바로 등록됩니다 (비우면 전역, 최대 1시간) |
| `ALERT_CHANNEL_ID` | | 관리자 경고를 받을 채널 ID |
| `TWITTER_CHECK_SECONDS` | | 조회 간격(초). 기본 18, 최소 10 |
| `DATA_DIR` | | DB · 로그인 세션 저장 위치. 기본 `data` |

### 봇용 트위터 계정 준비 (`auth_token`)

> ⚠️ 이 계정은 추적 대상을 **실제로 팔로우하고 알림(종)을 켭니다.** 트위터 정책상 제재될 수 있으니
> **본 계정 대신 부계정**을 쓰세요.

1. 브라우저에서 부계정으로 x.com 에 로그인합니다.
2. 개발자 도구(F12) → Application(저장소) → Cookies → `https://x.com` 에서 `auth_token` 값을 복사합니다.
3. `.env` 에 `TWITTER_TOKEN=sub1:복사한값` 형식으로 넣습니다. 별명(`sub1`)은 영문 · 숫자 · `_` · `-` 로 자유롭게 정합니다.

토큰이 만료되면 `/twitter accounts` 에 ❌ 가 뜹니다. 새 토큰을 넣고 재시작하세요.
트위터에서 로그아웃하면 토큰이 무효가 되니, 복사한 뒤에는 브라우저 창만 닫으세요.

### 디스코드 봇 초대 권한

Developer Portal → OAuth2 → URL Generator 에서 `bot`, `applications.commands` 를 고르고 다음 권한을 줍니다.

- 채널 보기, 메시지 보내기, 스레드에서 메시지 보내기, 링크 첨부(임베드)
- **모든 역할 멘션하기** — 멘션 가능하도록 설정되지 않은 역할도 울리게 하려면 필요합니다

Privileged Gateway Intents 는 하나도 켤 필요가 없습니다.

---

## Dishost 배포

1. 이 폴더를 그대로 업로드합니다 (`.venv`, `data`, `.env` 는 제외).
2. 패널의 환경변수 탭에 `.env` 항목을 넣습니다 (또는 `.env` 파일을 업로드).
3. 시작 파일은 `app.py` 입니다. 기본값이라 따로 바꿀 필요가 없습니다.
4. `data/` 폴더는 지우지 마세요. 추적 목록과 로그인 세션이 들어 있습니다.

`tweety-ns` 는 git 없이 설치되도록 zip 주소로 고정해 두었습니다.

---

## 기능 추가하기

내부 패키지 이름이 `miniyatcho` 인 것은 서버 관리 봇 "미니얏쵸0호" 의 트위터 알림 기능을
독립 봇으로 떼어냈기 때문입니다. 같은 구조로 다른 기능도 붙일 수 있습니다.

기능 하나는 `miniyatcho/features/<이름>/` 패키지 하나입니다.

1. `miniyatcho/features/<이름>/__init__.py` 에 `async def setup(bot)` 을 만들고 Cog 를 붙입니다.
2. `miniyatcho/bot.py` 의 `EXTENSIONS` 에 `"miniyatcho.features.<이름>"` 을 추가합니다.
3. DB 가 필요하면 `bot.db.ensure_schema(...)` 로 자기 테이블만 만듭니다. 기능끼리는 서로 import 하지 않습니다.

한 기능의 로드가 실패해도 봇은 뜨고, 다른 기능은 그대로 동작합니다.

## 개발

```shell
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

## 라이선스

MIT. 트위터 추적 방식은 [Tweetcord](https://github.com/Yuuzi261/Tweetcord) (MIT) 를 참고했습니다 — [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

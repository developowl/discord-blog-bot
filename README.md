# discord-blog-bot

디스코드 블로그 포스팅 알림 봇

채널에 개발 블로그를 등록해두면, 새 글이 올라올 때 "누구의 새 글인지"와 함께 채널에 알려줍니다.

## 기능

| 커맨드 | 설명 | 권한 |
|---|---|---|
| `/등록` | 입력 창(모달)에서 이름, 닉네임, 블로그 URL을 입력해 블로그를 등록 | 채널 관리 |
| `/목록` | 이 채널에 등록된 블로그 목록 | 모두 |
| `/삭제 <블로그>` | 등록된 블로그 삭제 (자동완성) | 채널 관리 |

- 블로그 URL만 입력하면 RSS/Atom 피드를 자동으로 찾습니다. (HTML `<link rel="alternate">`, velog/medium 규칙, `/rss`·`/feed`·`/atom.xml` 등)
- 등록 시점에 이미 있던 글은 알리지 않고, 이후 새로 올라온 글만 알립니다.
- 권한은 서버 설정 → 연동 → 봇에서 바꿀 수 있습니다.

## 디스코드 봇 준비

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 애플리케이션 생성
2. Bot 탭에서 토큰 발급 → `DISCORD_TOKEN`
3. OAuth2 → URL Generator
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `View Channels`, `Send Messages`, `Embed Links`
4. 생성된 URL로 서버에 초대

Privileged Gateway Intents는 필요하지 않습니다.

## 로컬 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # DISCORD_TOKEN, DEV_GUILD_ID 입력
python -m bot
```

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_TOKEN` | (필수) | 봇 토큰 |
| `DEV_GUILD_ID` | | 지정 시 해당 서버에만 커맨드 등록 (즉시 반영) |
| `DB_PATH` | `data/bot.db` | SQLite 파일 경로 (컨테이너: `/data/bot.db`) |
| `POLL_INTERVAL_MINUTES` | `15` | 새 글 확인 주기 |
| `MAX_POSTS_PER_POLL` | `5` | 한 번에 보낼 최대 새 글 수 (초과분은 요약 메시지) |
| `ALLOW_PRIVATE_URLS` | | 로컬 테스트용. 켜면 내부망 주소 요청 허용 |

## 컨테이너

```bash
docker build -t discord-blog-bot .
docker run --env-file .env -v $(pwd)/data:/data discord-blog-bot
```

## 운영 시 주의

- 봇은 디스코드 Gateway에 아웃바운드로 연결하므로 Ingress가 필요 없습니다.
- 인스턴스는 반드시 하나만 실행합니다. 둘 이상이면 알림이 중복 전송됩니다. (K8s: `replicas: 1`, `strategy: Recreate`)
- SQLite 파일은 영구 볼륨에 저장합니다.

## 구조

```
bot/
├── __main__.py   # 봇 실행, 커맨드 동기화
├── config.py     # 환경변수
├── db.py         # SQLite (feeds, seen_posts)
├── feeds.py      # 피드 탐색·파싱, 내부망 요청 차단
├── commands.py   # /등록(모달), /목록, /삭제
├── poller.py     # 주기적 새 글 확인 및 전송
└── embeds.py     # 메시지 임베드
```

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    token: str
    dev_guild_id: int | None
    db_path: str
    poll_interval_minutes: float
    max_posts_per_poll: int
    allow_private_urls: bool

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise SystemExit("DISCORD_TOKEN 환경변수가 필요합니다.")
        guild = os.getenv("DEV_GUILD_ID", "").strip()
        return cls(
            token=token,
            dev_guild_id=int(guild) if guild else None,
            db_path=os.getenv("DB_PATH", "data/bot.db"),
            poll_interval_minutes=float(os.getenv("POLL_INTERVAL_MINUTES", "15")),
            max_posts_per_poll=int(os.getenv("MAX_POSTS_PER_POLL", "5")),
            allow_private_urls=_bool(os.getenv("ALLOW_PRIVATE_URLS")),
        )

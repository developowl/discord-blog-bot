from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    channel_id     INTEGER NOT NULL,
    owner_name     TEXT    NOT NULL,
    owner_nickname TEXT    NOT NULL,
    site_url       TEXT    NOT NULL,
    feed_url       TEXT    NOT NULL,
    title          TEXT,
    etag           TEXT,
    last_modified  TEXT,
    fail_count     INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    created_by     INTEGER NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (channel_id, feed_url)
);

CREATE TABLE IF NOT EXISTS seen_posts (
    feed_id  INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    post_key TEXT    NOT NULL,
    seen_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feed_id, post_key)
);
"""


@dataclass
class Feed:
    id: int
    guild_id: int
    channel_id: int
    owner_name: str
    owner_nickname: str
    site_url: str
    feed_url: str
    title: str | None
    etag: str | None
    last_modified: str | None
    fail_count: int
    active: bool

    @property
    def owner_label(self) -> str:
        return f"{self.owner_name}({self.owner_nickname})"


_FEED_COLUMNS = (
    "id, guild_id, channel_id, owner_name, owner_nickname, site_url, feed_url, "
    "title, etag, last_modified, fail_count, active"
)


def _to_feed(row) -> Feed:
    return Feed(*row[:11], active=bool(row[11]))


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def feed_exists(self, channel_id: int, feed_url: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM feeds WHERE channel_id = ? AND feed_url = ?",
            (channel_id, feed_url),
        )
        return await cur.fetchone() is not None

    async def add_feed(
        self,
        *,
        guild_id: int,
        channel_id: int,
        owner_name: str,
        owner_nickname: str,
        site_url: str,
        feed_url: str,
        title: str | None,
        etag: str | None,
        last_modified: str | None,
        created_by: int,
        seen_keys: list[str],
    ) -> int:
        cur = await self.conn.execute(
            """INSERT INTO feeds (guild_id, channel_id, owner_name, owner_nickname,
                   site_url, feed_url, title, etag, last_modified, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, channel_id, owner_name, owner_nickname, site_url, feed_url,
             title, etag, last_modified, created_by),
        )
        feed_id = cur.lastrowid
        await self.conn.executemany(
            "INSERT OR IGNORE INTO seen_posts (feed_id, post_key) VALUES (?, ?)",
            [(feed_id, k) for k in seen_keys],
        )
        await self.conn.commit()
        return feed_id

    async def list_feeds(self, channel_id: int) -> list[Feed]:
        cur = await self.conn.execute(
            f"SELECT {_FEED_COLUMNS} FROM feeds WHERE channel_id = ? ORDER BY id",
            (channel_id,),
        )
        return [_to_feed(r) for r in await cur.fetchall()]

    async def active_feeds(self) -> list[Feed]:
        cur = await self.conn.execute(
            f"SELECT {_FEED_COLUMNS} FROM feeds WHERE active = 1 ORDER BY id"
        )
        return [_to_feed(r) for r in await cur.fetchall()]

    async def get_feed(self, feed_id: int, channel_id: int) -> Feed | None:
        cur = await self.conn.execute(
            f"SELECT {_FEED_COLUMNS} FROM feeds WHERE id = ? AND channel_id = ?",
            (feed_id, channel_id),
        )
        row = await cur.fetchone()
        return _to_feed(row) if row else None

    async def delete_feed(self, feed_id: int) -> None:
        await self.conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        await self.conn.commit()

    async def unseen_keys(self, feed_id: int, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        placeholders = ",".join("?" * len(keys))
        cur = await self.conn.execute(
            f"SELECT post_key FROM seen_posts WHERE feed_id = ? AND post_key IN ({placeholders})",
            (feed_id, *keys),
        )
        seen = {r[0] for r in await cur.fetchall()}
        return set(keys) - seen

    async def mark_seen(self, feed_id: int, keys: list[str]) -> None:
        await self.conn.executemany(
            "INSERT OR IGNORE INTO seen_posts (feed_id, post_key) VALUES (?, ?)",
            [(feed_id, k) for k in keys],
        )
        await self.conn.commit()

    async def record_success(self, feed_id: int, etag: str | None, last_modified: str | None) -> None:
        await self.conn.execute(
            "UPDATE feeds SET etag = ?, last_modified = ?, fail_count = 0 WHERE id = ?",
            (etag, last_modified, feed_id),
        )
        await self.conn.commit()

    async def record_failure(self, feed_id: int) -> None:
        await self.conn.execute(
            "UPDATE feeds SET fail_count = fail_count + 1 WHERE id = ?", (feed_id,)
        )
        await self.conn.commit()

    async def deactivate(self, feed_id: int) -> None:
        await self.conn.execute("UPDATE feeds SET active = 0 WHERE id = ?", (feed_id,))
        await self.conn.commit()

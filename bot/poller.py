import asyncio
import logging

import discord
from discord.ext import commands, tasks

from . import embeds
from .db import Feed
from .feeds import fetch_feed

log = logging.getLogger(__name__)

CONCURRENCY = 5


class Poller(commands.Cog):
    def __init__(self, bot, interval_minutes: float, max_posts: int):
        self.bot = bot
        self.max_posts = max_posts
        self.loop.change_interval(minutes=interval_minutes)
        self._sem = asyncio.Semaphore(CONCURRENCY)

    async def cog_load(self) -> None:
        self.loop.start()

    async def cog_unload(self) -> None:
        self.loop.cancel()

    @tasks.loop(minutes=15)
    async def loop(self) -> None:
        feeds = await self.bot.db.active_feeds()
        log.info("폴링 시작: 피드 %d개", len(feeds))
        await asyncio.gather(*(self._guarded(f) for f in feeds))

    @loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _guarded(self, feed: Feed) -> None:
        async with self._sem:
            try:
                await self.check(feed)
            except Exception:
                log.exception("피드 확인 실패 #%s %s", feed.id, feed.feed_url)
                await self.bot.db.record_failure(feed.id)

    async def check(self, feed: Feed) -> None:
        db = self.bot.db
        result = await fetch_feed(self.bot.http_client, feed.feed_url, feed.etag, feed.last_modified)
        if result.not_modified:
            await db.record_success(feed.id, feed.etag, feed.last_modified)
            return

        keys = [e.key for e in result.entries]
        unseen = await db.unseen_keys(feed.id, keys)
        # 피드는 보통 최신순이므로 뒤집어서 오래된 글부터 보낸다.
        new_entries = [e for e in reversed(result.entries) if e.key in unseen]

        if new_entries:
            channel = await self._channel(feed)
            if channel is None:
                return
            skipped = max(0, len(new_entries) - self.max_posts)
            try:
                if skipped:
                    await channel.send(f"📚 **{feed.owner_label}** 님의 새 글이 {skipped}개 더 있어요: {feed.site_url}")
                    await db.mark_seen(feed.id, [e.key for e in new_entries[:skipped]])
                for entry in new_entries[skipped:]:
                    await channel.send(embed=embeds.new_post(feed, entry))
                    await db.mark_seen(feed.id, [entry.key])
            except discord.Forbidden:
                log.warning("채널 전송 권한이 없어 비활성화 #%s (channel=%s)", feed.id, feed.channel_id)
                await db.deactivate(feed.id)
                return
            log.info("새 글 %d개 처리 #%s", len(new_entries), feed.id)

        await db.record_success(feed.id, result.etag, result.last_modified)

    async def _channel(self, feed: Feed) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(feed.channel_id)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(feed.channel_id)
        except (discord.NotFound, discord.Forbidden):
            log.warning("채널에 접근할 수 없어 비활성화 #%s (channel=%s)", feed.id, feed.channel_id)
            await self.bot.db.deactivate(feed.id)
            return None

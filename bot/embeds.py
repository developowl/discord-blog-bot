import discord

from .db import Feed
from .feeds import Entry

COLOR = 0x5865F2


def registered(feed: Feed) -> discord.Embed:
    embed = discord.Embed(
        title=feed.title or feed.site_url,
        url=feed.site_url,
        description=f"🎉 **{feed.owner_label}** 님의 개발 블로그가 등록되었어요!",
        color=COLOR,
    )
    embed.set_footer(text="새 글이 올라오면 이 채널에 알려드릴게요.")
    return embed


def new_post(feed: Feed, entry: Entry) -> discord.Embed:
    embed = discord.Embed(
        title=entry.title[:256],
        url=entry.link,
        color=COLOR,
        timestamp=entry.published,
    )
    embed.set_author(name=f"📝 {feed.owner_label} 님의 새 글")
    embed.set_footer(text=(feed.title or feed.site_url)[:2048])
    if entry.image:
        embed.set_thumbnail(url=entry.image)
    return embed

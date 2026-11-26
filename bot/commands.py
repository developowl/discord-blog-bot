import logging

import discord
from discord import app_commands
from discord.ext import commands

from . import embeds
from .feeds import FeedError, discover_feed

log = logging.getLogger(__name__)


class RegisterModal(discord.ui.Modal, title="블로그 등록"):
    def __init__(self, cog: "BlogCommands", name: str = "", nickname: str = "", url: str = ""):
        super().__init__()
        self.cog = cog
        self.name = discord.ui.TextInput(label="이름", placeholder="홍길동", default=name or None, max_length=30)
        self.nickname = discord.ui.TextInput(label="닉네임", placeholder="gildong", default=nickname or None, max_length=30)
        self.url = discord.ui.TextInput(
            label="블로그 URL", placeholder="https://velog.io/@gildong", default=url or None, max_length=300
        )
        for item in (self.name, self.nickname, self.url):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        name, nickname, url = (v.value.strip() for v in (self.name, self.nickname, self.url))
        try:
            feed = await self.cog.register(interaction, name, nickname, url)
        except FeedError as e:
            await interaction.followup.send(
                f"❌ {e}", view=RetryView(self.cog, name, nickname, url), ephemeral=True
            )
            return

        embed = embeds.registered(feed)
        try:
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("✅ 등록했어요.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send(
                "✅ 등록했지만 채널에 메시지를 보낼 권한이 없어요. 봇의 채널 권한을 확인해주세요.",
                embed=embed,
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("등록 처리 중 오류", exc_info=error)
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send("❌ 처리 중 알 수 없는 오류가 발생했어요.", ephemeral=True)


class RetryView(discord.ui.View):
    def __init__(self, cog: "BlogCommands", name: str, nickname: str, url: str):
        super().__init__(timeout=600)
        self.cog, self.values = cog, (name, nickname, url)

    @discord.ui.button(label="다시 입력", style=discord.ButtonStyle.primary, emoji="✏️")
    async def retry(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RegisterModal(self.cog, *self.values))


class BlogCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def register(self, interaction: discord.Interaction, name: str, nickname: str, url: str):
        if not name or not nickname:
            raise FeedError("이름과 닉네임을 모두 입력해주세요.")
        site_url, feed_url, result = await discover_feed(self.bot.http_client, url)
        db = self.bot.db
        if await db.feed_exists(interaction.channel_id, feed_url):
            raise FeedError("이 채널에 이미 등록된 블로그예요.")
        feed_id = await db.add_feed(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            owner_name=name,
            owner_nickname=nickname,
            site_url=site_url,
            feed_url=feed_url,
            title=result.title,
            etag=result.etag,
            last_modified=result.last_modified,
            created_by=interaction.user.id,
            seen_keys=[e.key for e in result.entries],
        )
        log.info("등록: #%s %s → %s (channel=%s)", feed_id, site_url, feed_url, interaction.channel_id)
        return await db.get_feed(feed_id, interaction.channel_id)

    @app_commands.command(name="등록", description="블로그를 등록하고 새 글 알림을 받아요.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    async def register_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RegisterModal(self))

    @app_commands.command(name="목록", description="이 채널에 등록된 블로그를 보여줘요.")
    @app_commands.guild_only()
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        feeds = await self.bot.db.list_feeds(interaction.channel_id)
        if not feeds:
            await interaction.response.send_message("등록된 블로그가 없어요. `/등록`으로 추가해보세요.", ephemeral=True)
            return
        lines = [
            f"`{f.id}` **{f.owner_label}** — {f.site_url}" + ("" if f.active else " *(비활성)*")
            for f in feeds
        ]
        embed = discord.Embed(title=f"등록된 블로그 ({len(feeds)})", description="\n".join(lines)[:4096], color=embeds.COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="삭제", description="등록된 블로그를 삭제해요.")
    @app_commands.describe(블로그="삭제할 블로그")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    async def delete_cmd(self, interaction: discord.Interaction, 블로그: int) -> None:
        feed = await self.bot.db.get_feed(블로그, interaction.channel_id)
        if not feed:
            await interaction.response.send_message("❌ 이 채널에서 해당 블로그를 찾을 수 없어요.", ephemeral=True)
            return
        await self.bot.db.delete_feed(feed.id)
        await interaction.response.send_message(f"🗑️ **{feed.owner_label}** 님의 블로그를 삭제했어요.", ephemeral=True)

    @delete_cmd.autocomplete("블로그")
    async def delete_autocomplete(self, interaction: discord.Interaction, current: str):
        feeds = await self.bot.db.list_feeds(interaction.channel_id)
        current = current.lower()
        choices = []
        for f in feeds:
            label = f"{f.owner_label} - {f.site_url}"
            if current in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=f.id))
        return choices[:25]

import logging

import discord
from discord.ext import commands

from .commands import BlogCommands
from .config import Config
from .db import Database
from .feeds import make_client

log = logging.getLogger("bot")


class BlogBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.config = config
        self.db = Database(config.db_path)
        self.http_client = make_client(allow_private=config.allow_private_urls)

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.add_cog(BlogCommands(self))

        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("개발 서버(%s)에 커맨드 %d개 동기화", self.config.dev_guild_id, len(synced))
        else:
            synced = await self.tree.sync()
            log.info("전역 커맨드 %d개 동기화", len(synced))

    async def on_ready(self) -> None:
        log.info("로그인: %s (id=%s)", self.user, self.user.id)

    async def close(self) -> None:
        await super().close()
        await self.http_client.aclose()
        await self.db.close()


def main() -> None:
    config = Config.load()
    discord.utils.setup_logging(level=logging.INFO)
    BlogBot(config).run(config.token, log_handler=None)


if __name__ == "__main__":
    main()

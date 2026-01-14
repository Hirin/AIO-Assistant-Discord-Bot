"""
Discord Bot - Core Bot Class
"""

import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,  # We'll use slash command for help
        )
        # Get guild_id, only use if it's a valid numeric ID
        guild_id_str = os.getenv("GUILD_ID", "")
        self.guild_id = guild_id_str if guild_id_str.isdigit() else None

        # Track active dropdown messages per user
        self.active_dropdowns: dict[int, discord.Message] = {}

    async def setup_hook(self):
        """Load cogs and sync commands"""
        # Load cogs
        await self._load_cogs()

        # Sync commands
        if self.guild_id:
            guild = discord.Object(id=int(self.guild_id))
            # Copy to guild for instant sync
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Commands synced to guild {self.guild_id}")
        else:
            await self.tree.sync()
            logger.info("Commands synced globally")

    async def _load_cogs(self):
        """Auto-load all cogs from cogs directory"""
        cogs_dir = Path(__file__).parent / "cogs"

        for category in ["system", "meeting", "lecture", "ask"]:
            category_dir = cogs_dir / category
            if not category_dir.exists():
                continue

            # Check if category has __init__.py with setup() - load as package
            init_file = category_dir / "__init__.py"
            if init_file.exists() and "async def setup" in init_file.read_text():
                # Load the package itself (e.g., cogs.meeting)
                cog_path = f"cogs.{category}"
                try:
                    await self.load_extension(cog_path)
                    logger.info(f"Loaded cog package: {cog_path}")
                except Exception as e:
                    logger.error(f"Failed to load {cog_path}: {e}")
            else:
                # Fallback: load individual .py files
                for cog_file in category_dir.glob("*.py"):
                    if cog_file.name.startswith("_"):
                        continue

                    cog_path = f"cogs.{category}.{cog_file.stem}"
                    try:
                        await self.load_extension(cog_path)
                        logger.info(f"Loaded cog: {cog_path}")
                    except Exception as e:
                        logger.error(f"Failed to load {cog_path}: {e}")

    async def on_ready(self):
        """Bot is ready"""
        # Create health marker for Docker healthcheck
        Path("/tmp/healthy").touch()

        logger.info(f"Bot ready: {self.user} (ID: {self.user.id})")
        logger.info(f"Guilds: {len(self.guilds)}")

    async def on_guild_join(self, guild: discord.Guild):
        """Auto sync commands when bot joins a new guild"""
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Commands synced to new guild: {guild.name} ({guild.id})")
        except Exception as e:
            logger.error(f"Failed to sync commands to {guild.name}: {e}")

    async def on_error(self, event, *args, **kwargs):
        """Global error handler"""
        logger.exception(f"Unhandled error in event: {event}")

    @staticmethod
    def setup_logging():
        """Setup structured logging"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


# Setup logging on import
DiscordBot.setup_logging()

"""
Discord Bot - Core Bot Class
"""
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None  # We'll use slash command for help
        )
        
        self.guild_id = os.getenv("GUILD_ID")
    
    async def setup_hook(self):
        """Load cogs and sync commands"""
        # Load cogs
        await self._load_cogs()
        
        # Sync commands
        if self.guild_id:
            guild = discord.Object(id=int(self.guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Commands synced to guild {self.guild_id}")
        else:
            await self.tree.sync()
            logger.info("Commands synced globally")
    
    async def _load_cogs(self):
        """Auto-load all cogs from cogs directory"""
        cogs_dir = Path(__file__).parent / "cogs"
        
        for category in ["system", "meeting"]:
            category_dir = cogs_dir / category
            if not category_dir.exists():
                continue
            
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
        
        logger.info(f"✅ Bot ready: {self.user} (ID: {self.user.id})")
        logger.info(f"📊 Guilds: {len(self.guilds)}")
    
    async def on_error(self, event, *args, **kwargs):
        """Global error handler"""
        logger.exception(f"Unhandled error in event: {event}")
    
    @staticmethod
    def setup_logging():
        """Setup structured logging"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


# Setup logging on import
DiscordBot.setup_logging()

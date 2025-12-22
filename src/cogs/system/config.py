"""
Config Commands
/config set-api <key_type> <api_key> - Set API key for this server
/config show - Show current config (masked keys)
/config remove <key_type> - Remove API key
"""

import discord
from discord import app_commands
from discord.ext import commands

from services import config as config_service


class Config(commands.GroupCog, name="config"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="set-api", description="Set API key for this server")
    @app_commands.describe(
        key_type="Type of API key (glm, fireflies)",
        api_key="Your API key (will be stored securely)",
    )
    @app_commands.choices(
        key_type=[
            app_commands.Choice(name="GLM (Z.AI)", value="glm"),
            app_commands.Choice(name="Fireflies", value="fireflies"),
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_api(
        self, interaction: discord.Interaction, key_type: str, api_key: str
    ):
        """Set API key for this server (Admin only)"""
        guild_id = interaction.guild_id
        if not guild_id:
            await interaction.response.send_message(
                "❌ This command can only be used in a server", ephemeral=True
            )
            return

        # Store the key
        config_service.set_guild_config(guild_id, f"{key_type}_api_key", api_key)

        await interaction.response.send_message(
            f"✅ **{key_type.upper()} API key** đã được lưu cho server này!\n"
            f"Key: `{config_service.mask_key(api_key)}`",
            ephemeral=True,
        )

    @app_commands.command(name="show", description="Show current server config")
    @app_commands.checks.has_permissions(administrator=True)
    async def show(self, interaction: discord.Interaction):
        """Show current config for this server (Admin only)"""
        guild_id = interaction.guild_id
        if not guild_id:
            await interaction.response.send_message(
                "❌ This command can only be used in a server", ephemeral=True
            )
            return

        guild_config = config_service.get_guild_config(guild_id)

        embed = discord.Embed(title="⚙️ Server Config", color=discord.Color.blue())

        # GLM API Key
        glm_key = guild_config.get("glm_api_key")
        embed.add_field(
            name="GLM API Key",
            value=f"`{config_service.mask_key(glm_key)}`" if glm_key else "❌ Not set",
            inline=True,
        )

        # Fireflies API Key
        ff_key = guild_config.get("fireflies_api_key")
        embed.add_field(
            name="Fireflies API Key",
            value=f"`{config_service.mask_key(ff_key)}`" if ff_key else "❌ Not set",
            inline=True,
        )

        embed.set_footer(text="Use /config set-api to configure API keys")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove API key for this server")
    @app_commands.describe(key_type="Type of API key to remove")
    @app_commands.choices(
        key_type=[
            app_commands.Choice(name="GLM (Z.AI)", value="glm"),
            app_commands.Choice(name="Fireflies", value="fireflies"),
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction, key_type: str):
        """Remove API key for this server (Admin only)"""
        guild_id = interaction.guild_id
        if not guild_id:
            await interaction.response.send_message(
                "❌ This command can only be used in a server", ephemeral=True
            )
            return

        config_service.set_guild_config(guild_id, f"{key_type}_api_key", "")

        await interaction.response.send_message(
            f"✅ **{key_type.upper()} API key** đã được xóa khỏi server này!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))

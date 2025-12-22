"""
Config Command - Single command with action dropdown
/config <action> [value]
"""

import discord
from discord import app_commands
from discord.ext import commands

from services import config as config_service


class ConfigModal(discord.ui.Modal, title="Set Custom Prompt"):
    """Modal for entering custom prompt"""

    prompt = discord.ui.TextInput(
        label="Custom Prompt",
        style=discord.TextStyle.paragraph,
        placeholder="Bạn là trợ lý tóm tắt cuộc họp...",
        max_length=2000,
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        config_service.set_guild_config(
            self.guild_id, "custom_prompt", self.prompt.value
        )
        await interaction.response.send_message(
            f"✅ Custom prompt đã lưu!\n```{self.prompt.value[:200]}...```",
            ephemeral=True,
        )


class ApiModal(discord.ui.Modal, title="Set API Key"):
    """Modal for entering API key"""

    api_key = discord.ui.TextInput(
        label="API Key",
        style=discord.TextStyle.short,
        placeholder="Enter your API key",
    )

    def __init__(self, guild_id: int, key_type: str):
        super().__init__()
        self.guild_id = guild_id
        self.key_type = key_type

    async def on_submit(self, interaction: discord.Interaction):
        config_service.set_guild_config(
            self.guild_id, f"{self.key_type}_api_key", self.api_key.value
        )
        await interaction.response.send_message(
            f"✅ {self.key_type.upper()} API key đã lưu!",
            ephemeral=True,
        )


class ConfigView(discord.ui.View):
    """Dropdown view for config actions"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.select(
        placeholder="Chọn action...",
        options=[
            discord.SelectOption(label="Set GLM API Key", value="api_glm", emoji="🔑"),
            discord.SelectOption(
                label="Set Fireflies API Key", value="api_fireflies", emoji="🔥"
            ),
            discord.SelectOption(
                label="Set Custom Prompt", value="prompt_set", emoji="📝"
            ),
            discord.SelectOption(label="View Prompt", value="prompt_view", emoji="👁️"),
            discord.SelectOption(
                label="Reset Prompt", value="prompt_reset", emoji="🔄"
            ),
            discord.SelectOption(label="View Config", value="info", emoji="ℹ️"),
        ],
    )
    async def select_action(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        action = select.values[0]

        if action == "api_glm":
            await interaction.response.send_modal(ApiModal(self.guild_id, "glm"))

        elif action == "api_fireflies":
            await interaction.response.send_modal(ApiModal(self.guild_id, "fireflies"))

        elif action == "prompt_set":
            await interaction.response.send_modal(ConfigModal(self.guild_id))

        elif action == "prompt_view":
            prompt = config_service.get_custom_prompt(self.guild_id)
            is_custom = bool(
                config_service.get_guild_config(self.guild_id).get("custom_prompt")
            )
            await interaction.response.send_message(
                f"**{'Custom' if is_custom else 'Default'} Prompt:**\n```{prompt[:1500]}```",
                ephemeral=True,
            )

        elif action == "prompt_reset":
            config_service.set_guild_config(self.guild_id, "custom_prompt", "")
            await interaction.response.send_message(
                "✅ Reset về prompt mặc định!", ephemeral=True
            )

        elif action == "info":
            config = config_service.get_guild_config(self.guild_id)
            glm = config.get("glm_api_key")
            ff = config.get("fireflies_api_key")
            has_prompt = bool(config.get("custom_prompt"))

            embed = discord.Embed(title="⚙️ Server Config", color=discord.Color.blue())
            embed.add_field(
                name="API Keys",
                value=f"GLM: {'✅' if glm else '❌'} | Fireflies: {'✅' if ff else '❌'}",
                inline=False,
            )
            embed.add_field(
                name="Prompt",
                value="Custom ✅" if has_prompt else "Default",
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_messages: dict[int, discord.Message] = {}  # user_id -> message

    @app_commands.command(name="config", description="Server configuration")
    @app_commands.checks.has_permissions(administrator=True)
    async def config(self, interaction: discord.Interaction):
        """Show config options"""
        if not interaction.guild_id:
            await interaction.response.send_message(
                "❌ Chỉ dùng trong server", ephemeral=True
            )
            return

        # Delete previous dropdown for this user
        user_id = interaction.user.id
        if user_id in self._active_messages:
            try:
                await self._active_messages[user_id].delete()
            except Exception:
                pass

        view = ConfigView(interaction.guild_id)
        await interaction.response.send_message(
            "⚙️ **Server Config** - Chọn action:",
            view=view,
            delete_after=60,
        )

        # Store this message
        self._active_messages[user_id] = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))

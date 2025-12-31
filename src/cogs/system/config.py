"""
Config Command - Single command with action dropdown
/config <action> [value]
"""

import discord
from discord import app_commands
from discord.ext import commands

from services import config as config_service


# Note: Old ConfigModal removed - replaced by PromptEditModal (per-mode/per-type)


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


class TimezoneModal(discord.ui.Modal, title="Set Timezone"):
    """Modal for setting timezone"""

    timezone = discord.ui.TextInput(
        label="Timezone (UTC offset hoặc IANA)",
        style=discord.TextStyle.short,
        placeholder="UTC+7, UTC-5, Asia/Ho_Chi_Minh",
        default="UTC+7",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        from datetime import timezone as tz_module, timedelta
        from zoneinfo import ZoneInfo
        
        tz_name = self.timezone.value.strip()
        
        # Validate timezone - support both UTC+X and IANA format
        try:
            if tz_name.upper().startswith("UTC"):
                # Parse UTC+7 or UTC-5 format
                offset_str = tz_name[3:]
                if offset_str:
                    offset_hours = int(offset_str)
                else:
                    offset_hours = 0
                # Validate by creating timezone
                tz_module(timedelta(hours=offset_hours))
            else:
                # IANA format
                ZoneInfo(tz_name)
        except Exception:
            await interaction.response.send_message(
                f"❌ Timezone không hợp lệ: `{tz_name}`\n"
                "Dùng format: UTC+7, UTC-5, hoặc Asia/Ho_Chi_Minh",
                ephemeral=True,
            )
            return
        
        config_service.set_timezone(self.guild_id, tz_name)
        await interaction.response.send_message(
            f"✅ Timezone đã set: `{tz_name}`",
            ephemeral=True,
        )


class FirefliesLimitModal(discord.ui.Modal, title="Fireflies Storage Limit"):
    """Modal for setting max Fireflies records"""

    limit = discord.ui.TextInput(
        label="Max records (1-50, default 6)",
        style=discord.TextStyle.short,
        placeholder="6",
        default="6",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_val = int(self.limit.value.strip())
            if not 1 <= limit_val <= 50:
                raise ValueError("Out of range")
        except ValueError:
            await interaction.response.send_message(
                "❌ Số không hợp lệ. Nhập 1-50.",
                ephemeral=True,
            )
            return
        
        config_service.set_fireflies_max_records(self.guild_id, limit_val)
        await interaction.response.send_message(
            f"✅ Fireflies storage limit: `{limit_val}` records",
            ephemeral=True,
        )


# === New Nested Button Views ===


class ApiKeySelectionView(discord.ui.View):
    """Select which API key to set"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.button(label="🤖 Gemini API (Global)", style=discord.ButtonStyle.success)
    async def gemini_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set Global Gemini API for guild automation"""
        current_key = config_service.get_guild_gemini_api(self.guild_id)
        if current_key:
            status = f"✅ Đã set: `{config_service.mask_key(current_key)}`"
        else:
            status = "❌ Chưa set"
        
        view = GlobalGeminiApiView(self.guild_id)
        await interaction.response.edit_message(
            content=f"🤖 **Global Gemini API**\n\n"
                    f"Status: {status}\n\n"
                    f"_Dùng cho: Auto-join meeting, Scheduled summary_",
            view=view
        )

    @discord.ui.button(label="🔑 GLM API", style=discord.ButtonStyle.primary)
    async def glm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApiModal(self.guild_id, "glm"))

    @discord.ui.button(label="🔥 Fireflies API", style=discord.ButtonStyle.primary)
    async def fireflies_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApiModal(self.guild_id, "fireflies"))

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class GlobalGeminiApiView(discord.ui.View):
    """View for managing Global Gemini API key"""
    
    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id
    
    @discord.ui.button(label="⚙️ Set API", style=discord.ButtonStyle.primary)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GlobalGeminiApiModal(self.guild_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Xóa API", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_service.set_guild_gemini_api(self.guild_id, "")
        await interaction.response.send_message(
            "✅ Đã xóa Global Gemini API key",
            ephemeral=True
        )
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.secondary)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class GlobalGeminiApiModal(discord.ui.Modal, title="Set Global Gemini API"):
    """Modal for entering Global Gemini API key"""
    
    api_key = discord.ui.TextInput(
        label="Gemini API Key",
        placeholder="AIza...",
        required=True,
    )
    
    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        key = self.api_key.value.strip()
        config_service.set_guild_gemini_api(self.guild_id, key)
        
        await interaction.response.send_message(
            f"✅ Global Gemini API Key đã lưu: `{config_service.mask_key(key)}`\n"
            f"_Dùng cho auto-join meeting, scheduled summary_",
            ephemeral=True
        )


class ChannelTypeSelectionView(discord.ui.View):
    """Select channel type to set"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.button(label="📋 Meeting Channel", style=discord.ButtonStyle.primary)
    async def meeting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_service.set_meetings_channel(self.guild_id, interaction.channel_id)
        await interaction.response.send_message(
            f"✅ Đã set kênh này làm **Meetings Channel**!\n"
            f"Bot sẽ gửi summary vào <#{interaction.channel_id}>",
            ephemeral=True,
        )

    @discord.ui.button(label="📁 Archive Channel", style=discord.ButtonStyle.success)
    async def archive_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_service.set_archive_channel(self.guild_id, interaction.channel_id)
        await interaction.response.send_message(
            f"✅ Đã set kênh này làm **Archive Channel**!\n"
            f"Transcripts backup sẽ lưu vào <#{interaction.channel_id}>",
            ephemeral=True,
        )

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class PromptModeSelectionView(discord.ui.View):
    """Step 1: Select Meeting or Lecture mode"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.button(label="📋 Meeting", style=discord.ButtonStyle.primary)
    async def meeting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptTypeSelectionView(self.guild_id, mode="meeting")
        await interaction.response.edit_message(
            content="**Manage Prompts** - Chọn loại prompt (Meeting mode):",
            view=view
        )

    @discord.ui.button(label="📚 Lecture", style=discord.ButtonStyle.success)
    async def lecture_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptTypeSelectionView(self.guild_id, mode="lecture")
        await interaction.response.edit_message(
            content="**Manage Prompts** - Chọn loại prompt (Lecture mode):",
            view=view
        )

    @discord.ui.button(label="🎬 Gemini Video", style=discord.ButtonStyle.secondary)
    async def gemini_video_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GeminiPromptTypeSelectionView(self.guild_id)
        await interaction.response.edit_message(
            content="**Manage Prompts** - Chọn loại prompt (Gemini Video mode):",
            view=view
        )

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class GeminiPromptTypeSelectionView(discord.ui.View):
    """Select Gemini prompt type: Part 1, Part N, or Merge"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.button(label="1️⃣ Part 1 Prompt", style=discord.ButtonStyle.primary)
    async def part1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptActionSelectionView(self.guild_id, mode="gemini", prompt_type="lecture_part1")
        await interaction.response.edit_message(
            content="**Manage Prompts** - Gemini Part 1 - Chọn hành động:",
            view=view
        )

    @discord.ui.button(label="🔢 Part N Prompt", style=discord.ButtonStyle.primary)
    async def part_n_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptActionSelectionView(self.guild_id, mode="gemini", prompt_type="lecture_part_n")
        await interaction.response.edit_message(
            content="**Manage Prompts** - Gemini Part N - Chọn hành động:",
            view=view
        )

    @discord.ui.button(label="🔗 Merge Prompt", style=discord.ButtonStyle.success)
    async def merge_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptActionSelectionView(self.guild_id, mode="gemini", prompt_type="merge")
        await interaction.response.edit_message(
            content="**Manage Prompts** - Gemini Merge - Chọn hành động:",
            view=view
        )

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class PromptTypeSelectionView(discord.ui.View):
    """Step 2: Select VLM or Summary prompt"""

    def __init__(self, guild_id: int, mode: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.mode = mode

    @discord.ui.button(label="📄 Slide Extractor (VLM)", style=discord.ButtonStyle.primary)
    async def vlm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptActionSelectionView(self.guild_id, self.mode, prompt_type="vlm")
        mode_label = "Meeting" if self.mode == "meeting" else "Lecture"
        await interaction.response.edit_message(
            content=f"**Manage Prompts** - {mode_label} VLM - Chọn hành động:",
            view=view
        )

    @discord.ui.button(label="📝 Summary (LLM)", style=discord.ButtonStyle.success)
    async def summary_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PromptActionSelectionView(self.guild_id, self.mode, prompt_type="summary")
        mode_label = "Meeting" if self.mode == "meeting" else "Lecture"
        await interaction.response.edit_message(
            content=f"**Manage Prompts** - {mode_label} Summary - Chọn hành động:",
            view=view
        )

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class PromptActionSelectionView(discord.ui.View):
    """Step 3: Reset, Edit, or View the prompt"""

    def __init__(self, guild_id: int, mode: str, prompt_type: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.mode = mode
        self.prompt_type = prompt_type

    def _get_labels(self) -> tuple[str, str]:
        mode_label = "Meeting" if self.mode == "meeting" else "Lecture"
        type_label = "VLM" if self.prompt_type == "vlm" else "Summary"
        return mode_label, type_label

    @discord.ui.button(label="🔄 Reset Default", style=discord.ButtonStyle.danger)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_service.reset_prompt(self.guild_id, self.mode, self.prompt_type)
        mode_label, type_label = self._get_labels()
        await interaction.response.send_message(
            f"✅ Đã reset **{mode_label} {type_label}** prompt về mặc định!",
            ephemeral=True,
        )

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            PromptEditModal(self.guild_id, self.mode, self.prompt_type)
        )

    @discord.ui.button(label="👁️ View", style=discord.ButtonStyle.secondary)
    async def view_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        prompt_text = config_service.get_prompt(self.guild_id, self.mode, self.prompt_type)
        mode_label, type_label = self._get_labels()
        
        # Check if custom or default
        config = config_service.get_guild_config(self.guild_id)
        key = f"{self.mode}_{self.prompt_type}_prompt"
        is_custom = bool(config.get(key))
        status = "Custom ✏️" if is_custom else "Default ⚙️"
        
        # Send to channel (may be long)
        header = f"**{mode_label} {type_label} Prompt** ({status}, {len(prompt_text)} chars)\n"
        content = f"{header}```\n{prompt_text[:1800]}{'...' if len(prompt_text) > 1800 else ''}\n```"
        await interaction.response.send_message(content, ephemeral=True)

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class PromptEditModal(discord.ui.Modal):
    """Modal for editing a specific prompt"""

    def __init__(self, guild_id: int, mode: str, prompt_type: str):
        mode_label = "Meeting" if mode == "meeting" else "Lecture"
        type_label = "VLM" if prompt_type == "vlm" else "Summary"
        super().__init__(title=f"Edit {mode_label} {type_label} Prompt")
        
        self.guild_id = guild_id
        self.mode = mode
        self.prompt_type = prompt_type
        
        # Get current prompt
        current = config_service.get_prompt(guild_id, mode, prompt_type)
        
        self.prompt_input = discord.ui.TextInput(
            label=f"Prompt ({len(current)} chars)",
            style=discord.TextStyle.paragraph,
            default=current[:4000],  # Modal limit
            required=True,
            max_length=4000
        )
        self.add_item(self.prompt_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_prompt = self.prompt_input.value.strip()
        config_service.set_prompt(self.guild_id, self.mode, self.prompt_type, new_prompt)
        
        mode_label = "Meeting" if self.mode == "meeting" else "Lecture"
        type_label = "VLM" if self.prompt_type == "vlm" else "Summary"
        
        await interaction.response.send_message(
            f"✅ Đã lưu **{mode_label} {type_label}** prompt ({len(new_prompt)} chars)",
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
            discord.SelectOption(label="🔑 Set API Keys", value="api_keys"),
            discord.SelectOption(label="📍 Set This Channel For...", value="set_channel"),
            discord.SelectOption(label="📝 Manage Prompts", value="manage_prompts"),
            discord.SelectOption(label="⚙️ View Config", value="info"),
            discord.SelectOption(label="🕐 Custom Timezone", value="timezone"),
            discord.SelectOption(label="📼 Fireflies Storage Limit", value="ff_limit"),
            discord.SelectOption(label="🔄 Sync Commands", value="sync_commands"),
        ],
    )
    async def select_action(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        action = select.values[0]

        if action == "api_keys":
            # Show API key selection buttons
            view = ApiKeySelectionView(self.guild_id)
            await interaction.response.send_message(
                "🔑 **Set API Keys** - Chọn loại API:",
                view=view,
                ephemeral=True,
            )

        elif action == "set_channel":
            # Show channel type selection buttons
            view = ChannelTypeSelectionView(self.guild_id)
            await interaction.response.send_message(
                f"📍 **Set This Channel** (<#{interaction.channel_id}>) - Chọn loại:",
                view=view,
                ephemeral=True,
            )

        elif action == "manage_prompts":
            # Show prompt mode selection (Step 1)
            view = PromptModeSelectionView(self.guild_id)
            await interaction.response.send_message(
                "📝 **Manage Prompts** - Chọn chế độ:",
                view=view,
                ephemeral=True,
            )

        elif action == "info":
            config = config_service.get_guild_config(self.guild_id)
            glm = config.get("glm_api_key")
            ff = config.get("fireflies_api_key")
            channel_id = config.get("meetings_channel")
            timezone = config_service.get_timezone(self.guild_id)
            archive_id = config_service.get_archive_channel(self.guild_id)
            ff_limit = config_service.get_fireflies_max_records(self.guild_id)

            # Build prompt status for all 4 prompts
            def prompt_status(mode: str, ptype: str) -> str:
                key = f"{mode}_{ptype}_prompt"
                is_custom = bool(config.get(key))
                if is_custom:
                    return f"Custom ✏️ ({len(config.get(key, ''))} chars)"
                return "Default ⚙️"

            embed = discord.Embed(
                title="⚙️ Server Configuration",
                color=discord.Color.blue()
            )
            
            # API Connections
            gemini_global = config_service.get_guild_gemini_api(self.guild_id)
            embed.add_field(
                name="📡 API Connections",
                value=(
                    f"• Gemini (Global): {'✅ Configured' if gemini_global else '❌ Not set'}\n"
                    f"• GLM: {'✅ Configured' if glm else '❌ Not set'}\n"
                    f"• Fireflies: {'✅ Configured' if ff else '❌ Not set'}"
                ),
                inline=False,
            )
            
            # Prompts (4 total)
            embed.add_field(
                name="📝 Meeting Prompts",
                value=(
                    f"• VLM: {prompt_status('meeting', 'vlm')}\n"
                    f"• Summary: {prompt_status('meeting', 'summary')}"
                ),
                inline=True,
            )
            embed.add_field(
                name="📚 Lecture Prompts",
                value=(
                    f"• VLM: {prompt_status('lecture', 'vlm')}\n"
                    f"• Summary: {prompt_status('lecture', 'summary')}"
                ),
                inline=True,
            )
            
            # Channels
            embed.add_field(
                name="📍 Channels",
                value=(
                    f"• Meetings: {f'<#{channel_id}>' if channel_id else 'Not set'}\n"
                    f"• Archive: {f'<#{archive_id}>' if archive_id else 'Not set'}"
                ),
                inline=False,
            )
            
            # Settings
            embed.add_field(
                name="⚙️ Settings",
                value=(
                    f"• Timezone: `{timezone}`\n"
                    f"• Fireflies Limit: `{ff_limit}` records"
                ),
                inline=False,
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "timezone":
            await interaction.response.send_modal(TimezoneModal(self.guild_id))

        elif action == "ff_limit":
            await interaction.response.send_modal(FirefliesLimitModal(self.guild_id))

        elif action == "sync_commands":
            # Sync commands to this guild
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                bot = interaction.client
                guild = interaction.guild
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                await interaction.followup.send(
                    "✅ Đã sync commands cho server này!",
                    ephemeral=True,
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Lỗi sync: {str(e)[:100]}",
                    ephemeral=True,
                )

    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.secondary, row=1)
    async def reload_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Reload the dropdown view"""
        await interaction.response.edit_message(view=ConfigView(self.guild_id))

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger, row=1)
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Delete the message"""
        await interaction.message.delete()


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
        if user_id in self.bot.active_dropdowns:
            try:
                await self.bot.active_dropdowns[user_id].delete()
            except Exception:
                pass

        view = ConfigView(interaction.guild_id)
        await interaction.response.send_message(
            "⚙️ **Server Config** - Chọn action:",
            view=view,
            delete_after=60,
        )

        # Store this message
        self.bot.active_dropdowns[user_id] = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))

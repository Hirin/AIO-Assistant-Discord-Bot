"""
Meeting Cog - Main command and view for meeting management
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services import scheduler, transcript_storage, config as config_service

from .modals import (
    CancelScheduleModal,
    DeleteSavedModal,
    JoinMeetingModal,
    MeetingIdModal,
    ScheduleMeetingModal,
)

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 10


class BackupPaginationView(discord.ui.View):
    """Paginated view for backup transcripts"""

    def __init__(self, guild_id: int, transcripts: list[dict], page: int = 0):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.transcripts = transcripts
        self.page = page
        self.total_pages = max(1, (len(transcripts) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    def build_embed(self) -> discord.Embed:
        """Build embed for current page"""
        embed = discord.Embed(
            title="📥 Backup Transcripts",
            color=discord.Color.blue()
        )
        
        start = self.page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_items = self.transcripts[start:end]
        
        for t in page_items:
            title = t.get("title", "Untitled")[:30]
            local_id = t.get("local_id", "")
            display_id = local_id[:12]  # Truncate only for display
            ts = t.get("created_timestamp", 0)
            time_str = f"<t:{ts}:d>" if ts else "N/A"
            
            # Check backup status - use FULL ID for lookup
            full_entry = transcript_storage.get_transcript(self.guild_id, local_id)
            if full_entry and full_entry.get("backup_url"):
                status = f"✅ [Download]({full_entry['backup_url']})"
            elif full_entry:
                status = "⚠️ No backup"
            else:
                status = "🗑️ Deleted"
            
            embed.add_field(
                name=f"📝 {title}",
                value=f"ID: `{display_id}` | {time_str} | {status}",
                inline=False,
            )
        
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✏️ Edit Title", style=discord.ButtonStyle.primary, row=1)
    async def edit_title_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to edit transcript title by local ID"""
        from .modals import EditTitleModal
        modal = EditTitleModal(self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🗑️ Remove", style=discord.ButtonStyle.danger, row=1)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to remove transcript from local storage"""
        modal = RemoveTranscriptModal(self.guild_id, self)
        await interaction.response.send_modal(modal)


class RemoveTranscriptModal(discord.ui.Modal, title="Remove Transcript"):
    """Modal for removing transcript from local storage"""

    local_id = discord.ui.TextInput(
        label="Local Transcript ID",
        style=discord.TextStyle.short,
        placeholder="v_dfbc... (copy từ list trên)",
    )

    def __init__(self, guild_id: int, parent_view: BackupPaginationView):
        super().__init__()
        self.guild_id = guild_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        local_id = self.local_id.value.strip()
        
        if transcript_storage.delete_transcript(local_id):
            # Refresh the view
            self.parent_view.transcripts = transcript_storage.list_transcripts(self.guild_id)
            self.parent_view.total_pages = max(1, (len(self.parent_view.transcripts) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            if self.parent_view.page >= self.parent_view.total_pages:
                self.parent_view.page = max(0, self.parent_view.total_pages - 1)
            
            embed = self.parent_view.build_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        else:
            await interaction.response.send_message(
                f"❌ Không tìm thấy transcript `{local_id}`", ephemeral=True
            )


class WhitelistView(discord.ui.View):
    """Dropdown view for managing whitelist"""

    def __init__(self, guild_id: int, transcripts: list[dict]):
        super().__init__(timeout=180)  # Increased to 3 mins
        self.guild_id = guild_id
        self.transcripts = transcripts
        self._build_select()

    def _build_select(self):
        from services import config
        
        whitelist = config.get_whitelist_transcripts(self.guild_id)
        
        options = []
        for t in self.transcripts[:25]:
            t_id = t.get("id", "")
            title = t.get("title", "Untitled")[:50]
            is_whitelisted = t_id in whitelist
            
            options.append(
                discord.SelectOption(
                    label=f"{'🛡️ ' if is_whitelisted else ''}{title[:45]}",
                    value=t_id,
                    description="Click to toggle" + (" (protected)" if is_whitelisted else ""),
                )
            )
        
        if options:
            select = discord.ui.Select(
                placeholder="Chọn transcript để toggle whitelist...",
                options=options,
                max_values=1,
            )
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        from services import config
        
        selected_id = interaction.data["values"][0]
        whitelist = config.get_whitelist_transcripts(self.guild_id)
        
        if selected_id in whitelist:
            config.remove_from_whitelist(self.guild_id, selected_id)
            await interaction.response.send_message(
                f"✅ Đã bỏ `{selected_id}` khỏi whitelist",
                ephemeral=True,
            )
        else:
            config.add_to_whitelist(self.guild_id, selected_id)
            await interaction.response.send_message(
                f"🛡️ Đã thêm `{selected_id}` vào whitelist",
                ephemeral=True,
            )


def mask_key_short(key: str) -> str:
    """Show first 3 and last 3 chars only"""
    if len(key) <= 6:
        return "*" * len(key)
    return key[:3] + "..." + key[-3:]


class GeminiApiStatusView(discord.ui.View):
    """View showing Gemini API status with Set button"""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
    
    @discord.ui.button(label="🔧 Set API", style=discord.ButtonStyle.primary)
    async def set_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GeminiApiModal(self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Xóa API", style=discord.ButtonStyle.danger)
    async def delete_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_service.set_user_gemini_api(self.user_id, None)
        await interaction.response.send_message(
            "✅ Đã xóa Gemini API key. Sẽ dùng GLM mặc định.",
            ephemeral=True
        )


class GeminiApiModal(discord.ui.Modal, title="Set Gemini API Key"):
    """Modal for entering personal Gemini API key"""
    
    api_key = discord.ui.TextInput(
        label="Gemini API Key",
        placeholder="AIza...",
        required=True,
    )
    
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        key = self.api_key.value.strip()
        
        # Save to user config
        config_service.set_user_gemini_api(self.user_id, key)
        
        await interaction.response.send_message(
            f"✅ API Key đã lưu: `{mask_key_short(key)}`\n"
            f"Gemini sẽ được ưu tiên sử dụng khi summarize.",
            ephemeral=True
        )


class MeetingView(discord.ui.View):
    """Dropdown view for meeting actions"""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the user who invoked the command to interact"""
        if interaction.user.id == self.origin_user_id:
            return True
        await interaction.response.send_message("❌ Menu này không phải của bạn!", ephemeral=True)
        return False

    async def on_timeout(self):
        """Delete message on timeout"""
        try:
            if hasattr(self, "message") and self.message:
                await self.message.delete()
        except Exception:
            pass

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=60)  # Reset to 60s
        self.guild_id = guild_id
        self.origin_user_id = user_id
        # Add link button for supported platforms
        self.add_item(
            discord.ui.Button(
                label="Supported Platforms",
                url="https://fireflies.ai/integrations",
                style=discord.ButtonStyle.link,
                row=1,
            )
        )

    @discord.ui.select(
        placeholder="Chọn action...",
        options=[
            discord.SelectOption(label="📋 List from Fireflies", value="list_ff"),
            discord.SelectOption(label="📥 View Backup Transcripts", value="view_backup"),
            discord.SelectOption(label="✏️ Summarize Meeting", value="summary"),
            discord.SelectOption(label="📝 Edit Title", value="edit_title"),
            discord.SelectOption(label="🚀 Join Now", value="join"),
            discord.SelectOption(label="📅 Schedule Join", value="schedule"),
            discord.SelectOption(label="👀 View Scheduled", value="view_scheduled"),
            discord.SelectOption(label="❌ Cancel Schedule", value="cancel_schedule"),
            discord.SelectOption(label="🗑️ Delete Transcript", value="delete_transcript"),
            discord.SelectOption(label="🛡️ Manage Whitelist", value="whitelist"),
        ],
    )
    async def select_action(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        action = select.values[0]

        if action == "list_ff":
            # List transcripts from Fireflies API
            from services import fireflies_api, config
            
            await interaction.response.defer(ephemeral=True)
            
            transcripts = await fireflies_api.list_transcripts(self.guild_id, limit=20)
            
            if not transcripts:
                await interaction.followup.send(
                    "📁 Không có transcript nào trên Fireflies.", ephemeral=True
                )
                return
            
            whitelist = config.get_whitelist_transcripts(self.guild_id)
            embed = discord.Embed(
                title="📋 List from Fireflies", 
                color=discord.Color.blue()
            )
            
            for t in transcripts[:10]:
                t_id = t.get("id", "")
                title = t.get("title", "Untitled")[:40]
                duration = t.get("duration", 0)
                date_ms = t.get("date", 0)
                
                # Format duration (minutes)
                dur_str = f"{int(duration)}m" if duration else "N/A"
                # Format date
                time_str = f"<t:{date_ms // 1000}:f>" if date_ms else "N/A"
                # Whitelist badge
                wl_badge = " 🛡️" if t_id in whitelist else ""
                
                embed.add_field(
                    name=f"📝 {title}{wl_badge}",
                    value=f"**ID:** `{t_id}`\n⏱️ {dur_str} | {time_str}",
                    inline=False,
                )
            
            embed.set_footer(text="🛡️ = Whitelisted (không bị xóa khi queue đầy)")
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif action == "summary":
            await interaction.response.send_modal(MeetingIdModal(self.guild_id))

        elif action == "edit_title":
            from .modals import EditTitleModal
            await interaction.response.send_modal(EditTitleModal(self.guild_id))

        elif action == "join":
            await interaction.response.send_modal(JoinMeetingModal(self.guild_id))

        elif action == "schedule":
            await interaction.response.send_modal(ScheduleMeetingModal(self.guild_id))

        elif action == "view_scheduled":
            scheduled = scheduler.get_scheduled_for_guild(self.guild_id)

            if not scheduled:
                await interaction.response.send_message(
                    "📅 Không có meeting nào được lên lịch.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title="📅 Scheduled Meetings", color=discord.Color.green()
            )
            for m in scheduled[:5]:
                time_str = m.get("scheduled_time", "")[:16]
                link = m.get("meeting_link", "")[:30]
                embed.add_field(
                    name=f"{m.get('title') or 'Meeting'}",
                    value=f"**ID:** `{m.get('id')}`\n**Time:** {time_str}\n**Link:** {link}...",
                    inline=False,
                )

            embed.set_footer(text="Dùng Cancel Schedule để hủy")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "cancel_schedule":
            await interaction.response.send_modal(CancelScheduleModal(self.guild_id))

        elif action == "delete_transcript":
            await interaction.response.send_modal(DeleteSavedModal(self.guild_id))

        elif action == "view_backup":
            # View backup transcripts with status
            await interaction.response.defer(ephemeral=True)
            
            saved = transcript_storage.list_transcripts(self.guild_id, limit=50)
            
            if not saved:
                await interaction.followup.send(
                    "📁 Chưa có backup transcript nào.", ephemeral=True
                )
                return
            
            # Show paginated view
            view = BackupPaginationView(self.guild_id, saved, page=0)
            embed = view.build_embed()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        elif action == "whitelist":
            # Manage whitelist with dropdown
            from services import fireflies_api
            
            await interaction.response.defer(ephemeral=True)
            
            transcripts = await fireflies_api.list_transcripts(self.guild_id, limit=25)
            
            if not transcripts:
                await interaction.followup.send(
                    "📁 Không có transcript nào trên Fireflies để whitelist.",
                    ephemeral=True,
                )
                return
            
            view = WhitelistView(self.guild_id, transcripts)
            await interaction.followup.send(
                "🛡️ **Manage Whitelist** - Toggle để thêm/bỏ protection:",
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.secondary, row=1)
    async def reload_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Reload the dropdown view"""
        await interaction.response.edit_message(view=MeetingView(self.guild_id, self.origin_user_id))

    @discord.ui.button(label="🤖 Gemini API", style=discord.ButtonStyle.secondary, row=1)
    async def gemini_api_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show Gemini API config view (multi-key)"""
        from cogs.shared.gemini_config_view import GeminiConfigView
        
        user_id = interaction.user.id
        view = GeminiConfigView(user_id)
        embed = view._build_status_embed()
        
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger, row=1)
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Delete the message"""
        await interaction.message.delete()


class Meeting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Start scheduler background task
        self.scheduler_task = bot.loop.create_task(scheduler.run_scheduler(bot))

    def cog_unload(self):
        self.scheduler_task.cancel()

    @app_commands.command(name="meeting", description="Meeting tools")
    async def meeting(self, interaction: discord.Interaction):
        """Show meeting options"""
        if not interaction.guild_id:
            await interaction.response.send_message(
                "❌ Chỉ dùng trong server", ephemeral=True
            )
            return

        # Delete previous dropdown
        user_id = interaction.user.id
        if user_id in self.bot.active_dropdowns:
            try:
                await self.bot.active_dropdowns[user_id].delete()
            except Exception:
                pass

        view = MeetingView(interaction.guild_id, user_id)
        await interaction.response.send_message(
            "📋 **Meeting** - Chọn action:",
            view=view,
            # Removed delete_after=60 so it respects view timeout (5 mins)
        )
        
        # Store message for on_timeout deletion
        message = await interaction.original_response()
        view.message = message

        self.bot.active_dropdowns[user_id] = message

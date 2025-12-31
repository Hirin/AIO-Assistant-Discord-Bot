"""
Shared Gemini Config View
Reusable multi-key Gemini API configuration UI for /lecture and /meeting.
"""
import discord
import logging

from services import config as config_service
from services import gemini as gemini_service
from services.gemini_keys import GeminiKeyPool, get_key_count


def mask_key_tail(key: str) -> str:
    """Show last 5 characters of API key for identification."""
    if len(key) <= 5:
        return "*" * len(key)
    return f"...{key[-5:]}"

logger = logging.getLogger(__name__)


class GeminiConfigView(discord.ui.View):
    """
    Shared view for managing personal Gemini API keys.
    Used by both /lecture and /meeting commands.
    """
    
    def __init__(self, user_id: int, return_callback=None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.return_callback = return_callback  # Optional callback to return to parent view
    
    async def refresh_status(self, interaction: discord.Interaction):
        """Refresh the status embed."""
        embed = self._build_status_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    def _build_status_embed(self) -> discord.Embed:
        """Build status embed showing all keys."""
        keys = config_service.get_user_gemini_apis(self.user_id)
        
        embed = discord.Embed(
            title="🔑 Gemini API Keys (Personal)",
            description="Quản lý API keys cá nhân cho Lecture/Meeting summary.",
            color=discord.Color.blue()
        )
        
        if not keys:
            embed.add_field(
                name="Chưa có API key",
                value="Nhấn **➕ Add Key** để thêm API key.\n"
                      "_Free tier: 20 requests/day/key_",
                inline=False
            )
        else:
            # Show each key with status
            pool = GeminiKeyPool(self.user_id, keys)
            statuses = pool.get_status()
            
            key_lines = []
            for i, s in enumerate(statuses):
                status_emoji = "🔴" if s["rate_limited"] else "🟢"
                key_tail = mask_key_tail(keys[i])
                key_lines.append(
                    f"{status_emoji} Key #{s['index']+1} (`{key_tail}`) - "
                    f"**{s['count']}/{s['limit']}** requests"
                )
            
            embed.add_field(
                name=f"API Keys ({len(keys)}/{config_service.MAX_GEMINI_KEYS})",
                value="\n".join(key_lines),
                inline=False
            )
        
        embed.set_footer(text="🟢 Available | 🔴 Rate limited | Reset: 3:00 PM (UTC+7)")
        return embed
    
    @discord.ui.button(label="➕ Add Key", style=discord.ButtonStyle.success)
    async def add_key_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to add new API key."""
        keys = config_service.get_user_gemini_apis(self.user_id)
        if len(keys) >= config_service.MAX_GEMINI_KEYS:
            await interaction.response.send_message(
                f"❌ Đã đạt giới hạn {config_service.MAX_GEMINI_KEYS} API keys!",
                ephemeral=True
            )
            return
        
        modal = AddGeminiKeyModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Remove Key", style=discord.ButtonStyle.danger)
    async def remove_key_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show dropdown to select key to remove."""
        keys = config_service.get_user_gemini_apis(self.user_id)
        if not keys:
            await interaction.response.send_message(
                "❌ Không có API key nào để xóa!",
                ephemeral=True
            )
            return
        
        # Show select menu
        view = RemoveKeySelectView(self.user_id, keys, parent_view=self)
        embed = discord.Embed(
            title="🗑️ Chọn API key để xóa",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="🧪 Test All", style=discord.ButtonStyle.secondary)
    async def test_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Test all API keys."""
        await interaction.response.defer(ephemeral=True)
        
        keys = config_service.get_user_gemini_apis(self.user_id)
        if not keys:
            await interaction.followup.send("❌ Không có API key nào!", ephemeral=True)
            return
        
        results = []
        for i, key in enumerate(keys):
            try:
                await gemini_service.test_api(key)
                results.append(f"✅ Key #{i+1}: OK")
            except Exception as e:
                error_msg = str(e)[:50]
                results.append(f"❌ Key #{i+1}: {error_msg}")
        
        await interaction.followup.send(
            "**🧪 Test Results:**\n" + "\n".join(results),
            ephemeral=True
        )
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh status."""
        await self.refresh_status(interaction)
    
    @discord.ui.button(label="⬅️ Quay lại", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go back or close the view."""
        if self.return_callback:
            await self.return_callback(interaction)
        else:
            await interaction.response.edit_message(content="✅ Đã đóng", embed=None, view=None)


class AddGeminiKeyModal(discord.ui.Modal, title="Add Gemini API Key"):
    """Modal for adding a new Gemini API key."""
    
    api_key = discord.ui.TextInput(
        label="Gemini API Key",
        placeholder="AIza...",
        required=True,
        min_length=10,
    )
    
    def __init__(self, parent_view: GeminiConfigView):
        super().__init__()
        self.parent_view = parent_view
    
    async def on_submit(self, interaction: discord.Interaction):
        key = self.api_key.value.strip()
        
        # Add key
        success, message = config_service.add_user_gemini_api(
            self.parent_view.user_id, key
        )
        
        if success:
            # Refresh parent view
            embed = self.parent_view._build_status_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)


class RemoveKeySelectView(discord.ui.View):
    """View with select menu to choose which key to remove."""
    
    def __init__(self, user_id: int, keys: list[str], parent_view: GeminiConfigView):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.parent_view = parent_view
        
        # Build options with last 5 chars for identification
        options = []
        for i, key in enumerate(keys):
            key_tail = mask_key_tail(key)
            count = get_key_count(user_id, key)
            options.append(discord.SelectOption(
                label=f"Key #{i+1} ({key_tail})",
                description=f"{count}/20 requests today",
                value=str(i)
            ))
        
        select = discord.ui.Select(
            placeholder="Chọn key để xóa...",
            options=options,
            min_values=1,
            max_values=1,
            row=0,  # Dropdown on top
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        """Handle key selection."""
        index = int(interaction.data["values"][0])
        
        success, message = config_service.remove_user_gemini_api(self.user_id, index)
        
        if success:
            # Return to parent view
            embed = self.parent_view._build_status_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    
    @discord.ui.button(label="⬅️ Quay lại", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go back to parent view."""
        embed = self.parent_view._build_status_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

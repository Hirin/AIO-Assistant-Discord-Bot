"""
Lecture Cog - /lecture command with Video summarization via Gemini
Per-user Gemini API key management (multi-key support)
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from services import config as config_service

logger = logging.getLogger(__name__)


class LectureCog(commands.Cog):
    """Lecture summarization commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="lecture", description="Tóm tắt bài giảng từ video")
    async def lecture(self, interaction: discord.Interaction):
        """Main lecture command - shows action buttons"""
        view = LectureMainView(interaction.guild_id, interaction.user.id, interaction)
        
        embed = discord.Embed(
            title="🎓 Lecture Summary",
            description="Chọn hành động:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="🎬 Record Summary",
            value="Tóm tắt bài giảng từ video (Gemini)",
            inline=False
        )
        embed.add_field(
            name="📄 Preview Slides",
            value="Xem trước nội dung slides trước buổi học",
            inline=True
        )
        embed.add_field(
            name="🔑 Personal Config",
            value="Cấu hình API keys cá nhân (Gemini/AssemblyAI)",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class LectureMainView(discord.ui.View):
    """Main view: Record Summary / Preview / Config APIs"""
    
    def __init__(self, guild_id: int, user_id: int, original_interaction: discord.Interaction = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
        self.original_interaction = original_interaction
    
    async def return_to_main(self, interaction: discord.Interaction):
        """Callback to return to main lecture view"""
        embed = discord.Embed(
            title="🎓 Lecture Summary",
            description="Chọn hành động:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="🎬 Record Summary",
            value="Tóm tắt bài giảng từ video (Gemini)",
            inline=False
        )
        embed.add_field(
            name="📄 Preview Slides",
            value="Xem trước nội dung slides trước buổi học",
            inline=True
        )
        embed.add_field(
            name="🔑 Personal Config",
            value="Cấu hình API keys cá nhân (Gemini/AssemblyAI)",
            inline=True
        )
        
        new_view = LectureMainView(self.guild_id, self.user_id, self.original_interaction)
        await interaction.response.edit_message(embed=embed, content=None, view=new_view)
    
    @discord.ui.button(label="🎬 Record Summary", style=discord.ButtonStyle.primary)
    async def record_summary_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open video input modal directly"""
        from .video_views import VideoInputModal
        modal = VideoInputModal(self.guild_id, self.user_id, interaction)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📄 Preview Slides", style=discord.ButtonStyle.success)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Preview slides/documents before class"""
        from .preview_views import PreviewSourceView
        
        embed = discord.Embed(
            title="📄 Preview Tài Liệu",
            description=(
                "Chuẩn bị trước buổi học bằng cách tổng hợp NỘI DUNG CHÍNH từ slides/tài liệu.\n\n"
                "**Chọn cách upload tài liệu:**"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="📤 Upload PDF",
            value="Upload 1-5 file PDF trực tiếp",
            inline=True
        )
        embed.add_field(
            name="🔗 Google Drive",
            value="Paste link Drive (1 hoặc nhiều file)",
            inline=True
        )
        embed.set_footer(text="Có thể upload tối đa 5 tài liệu")
        
        view = PreviewSourceView(
            guild_id=self.guild_id,
            user_id=self.user_id,
            return_callback=self.return_to_main,
        )
        
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="🔑 Gemini API", style=discord.ButtonStyle.secondary)
    async def config_gemini_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open Gemini API config view (multi-key)"""
        from cogs.shared.gemini_config_view import GeminiConfigView
        
        view = GeminiConfigView(self.user_id, return_callback=self.return_to_main)
        embed = view._build_status_embed()
        
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=view
        )
    
    @discord.ui.button(label="🎙️ AssemblyAI API", style=discord.ButtonStyle.secondary)
    async def config_assemblyai_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open AssemblyAI API config view"""
        view = AssemblyAIApiConfigView(self.user_id, return_callback=self.return_to_main)
        
        current_key = config_service.get_user_assemblyai_api(self.user_id)
        if current_key:
            status = f"✅ Đã set: `{mask_key(current_key)}`"
        else:
            status = "❌ Chưa set API key"
        
        await interaction.response.edit_message(
            content=f"**🎙️ AssemblyAI API Config (Cá nhân)**\n\nStatus: {status}\n\n"
                    f"_AssemblyAI dùng để transcribe audio từ video lecture_\n"
                    f"_Free tier: 100 giờ/tháng_",
            embed=None,
            view=view
        )
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", embed=None, view=None)



class AssemblyAIApiConfigView(discord.ui.View):
    """View for managing personal AssemblyAI API key"""
    
    def __init__(self, user_id: int, return_callback=None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.return_callback = return_callback
    
    @discord.ui.button(label="⚙️ Set API", style=discord.ButtonStyle.primary)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to set API key"""
        modal = AssemblyAIApiModal(self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Xóa API", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete saved API key"""
        config_service.set_user_assemblyai_api(self.user_id, "")
        await interaction.response.send_message(
            "✅ Đã xóa AssemblyAI API key",
            ephemeral=True
        )
    
    @discord.ui.button(label="⬅️ Quay lại", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.return_callback:
            await self.return_callback(interaction)
        else:
            await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class AssemblyAIApiModal(discord.ui.Modal, title="Set AssemblyAI API Key"):
    """Modal for entering personal AssemblyAI API key"""
    
    api_key = discord.ui.TextInput(
        label="AssemblyAI API Key",
        placeholder="...",
        required=True,
    )
    
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        key = self.api_key.value.strip()
        
        # Save to user config
        config_service.set_user_assemblyai_api(self.user_id, key)
        
        await interaction.response.send_message(
            f"✅ AssemblyAI API Key đã lưu: `{mask_key(key)}`",
            ephemeral=True
        )


def mask_key(key: str) -> str:
    """Mask API key showing first 3 and last 3 chars"""
    if not key or len(key) < 8:
        return "***"
    return f"{key[:3]}...{key[-3:]}"

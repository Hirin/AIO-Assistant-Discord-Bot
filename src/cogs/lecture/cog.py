"""
Lecture Cog - /lecture command with Video (Gemini) and Transcript (GLM) modes
Per-user Gemini API key management
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging
import os

from services import config as config_service

logger = logging.getLogger(__name__)


class LectureCog(commands.Cog):
    """Lecture summarization commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="lecture", description="Tóm tắt bài giảng từ video hoặc transcript")
    async def lecture(self, interaction: discord.Interaction):
        """Main lecture command - shows Summary or Config options"""
        view = LectureMainView(interaction.guild_id, interaction.user.id)
        
        embed = discord.Embed(
            title="🎓 Lecture Summary",
            description="Chọn hành động:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📝 Summary",
            value="Tóm tắt bài giảng từ video (Gemini) hoặc transcript (GLM)",
            inline=False
        )
        embed.add_field(
            name="🔑 Config Gemini API",
            value="Cấu hình API key Gemini (video summarization)",
            inline=True
        )
        embed.add_field(
            name="🎙️ Config AssemblyAI API",
            value="Cấu hình API key AssemblyAI (transcription)",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class LectureMainView(discord.ui.View):
    """Main view: Summary or Config APIs"""
    
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
    
    @discord.ui.button(label="📝 Summary", style=discord.ButtonStyle.primary)
    async def summary_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open source selection view"""
        from .video_views import LectureSourceView
        view = LectureSourceView(self.guild_id, self.user_id)
        
        await interaction.response.edit_message(
            content="**Chọn nguồn dữ liệu:**",
            embed=None,
            view=view
        )
    
    @discord.ui.button(label="📄 Preview", style=discord.ButtonStyle.success)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Preview slides/documents before class"""
        from .preview_views import PreviewSourceView
        
        # Create embed with instructions
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
        )
        
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="🔑 Gemini API", style=discord.ButtonStyle.secondary)
    async def config_gemini_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open Gemini API config view"""
        view = GeminiApiConfigView(self.user_id)
        
        # Check current API status
        current_key = config_service.get_user_gemini_api(self.user_id)
        if current_key:
            status = f"✅ Đã set: `{mask_key(current_key)}`"
        else:
            status = "❌ Chưa set API key"
        
        await interaction.response.edit_message(
            content=f"**🔑 Gemini API Config (Cá nhân)**\n\nStatus: {status}",
            embed=None,
            view=view
        )
    
    @discord.ui.button(label="🎙️ AssemblyAI API", style=discord.ButtonStyle.secondary)
    async def config_assemblyai_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open AssemblyAI API config view"""
        view = AssemblyAIApiConfigView(self.user_id)
        
        # Check current API status
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



class GeminiApiConfigView(discord.ui.View):
    """View for managing personal Gemini API key"""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
    
    @discord.ui.button(label="🧪 Test API", style=discord.ButtonStyle.success)
    async def test_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Test if API key works"""
        await interaction.response.defer(ephemeral=True)
        
        api_key = config_service.get_user_gemini_api(self.user_id)
        if not api_key:
            await interaction.followup.send("❌ Chưa set API key!", ephemeral=True)
            return
        
        # Test with centralized service
        try:
            from services import gemini
            result = await gemini.test_api(api_key)
            
            await interaction.followup.send(
                f"✅ API hoạt động!\nResponse: {result[:100]}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ API lỗi: {str(e)[:200]}",
                ephemeral=True
            )
    
    @discord.ui.button(label="⚙️ Set API", style=discord.ButtonStyle.primary)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to set API key"""
        modal = GeminiApiModal(self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


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
            f"✅ API Key đã lưu: `{mask_key(key)}`",
            ephemeral=True
        )


class AssemblyAIApiConfigView(discord.ui.View):
    """View for managing personal AssemblyAI API key"""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
    
    @discord.ui.button(label="⚙️ Set API", style=discord.ButtonStyle.primary)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to set API key"""
        modal = AssemblyAIApiModal(self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🗑️ Xóa API", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete saved API key"""
        # Set empty key to effectively delete
        config_service.set_user_assemblyai_api(self.user_id, "")
        await interaction.response.send_message(
            "✅ Đã xóa AssemblyAI API key",
            ephemeral=True
        )
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.secondary)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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


class FirefliesApiModal(discord.ui.Modal, title="Set Fireflies API Key"):
    """Modal for entering personal Fireflies API key"""
    
    api_key = discord.ui.TextInput(
        label="Fireflies API Key",
        placeholder="...",
        required=True,
    )
    
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        key = self.api_key.value.strip()
        
        # Save to user config
        config_service.set_user_fireflies_api(self.user_id, key)
        
        await interaction.response.send_message(
            f"✅ Fireflies API Key đã lưu: `{mask_key(key)}`",
            ephemeral=True
        )


def mask_key(key: str) -> str:
    """Mask API key showing first 3 and last 3 chars"""
    if not key or len(key) < 8:
        return "***"
    return f"{key[:3]}...{key[-3:]}"

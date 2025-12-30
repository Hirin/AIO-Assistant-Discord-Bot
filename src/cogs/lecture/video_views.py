"""
Video Views for Lecture Command
Handles YouTube input, processing progress, and error handling
"""
import discord
import asyncio
import logging
import os
from typing import Optional

from services import gemini, video_download, video, lecture_cache, prompts, latex_utils
from services.video import format_timestamp, cleanup_files
from services.slides import SlidesError
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)

RATE_LIMIT_WAIT = 60  # seconds between API calls


class LectureSourceView(discord.ui.View):
    """View with buttons to select Video or Transcript mode"""
    
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
    
    @discord.ui.button(label="📹 Video (Gemini)", style=discord.ButtonStyle.success)
    async def video_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open video input modal"""
        modal = VideoInputModal(self.guild_id, self.user_id, interaction)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📝 Transcript (GLM)", style=discord.ButtonStyle.primary)
    async def transcript_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Use existing transcript flow from meeting cog"""
        from cogs.meeting.modals import MeetingIdModal
        modal = MeetingIdModal(self.guild_id, mode="lecture")
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📄 Preview Slides", style=discord.ButtonStyle.secondary)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Preview slides/documents before class"""
        from cogs.preview.views import PreviewSourceView
        
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
            value="Upload 1-5 file PDF trực tiếp qua Discord",
            inline=True
        )
        embed.add_field(
            name="🔗 Google Drive",
            value="Paste link Google Drive (1 hoặc nhiều file)",
            inline=True
        )
        embed.set_footer(text="Có thể upload tối đa 5 tài liệu")
        
        view = PreviewSourceView(
            guild_id=self.guild_id,
            user_id=self.user_id,
        )
        
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", embed=None, view=None)


def preprocess_chat_session(raw_text: str) -> str:
    """
    Filter junk from chat session text using robust parsing.
    Logic:
    1. Parse messages (Name, Timestamp, Content)
    2. Clean content (remove reaction lines, Collapse All, headers)
    3. Filter: Keep if has link OR length >= 6 words
    4. Format: JSON string matching user request
    """
    import re
    import json
    
    lines = [line_item.strip() for line_item in raw_text.split('\n')]
    
    # Patterns
    time_pat = re.compile(r'^(\d{1,2}:\d{2}(?::\d{2})?)(?:\s*\(Edited\))?$')
    reaction_count_pat = re.compile(r'^\d+$')
    emoji_pat = re.compile(r'^[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]+$')
    
    # 1. Identify start indices
    msg_starts = []
    i = 0
    while i < len(lines) - 1:
        if time_pat.match(lines[i+1]) and lines[i]: 
            msg_starts.append(i)
            i += 1 
        i += 1
        
    filtered_messages = []
    
    for idx, start_line_idx in enumerate(msg_starts):
        name = lines[start_line_idx]
        timestamp = time_pat.match(lines[start_line_idx+1]).group(1)
        
        start_content = start_line_idx + 2
        end_content = msg_starts[idx+1] if idx + 1 < len(msg_starts) else len(lines)
        
        clean_lines = []
        for line in lines[start_content:end_content]:
            if not line:
                continue
            if line == "Collapse All":
                continue
            if emoji_pat.match(line):
                continue
            if reaction_count_pat.match(line):
                continue
            clean_lines.append(line)
            
        full_content = "\n".join(clean_lines).strip()
        
        if not full_content:
            continue
            
        # Filter Logic: Keep if Link OR >= 6 Words OR >= 3 Lines (code blocks)
        has_link = 'http' in full_content.lower()
        word_count = len(full_content.split())
        line_count = len(clean_lines)
        
        is_junk = (word_count < 6) and (not has_link) and (line_count < 2)
        
        if not is_junk:
            filtered_messages.append({
                "name": name,
                "time": timestamp,
                "content": full_content
            })
            
    # Return as JSON string
    return json.dumps(filtered_messages, ensure_ascii=False, indent=2)


def extract_links_from_chat(chat_text: str) -> list[str]:
    """
    Extract URLs from chat session text, filtering out Kahoot and other gaming links.
    
    Args:
        chat_text: Preprocessed chat session text
        
    Returns:
        List of URLs (already wrapped in <>)
    """
    import re
    
    # Find all URLs
    url_pattern = r'https?://[^\s<>"\'\)]+[^\s<>"\'\)\.\,\;]'
    urls = re.findall(url_pattern, chat_text)
    
    # Filter out unwanted links
    exclude_patterns = [
        r'kahoot\.it',
        r'kahoot\.com',
        r'discord\.com',
        r'discord\.gg',
        r'youtube\.com/live',  # Live stream links often not useful
    ]
    exclude_regex = [re.compile(p, re.IGNORECASE) for p in exclude_patterns]
    
    filtered = []
    seen = set()
    for url in urls:
        # Skip if matches exclude pattern
        if any(p.search(url) for p in exclude_regex):
            continue
        # Skip duplicates
        if url in seen:
            continue
        seen.add(url)
        filtered.append(f"<{url}>")
    
    return filtered


def format_chat_links_for_prompt(links: list[str]) -> str:
    """
    Format chat links for injection into merge prompt.
    
    Args:
        links: List of URLs (already wrapped in <>)
        
    Returns:
        Formatted string for prompt
    """
    if not links:
        return ""
    
    lines = ["**Links từ chat session:**"]
    for url in links:
        lines.append(f"- {url}")
    
    return "\n".join(lines)


class VideoInputModal(discord.ui.Modal, title="Video Lecture Summary"):
    """Modal for entering video URL and title"""
    
    video_url = discord.ui.TextInput(
        label="Video URL",
        placeholder="Google Drive link hoặc direct URL (mp4)...",
        required=True,
    )
    
    lecture_title = discord.ui.TextInput(
        label="Tiêu đề bài giảng",
        placeholder="VD: M07W03 - Transformer",
        required=True,
        max_length=100,
    )
    
    def __init__(self, guild_id: int, user_id: int, parent_interaction: discord.Interaction):
        super().__init__()
        self.guild_id = guild_id
        self.user_id = user_id
        self.parent_interaction = parent_interaction
    
    async def on_submit(self, interaction: discord.Interaction):
        url = self.video_url.value.strip()
        title = self.lecture_title.value.strip()
        
        # Validate URL
        source_type, _ = video_download.validate_video_url(url)
        if source_type == 'invalid':
            await interaction.response.send_message(
                "❌ URL không hợp lệ. Hỗ trợ: Google Drive link hoặc direct video URL (mp4, webm...).",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Prompt for slides (optional) - returns (url, source, original_path)
        slides_url, slides_source, slides_original_path = await prompt_for_slides(
            interaction, interaction.client, self.user_id
        )
        
        # Prompt for chat session .txt file (optional)
        chat_content = await prompt_for_chat_session(
            interaction, interaction.client, self.user_id
        )
        # Use chat content as extra context if provided
        extra_context = chat_content if chat_content else None
        
        # Hide the source selection view
        try:
            await self.parent_interaction.edit_original_response(
                content=f"⏳ Đang xử lý: **{title}** (~25-30 phút)",
                view=None
            )
        except Exception:
            pass  # Ignore if already edited
        
        # Start processing
        processor = VideoLectureProcessor(
            interaction=interaction,
            youtube_url=url,
            title=title,
            slides_url=slides_url,
            slides_source=slides_source,
            slides_original_path=slides_original_path,
            guild_id=self.guild_id,
            user_id=self.user_id,
            extra_context=extra_context or None,
        )
        await processor.process()


class SlidesPromptView(discord.ui.View):
    """View with buttons to choose slides source: Upload, Drive Link, or Skip"""
    
    def __init__(self):
        super().__init__(timeout=None)  # No timeout - user can skip anytime
        self.choice = None  # "upload", "drive", or None
        self.result_interaction = None
    
    @discord.ui.button(label="📤 Upload PDF", style=discord.ButtonStyle.primary)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "upload"
        self.result_interaction = interaction
        await interaction.response.send_message(
            "📎 **Upload file PDF** trong 90s...\n_(Gửi file vào channel này)_",
            ephemeral=True,
        )
        self.stop()
    
    @discord.ui.button(label="🔗 Google Drive", style=discord.ButtonStyle.secondary)
    async def drive_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "drive"
        self.result_interaction = interaction
        # Show modal to enter Drive URL
        modal = SlidesUrlModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.drive_url = modal.slides_url
        self.stop()
    
    @discord.ui.button(label="❌ Bỏ qua", style=discord.ButtonStyle.danger)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = None
        await interaction.response.defer()
        self.stop()


class SlidesUrlModal(discord.ui.Modal, title="Slides PDF URL"):
    """Modal for entering slides PDF Drive URL"""
    
    url_input = discord.ui.TextInput(
        label="Google Drive PDF Link",
        placeholder="https://drive.google.com/file/d/...",
        required=True,
    )
    slides_url = None
    
    async def on_submit(self, interaction: discord.Interaction):
        self.slides_url = self.url_input.value.strip()
        await interaction.response.send_message(
            "✅ Đã nhận link slides",
            ephemeral=True
        )


async def prompt_for_slides(
    interaction: discord.Interaction,
    bot,
    user_id: int,
) -> tuple[str | None, str | None, str | None]:
    """
    Prompt user for optional slides PDF upload.
    
    Returns:
        Tuple of (slides_url, slides_source, original_path)
        - slides_url: Path to downloaded PDF or Drive URL
        - slides_source: "drive" | "upload" | None
        - original_path: Original file path or Drive URL (for footer/re-upload)
    """
    import asyncio
    
    # Send prompt with buttons
    view = SlidesPromptView()
    prompt_msg = await interaction.followup.send(
        "📄 **Có bổ sung slides PDF?**\n"
        "Slides sẽ được minh họa trong summary (3-10 trang quan trọng)",
        view=view,
        ephemeral=True,
    )
    
    # Wait for button click or timeout
    await view.wait()
    
    # Clean up prompt message
    try:
        await prompt_msg.delete()
    except Exception:
        pass
    
    if view.choice is None:
        return None, None, None
    
    if view.choice == "drive":
        # Return Drive URL directly
        drive_url = getattr(view, 'drive_url', None)
        return drive_url, "drive", drive_url
    
    if view.choice == "upload":
        # Wait for file upload with retry on wrong format
        def check(m):
            return (
                m.author.id == user_id
                and m.channel.id == interaction.channel.id
                and m.attachments
            )
        
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                remaining_attempts = max_attempts - attempt
                msg = await bot.wait_for("message", check=check, timeout=60)
                attachment = msg.attachments[0]
                
                # Validate PDF format
                if not attachment.filename.lower().endswith('.pdf'):
                    # Delete user's message
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    
                    file_ext = attachment.filename.split('.')[-1] if '.' in attachment.filename else 'unknown'
                    
                    if remaining_attempts > 1:
                        await interaction.followup.send(
                            f"❌ **Định dạng file không hợp lệ!**\n"
                            f"Bạn upload file `.{file_ext}`, nhưng slides phải là **PDF** (.pdf)\n"
                            f"📎 Vui lòng upload lại file PDF ({remaining_attempts - 1} lần thử còn lại)...",
                            ephemeral=True
                        )
                        continue  # Retry
                    else:
                        await interaction.followup.send(
                            f"❌ **Đã hết lượt thử!** File `.{file_ext}` không hợp lệ.\n"
                            f"Tiếp tục không có slides...",
                            ephemeral=True
                        )
                        return None, None, None
                
                # Valid PDF - download to /tmp
                file_path = f"/tmp/slides_upload_{user_id}_{attachment.filename}"
                file_bytes = await attachment.read()
                
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                
                # Delete user's message
                try:
                    await msg.delete()
                except Exception:
                    pass
                
                await interaction.followup.send(
                    f"✅ Đã nhận slides: {attachment.filename}",
                    ephemeral=True
                )
                
                return file_path, "upload", file_path
                
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    "⏰ Timeout - tiếp tục không có slides",
                    ephemeral=True,
                )
                return None, None, None
            except Exception as e:
                logger.exception("Error uploading slides")
                await interaction.followup.send(
                    f"❌ Lỗi upload: {str(e)[:50]}",
                    ephemeral=True,
                )
                return None, None, None
        
        return None, None, None
    
    return None, None, None


class ChatSessionPromptView(discord.ui.View):
    """View with buttons to choose: Upload chat file or Skip"""
    
    def __init__(self):
        super().__init__(timeout=None)  # No timeout - user can skip anytime
        self.choice = None  # "upload" or None
        self.result_interaction = None
    
    @discord.ui.button(label="📤 Upload Chat (.txt)", style=discord.ButtonStyle.primary)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "upload"
        self.result_interaction = interaction
        await interaction.response.send_message(
            "📎 **Paste chat session vào channel này** (Discord sẽ tự động convert thành .txt)...\n"
            "_(Có 3 phút để upload)_",
            ephemeral=True,
        )
        self.stop()
    
    @discord.ui.button(label="❌ Bỏ qua", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = None
        await interaction.response.defer()
        self.stop()


async def prompt_for_chat_session(
    interaction: discord.Interaction,
    bot,
    user_id: int,
) -> str | None:
    """
    Prompt user for optional chat session .txt file upload.
    
    Returns:
        Chat session content as string, or None if skipped
    """
    import asyncio
    
    # Send prompt with buttons
    view = ChatSessionPromptView()
    prompt_msg = await interaction.followup.send(
        "💬 **Có chat session cần bổ sung?**\n"
        "_(Paste toàn bộ chat vào channel, Discord tự đóng gói thành .txt)_",
        view=view,
        ephemeral=True,
    )
    
    # Wait for button choice
    await view.wait()
    
    # Delete the prompt message
    try:
        await prompt_msg.delete()
    except Exception:
        pass
    
    if view.choice == "upload":
        # Wait for .txt file upload
        def check_txt_upload(message):
            return (
                message.author.id == user_id and 
                message.channel.id == interaction.channel.id and
                message.attachments and 
                any(a.filename.lower().endswith('.txt') for a in message.attachments)
            )
        
        try:
            msg = await bot.wait_for('message', timeout=180.0, check=check_txt_upload)  # 3 minutes
            
            # Find .txt attachment
            txt_attachment = next(a for a in msg.attachments if a.filename.lower().endswith('.txt'))
            
            # Read content
            file_bytes = await txt_attachment.read()
            raw_content = file_bytes.decode('utf-8', errors='ignore')
            
            # Preprocess to filter junk
            chat_content = preprocess_chat_session(raw_content)
            
            # Delete user's message
            try:
                await msg.delete()
            except Exception:
                pass
            
            await interaction.followup.send(
                f"✅ Đã nhận chat session: {txt_attachment.filename}\n"
                f"📊 Raw: {len(raw_content)} chars → Filtered: {len(chat_content)} chars",
                ephemeral=True
            )
            
            return chat_content
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏰ Hết thời gian chờ upload chat session. Tiếp tục không có chat...",
                ephemeral=True
            )
            return None
    
    return None

class VideoErrorView(discord.ui.View):
    """View with Retry / Change API Key / Close buttons for errors"""
    
    def __init__(self, processor: "VideoLectureProcessor"):
        super().__init__(timeout=600)
        self.processor = processor
    
    @discord.ui.button(label="🔄 Retry", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🔄 Đang retry...", view=self)
        await self.processor.process(retry=True)
    
    @discord.ui.button(label="🔑 Gemini API", style=discord.ButtonStyle.secondary)
    async def change_gemini_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GeminiApiKeyModal(self.processor)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="🎙️ AssemblyAI API", style=discord.ButtonStyle.secondary)
    async def change_assemblyai_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AssemblyAIApiKeyModal(self.processor.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Cleanup any temp files
        self.processor.cleanup()
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class SlidesErrorView(discord.ui.View):
    """View for handling slides processing errors - Continue/Retry/NewLink/Cancel"""
    
    def __init__(self, processor: "VideoLectureProcessor", error_msg: str):
        super().__init__(timeout=300)
        self.processor = processor
        self.error_msg = error_msg
        self.choice = None  # "continue", "retry", "new_link", or "cancel"
        self.new_slides_url = None
    
    @discord.ui.button(label="▶️ Tiếp tục không có slides", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="▶️ Tiếp tục xử lý không có slides...",
            view=self
        )
        self.choice = "continue"
        self.stop()
    
    @discord.ui.button(label="🔄 Thử lại", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 Đang thử lại download slides...",
            view=self
        )
        self.choice = "retry"
        self.stop()
    
    @discord.ui.button(label="📎 Gửi link mới", style=discord.ButtonStyle.secondary)
    async def new_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show modal to get new slides URL
        modal = NewSlidesUrlModal(self)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ Hủy", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.processor.cleanup()
        await interaction.response.edit_message(content="❌ Đã hủy", view=None)
        self.choice = "cancel"
        self.stop()


class NewSlidesUrlModal(discord.ui.Modal, title="Gửi lại link slides"):
    """Modal for entering new slides URL"""
    
    slides_url = discord.ui.TextInput(
        label="Link slides mới (Google Drive hoặc URL)",
        placeholder="https://drive.google.com/file/d/...",
        required=True,
        max_length=500
    )
    
    def __init__(self, parent_view: SlidesErrorView):
        super().__init__()
        self.parent_view = parent_view
    
    async def on_submit(self, interaction: discord.Interaction):
        for item in self.parent_view.children:
            item.disabled = True
        
        self.parent_view.new_slides_url = self.slides_url.value
        self.parent_view.choice = "new_link"
        
        await interaction.response.edit_message(
            content="📎 Đang tải slides từ link mới...",
            view=self.parent_view
        )
        self.parent_view.stop()

class GeminiApiKeyModal(discord.ui.Modal, title="Đổi Gemini API Key"):
    """Modal for entering new Gemini API key (saves to user config)"""
    
    api_key = discord.ui.TextInput(
        label="Gemini API Key",
        placeholder="AIza...",
        required=True,
    )
    
    def __init__(self, processor: "VideoLectureProcessor"):
        super().__init__()
        self.processor = processor
    
    async def on_submit(self, interaction: discord.Interaction):
        from services import config as config_service
        
        new_key = self.api_key.value.strip()
        
        # Save to user config (per-user)
        config_service.set_user_gemini_api(self.processor.user_id, new_key)
        
        await interaction.response.send_message(
            "✅ Gemini API Key đã lưu. Bạn có thể nhấn Retry.",
            ephemeral=True
        )


class AssemblyAIApiKeyModal(discord.ui.Modal, title="Đổi AssemblyAI API Key"):
    """Modal for entering new AssemblyAI API key (saves to user config)"""
    
    api_key = discord.ui.TextInput(
        label="AssemblyAI API Key",
        placeholder="...",
        required=True,
    )
    
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        from services import config as config_service
        
        new_key = self.api_key.value.strip()
        
        # Save to user config (per-user)
        config_service.set_user_assemblyai_api(self.user_id, new_key)
        
        await interaction.response.send_message(
            "✅ AssemblyAI API Key đã lưu.",
            ephemeral=True
        )


class VideoLectureProcessor:
    """Handles the full video processing pipeline"""
    
    def __init__(
        self,
        interaction: discord.Interaction,
        youtube_url: str,
        title: str,
        guild_id: int,
        user_id: int,
        slides_url: Optional[str] = None,
        slides_source: Optional[str] = None,  # "drive" | "upload" | None
        slides_original_path: Optional[str] = None,  # Original path or Drive URL
        extra_context: Optional[str] = None,  # User-provided notes, Q&A, special requests
    ):
        self.interaction = interaction
        self.youtube_url = youtube_url
        self.title = title
        self.guild_id = guild_id
        self.user_id = user_id
        self.slides_url = slides_url
        self.slides_source = slides_source
        self.slides_original_path = slides_original_path
        self.extra_context = extra_context
        self.status_msg: Optional[discord.WebhookMessage] = None
        self.temp_files: list[str] = []
        self.video_path: Optional[str] = None
        self.slide_images: list[str] = []  # For PDF slides
        self.transcript: Optional[str] = None  # For AssemblyAI transcript
        # Generate cache ID based on video URL, slides URL, and user ID
        self.cache_id = lecture_cache.generate_pipeline_id(youtube_url, slides_url, user_id)
    
    async def update_status(self, message: str):
        """Update the status message"""
        try:
            if self.status_msg:
                await self.status_msg.edit(content=message)
            else:
                self.status_msg = await self.interaction.followup.send(
                    message, ephemeral=True, wait=True
                )
        except Exception as e:
            logger.warning(f"Failed to update status: {e}")
    
    def cleanup(self):
        """Clean up temporary files"""
        cleanup_files(self.temp_files)
        self.temp_files = []
    
    async def process(self, retry: bool = False):
        """Main processing pipeline with parallel AssemblyAI + video split + PDF"""
        from services import queue
        from services import config as config_service
        from services import slides as slides_service
        
        try:
            # Check queue and wait if needed
            queue_len = queue.get_queue_length()
            if queue_len > 0:
                await self.update_status(f"⏳ Đang chờ trong hàng đợi (vị trí {queue_len + 1})...")
            
            await queue.acquire_video_slot()
            
            # Load user's API keys
            user_gemini_key = config_service.get_user_gemini_api(self.user_id)
            user_assemblyai_key = config_service.get_user_assemblyai_api(self.user_id)
            
            if user_gemini_key:
                logger.info(f"Using custom Gemini API key for user {self.user_id}")
            
            # Check for cached data from previous attempt
            cached_parts = lecture_cache.get_cached_parts(self.cache_id)
            if cached_parts and not retry:
                logger.info(f"Found {len(cached_parts)} cached parts for {self.cache_id}")
            
            # =============================================
            # STAGE 1: Download video (with cache)
            # =============================================
            video_stage = lecture_cache.get_stage(self.cache_id, "video")
            
            if video_stage and os.path.exists(video_stage.get("path", "")):
                # Use cached video
                video_path = video_stage["path"]
                info_data = video_stage.get("info", {})
                
                # Recreate VideoInfo from cache
                from dataclasses import dataclass
                @dataclass
                class CachedVideoInfo:
                    duration: float
                    size_bytes: int
                info = CachedVideoInfo(
                    duration=info_data.get("duration", 0),
                    size_bytes=info_data.get("size_bytes", 0)
                )
                num_parts = video.calculate_num_parts(info.size_bytes, info.duration)
                
                await self.update_status(f"✅ Video từ cache ({format_timestamp(info.duration)})")
                logger.info(f"Using cached video: {video_path}")
            else:
                # Download video
                await self.update_status("⏳ Đang tải video...")
                video_path = f"/tmp/lecture_{self.cache_id}.mp4"
                
                video_path = await video_download.download_video(
                    self.youtube_url, video_path
                )
                
                # Get video info and cache
                info = await video.get_video_info(video_path)
                num_parts = video.calculate_num_parts(info.size_bytes, info.duration)
                
                # Save to cache
                lecture_cache.save_stage(self.cache_id, "video", {
                    "path": video_path,
                    "info": {"duration": info.duration, "size_bytes": info.size_bytes}
                }, config={
                    "video_url": self.youtube_url,
                    "slides_url": self.slides_url,
                    "user_id": self.user_id,
                    "title": self.title
                })
                
                await self.update_status(
                    f"⏳ Video: {format_timestamp(info.duration)} ({info.size_bytes // 1024 // 1024}MB) → {num_parts} phần"
                )
            
            self.video_path = video_path
            self.temp_files.append(video_path)
            
            # =============================================
            # STAGE 2: Parallel prep (AssemblyAI + Split + PDF)
            # =============================================
            assemblyai_task = None
            transcript = None
            
            # Check persistent transcript storage first (keyed by video_url hash)
            # This is independent of slides/prompt changes
            import hashlib
            from services import transcript_storage
            
            user_assemblyai_key = config_service.get_user_assemblyai_api(self.interaction.user.id)
            guild_id = self.interaction.guild_id
            
            # Generate transcript_id based on video_url (not slides/prompt)
            video_hash = hashlib.md5(self.youtube_url.encode()).hexdigest()[:12]
            aai_transcript_id = f"v_{video_hash}"
            
            # Try to get from persistent storage first
            stored_entry = transcript_storage.get_transcript(guild_id, aai_transcript_id, platform="aai")
            
            if stored_entry and stored_entry.get("backup_url"):
                # Fetch transcript from Discord backup
                await self.update_status("⏳ Đang tải transcript từ backup...")
                try:
                    from services import assemblyai_transcript
                    backup_data = await transcript_storage.fetch_transcript_data(stored_entry["backup_url"])
                    if backup_data:
                        transcript = assemblyai_transcript.Transcript.from_dict({
                            "id": aai_transcript_id,
                            "title": stored_entry.get("title", self.title),
                            "duration": stored_entry.get("duration", 0),
                            "paragraphs": backup_data
                        })
                        self.transcript = transcript.to_text()
                        await self.update_status(f"✅ Transcript từ backup ({len(transcript.paragraphs)} paragraphs)")
                        logger.info(f"Using stored transcript: {aai_transcript_id}")
                except Exception as e:
                    logger.warning(f"Failed to fetch backup transcript: {e}")
                    stored_entry = None  # Will check lecture_cache or re-transcribe
            
            # Fallback: check old lecture_cache (backward compat)
            if not transcript and user_assemblyai_key:
                aai_key_hash = hashlib.md5(user_assemblyai_key.encode()).hexdigest()[:8]
                transcript_stage_name = f"transcript_{aai_key_hash}"
                transcript_stage = lecture_cache.get_stage(self.cache_id, transcript_stage_name)
                if transcript_stage and transcript_stage.get("data"):
                    from services import assemblyai_transcript
                    transcript = assemblyai_transcript.Transcript.from_dict(transcript_stage["data"])
                    self.transcript = transcript.to_text()
                    await self.update_status(f"✅ Transcript từ cache ({len(transcript.paragraphs)} paragraphs)")
                    logger.info(f"Using lecture_cache transcript: {len(transcript.paragraphs)} paragraphs")
            
            if not transcript and user_assemblyai_key:
                # Start AssemblyAI transcription (runs in background)
                await self.update_status("⏳ Đang upload video và transcribe (~6 phút)...")
                try:
                    from services import assemblyai_transcript
                    async def transcribe_assemblyai():
                        result = await assemblyai_transcript.transcribe_file(
                            video_path, user_assemblyai_key, self.title,
                            cache_id=self.cache_id  # Enable upload_url caching for resume
                        )
                        
                        # Save to persistent storage + Discord archive
                        # Convert paragraphs to serializable dicts
                        paragraphs_data = result.to_dict()["paragraphs"]
                        entry, is_new = transcript_storage.save_transcript(
                            guild_id=guild_id,
                            transcript_id=aai_transcript_id,
                            title=self.title,
                            platform="aai",
                            transcript_data=paragraphs_data,  # Will be uploaded to Discord
                            video_url=self.youtube_url,
                            duration=result.duration,
                        )
                        
                        if is_new:
                            # Upload full transcript to Discord archive
                            await transcript_storage.upload_to_discord(
                                self.interaction.client, guild_id, entry
                            )
                            logger.info(f"Saved new AAI transcript: {aai_transcript_id}")
                        
                        return result
                    assemblyai_task = asyncio.create_task(transcribe_assemblyai())
                    
                except Exception as e:
                    logger.warning(f"AssemblyAI transcription failed: {e}, continuing without transcript")
                    assemblyai_task = None
            else:
                logger.info("No AssemblyAI API key, skipping transcription")
            
            # === Run slides + video split in PARALLEL while transcript uploads ===
            async def process_slides_inner():
                """Process slides (download + convert to images), raises SlidesError on failure"""
                slides_stage = lecture_cache.get_stage(self.cache_id, "slides")
                if slides_stage and slides_stage.get("images"):
                    cached_images = slides_stage["images"]
                    if all(os.path.exists(img) for img in cached_images):
                        self.slide_images = cached_images
                        logger.info(f"Using cached slides: {len(self.slide_images)} images")
                        return
                
                if not self.slides_url:
                    return
                
                # Try to download and convert (raises exception on failure)
                if self.slides_url.startswith('/tmp/') and os.path.exists(self.slides_url):
                    pdf_path = self.slides_url
                    self.temp_files.append(pdf_path)
                else:
                    pdf_path = f"/tmp/slides_{self.cache_id}.pdf"
                    await video_download.download_video(self.slides_url, pdf_path)
                    self.temp_files.append(pdf_path)
                
                self.slide_images = slides_service.pdf_to_images(pdf_path)
                logger.info(f"Converted {len(self.slide_images)} slide pages")
                
                lecture_cache.save_stage(self.cache_id, "slides", {
                    "images": self.slide_images
                })
            
            async def process_slides_with_retry():
                """Process slides with user interaction on failure"""
                if not self.slides_url:
                    return  # No slides to process
                
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        await process_slides_inner()
                        return  # Success
                    except SlidesError as e:
                        # Clear error from slides processing - show to user directly
                        error_msg = str(e)
                        logger.warning(f"Slides processing failed (attempt {attempt + 1}): {e}")
                    except Exception as e:
                        error_msg = f"Lỗi slides: {str(e)[:150]}"
                        logger.warning(f"Slides processing failed (attempt {attempt + 1}): {e}")
                    
                    # Show error view and wait for user choice
                    view = SlidesErrorView(self, error_msg)
                    try:
                        if self.status_msg:
                            await self.status_msg.edit(
                                content=f"❌ {error_msg}",
                                view=view
                            )
                        else:
                            self.status_msg = await self.interaction.followup.send(
                                f"❌ {error_msg}",
                                view=view,
                                ephemeral=True,
                                wait=True
                            )
                    except Exception:
                        # Fallback - continue without slides
                        logger.warning("Could not show slides error view, continuing without slides")
                        self.slide_images = []
                        return
                    
                    # Wait for user choice
                    await view.wait()
                    
                    if view.choice == "continue":
                        self.slide_images = []
                        return
                    elif view.choice == "retry":
                        continue  # Retry loop
                    elif view.choice == "new_link":
                        # Update slides URL and retry
                        self.slides_url = view.new_slides_url
                        # Clear any cached slides for this new URL
                        lecture_cache.clear_stage(self.cache_id, "slides")
                        continue  # Retry with new URL
                    else:  # cancel or timeout
                        raise Exception("User cancelled slides processing")
                
                # Fallback if all retries exhausted
                self.slide_images = []

            async def split_video_task():
                """Split video into parts"""
                nonlocal parts
                segments_stage = lecture_cache.get_stage(self.cache_id, "segments")
                if segments_stage and segments_stage.get("parts"):
                    cached_parts = segments_stage["parts"]
                    if all(os.path.exists(p["path"]) for p in cached_parts):
                        parts = cached_parts
                        logger.info(f"Using cached segments: {len(parts)} parts")
                        return
                
                if num_parts > 1:
                    parts = await video.split_video(video_path, num_parts)
                    self.temp_files.extend([p["path"] for p in parts])
                else:
                    parts = [{
                        "path": video_path,
                        "start_seconds": 0,
                        "duration": info.duration,
                    }]
                
                lecture_cache.save_stage(self.cache_id, "segments", {
                    "parts": parts
                })
                logger.info(f"Split video into {len(parts)} parts")
            
            # Initialize parts before parallel execution
            parts = []
            
            # Run slides + split in parallel
            await self.update_status("⏳ Đang xử lý slides và tách video song song...")
            await asyncio.gather(
                process_slides_with_retry(),
                split_video_task()
            )
            
            # Wait for AssemblyAI transcript if started
            if assemblyai_task:
                await self.update_status("⏳ Đang chờ AssemblyAI transcript...")
                try:
                    transcript = await assemblyai_task
                    self.transcript = transcript.to_text()
                    logger.info(f"Got transcript: {len(transcript.paragraphs)} paragraphs")
                except Exception as e:
                    logger.warning(f"Failed to get AssemblyAI transcript: {e}")
                    transcript = None
            
            # Build time ranges for transcript splitting
            time_ranges = [(p["start_seconds"], p["start_seconds"] + p["duration"]) for p in parts]
            logger.info(f"Time ranges for transcript split: {time_ranges}")
            transcript_segments = []
            if transcript:
                from services import assemblyai_transcript
                transcript_segments = assemblyai_transcript.split_transcript_by_time(transcript, time_ranges)
                for i, seg in enumerate(transcript_segments):
                    logger.info(f"Transcript segment {i+1}: {len(seg)} chars")
            else:
                # No transcript - use empty segments
                transcript_segments = ["" for _ in parts]
                logger.info("No transcript available for splitting")
            
            # =============================================
            # STAGE 3: Process each part (video + transcript)
            # =============================================
            summaries = []
            for i, part in enumerate(parts, 1):
                part_num = i
                transcript_segment = transcript_segments[i - 1] if transcript_segments else ""
                
                # Check cache
                if part_num in cached_parts:
                    logger.info(f"Using cached summary for part {part_num}")
                    summaries.append(cached_parts[part_num]["summary"])
                    cleanup_files([part["path"]])
                    continue
                
                await self.update_status(
                    f"⏳ Đang xử lý phần {part_num}/{len(parts)} "
                    f"({format_timestamp(part['start_seconds'])} - {format_timestamp(part['start_seconds'] + part['duration'])})"
                )
                
                # Upload to Gemini
                gemini_file = await gemini.upload_video(part["path"], api_key=user_gemini_key)
                
                try:
                    # Build prompt with transcript segment
                    if part_num == 1:
                        prompt = prompts.GEMINI_LECTURE_PROMPT_PART1.format(
                            transcript_segment=transcript_segment if transcript_segment else "(Không có transcript)"
                        )
                    else:
                        context = self._condense_summaries(summaries)
                        start_seconds = int(part["start_seconds"])
                        prompt = prompts.GEMINI_LECTURE_PROMPT_PART_N.format(
                            start_time=start_seconds,
                            transcript_segment=transcript_segment if transcript_segment else "(Không có transcript)",
                            previous_context=context,
                        )
                    
                    summary = await gemini.generate_lecture_summary(
                        gemini_file, prompt, guild_id=self.guild_id, api_key=user_gemini_key
                    )
                    
                    # Cache the summary
                    lecture_cache.save_part_summary(
                        self.cache_id, part_num, summary, part["start_seconds"]
                    )
                    summaries.append(summary)
                    
                    # Delete part video after successful processing
                    cleanup_files([part["path"]])
                    if part["path"] in self.temp_files:
                        self.temp_files.remove(part["path"])
                    
                finally:
                    gemini.cleanup_file(gemini_file, api_key=user_gemini_key)
                
                # Wait between parts to avoid rate limit
                if part_num < len(parts):
                    await self.update_status(f"⏳ Chờ {RATE_LIMIT_WAIT}s để tránh rate limit...")
                    await asyncio.sleep(RATE_LIMIT_WAIT)
            
            # =============================================
            # STAGE 4: Merge summaries with slides + transcript
            # =============================================
            # Check cache first
            merge_cache = lecture_cache.get_stage(self.cache_id, "merge")
            if merge_cache and merge_cache.get("result"):
                final_summary = merge_cache["result"]
                await self.update_status("✅ Merge summary từ cache")
                logger.info("Using cached merge summary")
            elif len(summaries) > 1:
                await self.update_status("⏳ Đang tổng hợp các phần...")
                await asyncio.sleep(RATE_LIMIT_WAIT)
                
                # Extract links from chat session for References section
                chat_links_str = ""
                if self.extra_context:
                    chat_links = extract_links_from_chat(self.extra_context)
                    if chat_links:
                        chat_links_str = format_chat_links_for_prompt(chat_links)
                        logger.info(f"Extracted {len(chat_links)} links from chat session")
                
                final_summary = await gemini.merge_summaries(
                    summaries, 
                    prompts.GEMINI_MERGE_PROMPT,
                    full_transcript=self.transcript or "",
                    extra_context=self.extra_context or "",
                    chat_links=chat_links_str,
                    api_key=user_gemini_key
                )
                
                # Save to cache
                lecture_cache.save_stage(self.cache_id, "merge", {
                    "result": final_summary
                })
                logger.info("Saved merge summary to cache")
            else:
                final_summary = summaries[0]
            
            # =============================================
            # STAGE 4.5: Slide Matching (if slides exist)
            # =============================================
            if self.slide_images and user_gemini_key:
                # Check cache first
                slide_match_cache = lecture_cache.get_stage(self.cache_id, "slide_match")
                if slide_match_cache and slide_match_cache.get("result"):
                    final_summary = slide_match_cache["result"]
                    await self.update_status("✅ Slide matching từ cache")
                    logger.info("Using cached slide matching result")
                else:
                    await self.update_status("⏳ Đang chèn slides vào nội dung...")
                    try:
                        import base64
                        from services import slides as slides_service
                        
                        # Extract links from PDF for References section
                        pdf_links_str = ""
                        if self.pdf_path:
                            pdf_links = slides_service.extract_links_from_pdf(self.pdf_path)
                            if pdf_links:
                                pdf_links_str = slides_service.format_pdf_links_for_prompt(pdf_links)
                                logger.info(f"Extracted {len(pdf_links)} links from PDF")
                        
                        # Load slide images as base64
                        slide_images_b64 = []
                        for path in self.slide_images:
                            with open(path, 'rb') as f:
                                slide_images_b64.append(base64.b64encode(f.read()).decode())
                        
                        # Call Gemini VLM for slide matching with PDF links
                        matched_summary = await gemini.match_slides_to_summary(
                            final_summary,
                            slide_images_b64,
                            pdf_links=pdf_links_str,
                            api_key=user_gemini_key
                        )
                        
                        # Save to cache
                        lecture_cache.save_stage(self.cache_id, "slide_match", {
                            "result": matched_summary
                        })
                        final_summary = matched_summary
                        logger.info(f"Slide matching completed, matched to {len(self.slide_images)} slides")
                    except Exception as e:
                        logger.warning(f"Slide matching failed: {e}, using summary without slides")
            
            # Post-process: Format timestamps (no need to wrap URLs - model already does it)
            # 1. Format TOC entries: [-"TOPIC"- | -SECONDS-] -> [MM:SS - TOPIC](url)
            final_summary = gemini.format_toc_hyperlinks(final_summary, self.youtube_url)
            # 2. Format inline timestamps: [-SECONDSs-] -> [[MM:SS]](url)
            final_summary = gemini.format_video_timestamps(final_summary, self.youtube_url)
            
            # STAGE 5: Send to channel with slides
            # =============================================
            # Process LaTeX formulas:
            # - $$...$$ (block): Render to images
            # - $...$ (inline): Convert to Unicode
            final_summary, latex_images = latex_utils.process_latex_formulas(final_summary)
            
            header = f"🎓 **{self.title}**\n🔗 <{self.youtube_url}>\n\n"
            
            # Helper to send LaTeX images embedded in text
            async def send_with_latex_images(channel, text: str, latex_imgs: list):
                """Send text with embedded LaTeX images"""
                if not latex_imgs:
                    await send_chunked(channel, text)
                    return
                
                # Split text by LaTeX placeholders and send with images
                remaining_text = text
                for placeholder, img_path in latex_imgs:
                    if placeholder in remaining_text:
                        parts = remaining_text.split(placeholder, 1)
                        if parts[0].strip():
                            await send_chunked(channel, parts[0])
                        
                        # Send the LaTeX image
                        try:
                            file = discord.File(img_path, filename="formula.png")
                            await channel.send(file=file)
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            logger.warning(f"Failed to send LaTeX image: {e}")
                        
                        remaining_text = parts[1] if len(parts) > 1 else ""
                
                if remaining_text.strip():
                    await send_chunked(channel, remaining_text)
                
                # Cleanup LaTeX images
                for _, img_path in latex_imgs:
                    try:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    except Exception:
                        pass
            
            # Check if we have slides to embed
            if self.slide_images:
                # Parse pages and send with slide images
                from utils.discord_utils import send_chunked_with_pages
                parsed_parts = gemini.parse_pages_and_text(header + final_summary)
                
                has_pages = any(part[1] is not None for part in parsed_parts)
                logger.info(f"Parsed {len(parsed_parts)} parts, has_pages={has_pages}")
                
                if has_pages:
                    await send_chunked_with_pages(
                        self.interaction.channel, parsed_parts, self.slide_images, latex_images
                    )
                else:
                    # No page markers, send text only (with LaTeX images if any)
                    await send_with_latex_images(self.interaction.channel, header + final_summary, latex_images)
                
                # Cleanup slide images
                slides_service.cleanup_slide_images(self.slide_images)
            else:
                # No slides - strip any PAGE markers that may have been generated
                final_summary = gemini.strip_page_markers(final_summary)
                
                # Check for frames (legacy behavior)
                parsed_parts = gemini.parse_frames_and_text(header + final_summary)
                has_frames = any(frame_sec is not None for _, frame_sec in parsed_parts)
                
                if has_frames and self.video_path and os.path.exists(self.video_path):
                    from utils.discord_utils import send_chunked_with_frames
                    frame_paths = await send_chunked_with_frames(
                        self.interaction.channel, parsed_parts, self.video_path
                    )
                    cleanup_files(frame_paths)
                else:
                    # Send with LaTeX images if any
                    await send_with_latex_images(self.interaction.channel, header + final_summary, latex_images)
            # =============================================
            # STAGE 6: Send slides footer/attachment
            # =============================================
            if self.slides_source == "drive" and self.slides_original_path:
                # Drive link - append footer with link
                await self.interaction.channel.send(
                    f"📄 **Slides:** <{self.slides_original_path}>"
                )
            elif self.slides_source == "upload" and self.slides_original_path:
                # Upload - re-send the file
                if os.path.exists(self.slides_original_path):
                    try:
                        filename = os.path.basename(self.slides_original_path)
                        file = discord.File(self.slides_original_path, filename=filename)
                        await self.interaction.channel.send(
                            "📄 **Slides:**",
                            file=file
                        )
                    except Exception as e:
                        logger.warning(f"Failed to re-upload slides: {e}")
            
            # Cleanup cache and temp files
            lecture_cache.clear_pipeline_cache(self.cache_id)
            self.cleanup()
            
            await self.update_status("✅ Hoàn thành! Summary đã được gửi lên channel.")
            
        except Exception as e:
            logger.exception("Error in video lecture processing")
            
            # Show error with retry buttons
            error_view = VideoErrorView(self)
            error_msg = f"❌ Lỗi: {str(e)[:200]}"
            
            try:
                if self.status_msg:
                    await self.status_msg.edit(content=error_msg, view=error_view)
                else:
                    await self.interaction.followup.send(
                        error_msg, view=error_view, ephemeral=True
                    )
            except Exception as send_err:
                logger.warning(f"Failed to send error via interaction: {send_err}")
                # Try sending to channel directly as fallback
                try:
                    await self.interaction.channel.send(
                        f"{error_msg}\n\n_(Không thể hiển thị nút retry do session timeout)_"
                    )
                except Exception as channel_err:
                    logger.error(f"Failed to send error to channel: {channel_err}")
        
        finally:
            # Always release queue slot
            queue.release_video_slot()
    
    def _condense_summaries(self, summaries: list[str], max_chars: int = 2000) -> str:
        """Condense summaries for context in next part"""
        lines = []
        for summary in summaries:
            for line in summary.split('\n'):
                if line.startswith('## ') or line.startswith('- **'):
                    lines.append(line)
                    if len('\n'.join(lines)) > max_chars:
                        return '\n'.join(lines)
        return '\n'.join(lines)

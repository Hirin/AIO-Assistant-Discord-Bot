"""
Video Views for Lecture Command
Handles YouTube input, processing progress, and error handling
"""
import discord
import asyncio
import logging
import os
from typing import Optional

from services import gemini, video_download, video, lecture_cache, prompts
from services.video import format_timestamp, cleanup_files
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)

RATE_LIMIT_WAIT = 60  # seconds between API calls


class SlidesError(Exception):
    """Raised when slides processing fails"""
    pass


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
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", embed=None, view=None)


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
        
        # Prompt for slides (optional)
        slides_url = await prompt_for_slides(interaction, interaction.client, self.user_id)
        
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
            guild_id=self.guild_id,
            user_id=self.user_id,
        )
        await processor.process()


class SlidesPromptView(discord.ui.View):
    """View with buttons to choose slides source: Upload, Drive Link, or Skip"""
    
    def __init__(self):
        super().__init__(timeout=60)
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
            f"✅ Đã nhận link slides",
            ephemeral=True
        )


async def prompt_for_slides(
    interaction: discord.Interaction,
    bot,
    user_id: int,
) -> str | None:
    """
    Prompt user for optional slides PDF upload.
    
    Returns:
        Path to downloaded PDF or None
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
        return None
    
    if view.choice == "drive":
        # Return Drive URL directly
        return getattr(view, 'drive_url', None)
    
    if view.choice == "upload":
        # Wait for file upload
        def check(m):
            return (
                m.author.id == user_id
                and m.channel.id == interaction.channel.id
                and m.attachments
                and any(a.filename.lower().endswith('.pdf') for a in m.attachments)
            )
        
        try:
            msg = await bot.wait_for("message", check=check, timeout=90)
            attachment = msg.attachments[0]
            
            # Download file to /tmp
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
            
            return file_path
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏰ Timeout - tiếp tục không có slides",
                ephemeral=True,
            )
            return None
        except Exception as e:
            logger.exception("Error uploading slides")
            await interaction.followup.send(
                f"❌ Lỗi upload: {str(e)[:50]}",
                ephemeral=True,
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
    """View for handling slides processing errors - Continue/Retry/Cancel"""
    
    def __init__(self, processor: "VideoLectureProcessor", error_msg: str):
        super().__init__(timeout=300)
        self.processor = processor
        self.error_msg = error_msg
        self.choice = None  # "continue", "retry", or "cancel"
    
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
    
    @discord.ui.button(label="🔄 Thử lại slides", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 Đang thử lại download slides...",
            view=self
        )
        self.choice = "retry"
        self.stop()
    
    @discord.ui.button(label="❌ Hủy", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.processor.cleanup()
        await interaction.response.edit_message(content="❌ Đã hủy", view=None)
        self.choice = "cancel"
        self.stop()

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
    ):
        self.interaction = interaction
        self.youtube_url = youtube_url
        self.title = title
        self.guild_id = guild_id
        self.user_id = user_id
        self.slides_url = slides_url
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
            
            # Check transcript cache first
            transcript_stage = lecture_cache.get_stage(self.cache_id, "transcript")
            if transcript_stage and transcript_stage.get("data"):
                # Use cached transcript
                from services import assemblyai_transcript
                transcript = assemblyai_transcript.Transcript.from_dict(transcript_stage["data"])
                self.transcript = transcript.to_text()
                await self.update_status(f"✅ Transcript từ cache ({len(transcript.paragraphs)} paragraphs)")
                logger.info(f"Using cached transcript: {len(transcript.paragraphs)} paragraphs")
            elif user_assemblyai_key:
                # Start AssemblyAI transcription (runs in background)
                await self.update_status("⏳ Đang upload video và transcribe (~6 phút)...")
                try:
                    from services import assemblyai_transcript
                    async def transcribe_assemblyai():
                        result = await assemblyai_transcript.transcribe_file(
                            video_path, user_assemblyai_key, self.title,
                            cache_id=self.cache_id  # Enable upload_url caching
                        )
                        # Save to cache immediately after completion
                        lecture_cache.save_stage(self.cache_id, "transcript", {
                            "data": result.to_dict()
                        })
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
                    except Exception as e:
                        error_msg = f"Lỗi slides: {str(e)[:100]}"
                        logger.warning(f"Slides processing failed (attempt {attempt + 1}): {e}")
                        
                        if attempt >= max_retries - 1:
                            # Max retries reached - ask user
                            error_msg += f" (đã thử {max_retries} lần)"
                        
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
            if len(summaries) > 1:
                await self.update_status("⏳ Đang tổng hợp các phần...")
                await asyncio.sleep(RATE_LIMIT_WAIT)
                
                final_summary = await gemini.merge_summaries(
                    summaries, 
                    prompts.GEMINI_MERGE_PROMPT,
                    slide_count=len(self.slide_images),
                    full_transcript=self.transcript or "",
                    api_key=user_gemini_key
                )
            else:
                final_summary = summaries[0]
            
            # Post-process: Convert timestamps to clickable links
            # 1. Format TOC entries: [-"TOPIC"- | -SECONDS-] -> [MM:SS - TOPIC](url)
            final_summary = gemini.format_toc_hyperlinks(final_summary, self.youtube_url)
            # 2. Format inline timestamps: [-SECONDSs-] -> [[MM:SS]](url)
            final_summary = gemini.format_video_timestamps(final_summary, self.youtube_url)
            
            # =============================================
            # STAGE 5: Send to channel with slides
            # =============================================
            header = f"🎓 **{self.title}**\n🔗 <{self.youtube_url}>\n\n"
            
            # Check if we have slides to embed
            if self.slide_images:
                # Parse pages and send with slide images
                from utils.discord_utils import send_chunked_with_pages
                parsed_parts = gemini.parse_pages_and_text(header + final_summary)
                
                has_pages = any(page_num is not None for _, page_num in parsed_parts)
                logger.info(f"Parsed {len(parsed_parts)} parts, has_pages={has_pages}")
                
                if has_pages:
                    await send_chunked_with_pages(
                        self.interaction.channel, parsed_parts, self.slide_images
                    )
                else:
                    # No page markers, send text only
                    await send_chunked(self.interaction.channel, header + final_summary)
                
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
                    await send_chunked(self.interaction.channel, header + final_summary)
            
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

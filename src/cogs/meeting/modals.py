"""
Meeting Modals - UI modals for meeting actions
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import discord

from services import fireflies, fireflies_api, llm, scheduler, transcript_storage, latex_utils, slides as slides_service
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)


async def _send_with_latex_images(channel, text: str, latex_imgs: list):
    """Send text with embedded LaTeX images for meeting summaries"""
    if not latex_imgs:
        await send_chunked(channel, text)
        return
    
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

class ModeSelectionView(discord.ui.View):
    """View with buttons to select Meeting or Lecture mode"""
    
    def __init__(self):
        super().__init__(timeout=60)  # 60 seconds timeout
        self.selected_mode = "meeting"  # Default to meeting mode
        
    @discord.ui.button(label="📋 Meeting", style=discord.ButtonStyle.primary, custom_id="mode_meeting")
    async def meeting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_mode = "meeting"
        await interaction.response.send_message(
            "✅ Đã chọn: **Meeting** mode (tóm tắt cuộc họp)", 
            ephemeral=True
        )
        self.stop()
    
    @discord.ui.button(label="📚 Lecture", style=discord.ButtonStyle.success, custom_id="mode_lecture")
    async def lecture_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_mode = "lecture"
        await interaction.response.send_message(
            "✅ Đã chọn: **Lecture** mode (trích xuất bài giảng)", 
            ephemeral=True
        )
        self.stop()


class ErrorRetryView(discord.ui.View):
    """View with Retry and Close buttons for error messages"""
    
    def __init__(self, retry_callback, retry_args: dict):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.retry_callback = retry_callback
        self.retry_args = retry_args
        self.retried = False
        
    @discord.ui.button(label="🔄 Retry", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.retried:
            await interaction.response.send_message("⚠️ Đã retry rồi!", ephemeral=True)
            return
            
        self.retried = True
        # Disable buttons after retry
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🔄 Đang retry...", view=self)
        
        # Execute retry callback
        await self.retry_callback(interaction, **self.retry_args)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


class MeetingIdModal(discord.ui.Modal, title="Meeting Summary"):
    """Modal for entering meeting ID, local ID, or URL"""

    id_or_url = discord.ui.TextInput(
        label="Local ID, Fireflies ID, or URL",
        style=discord.TextStyle.short,
        placeholder="1452341542420484127_123456... hoặc 01K94... hoặc URL",
    )
    meeting_title = discord.ui.TextInput(
        label="Title (optional - for new)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Tên meeting (chỉ dùng cho meeting mới)",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        # Defer immediately to show we're working
        await interaction.response.defer(ephemeral=True)

        id_or_url = self.id_or_url.value.strip()

        try:
            is_url = id_or_url.startswith("http")
            fireflies_id = None
            original_url = None  # Store link URL for footer
            transcript_data = None
            scraped_title = None
            from_backup = False
            
            # NEW: Ask user to select mode (Meeting or Lecture)
            mode_view = ModeSelectionView()
            mode_msg = await interaction.followup.send(
                "📝 Chọn loại nội dung cần tóm tắt:", 
                view=mode_view, 
                ephemeral=True
            )
            await mode_view.wait()
            mode = mode_view.selected_mode
            
            # Delete mode selection message
            try:
                await mode_msg.delete()
            except Exception:
                pass
            
            # Prompt for optional document (instant feedback)
            from .document_views import prompt_for_document
            slide_content, pdf_path = await prompt_for_document(
                interaction, interaction.client, self.guild_id, mode
            )
            
            # Show processing message (will be deleted when done)
            processing_msg = await interaction.followup.send(
                "⏳ **Đang xử lý...**\n"
                "Quá trình có thể mất **2-3 phút**, xin vui lòng chờ.",
                ephemeral=True
            )

            if is_url:
                # URL: scrape Fireflies share link
                if "fireflies.ai" not in id_or_url:
                    try:
                        await processing_msg.delete()
                    except Exception:
                        pass
                    await interaction.followup.send("❌ Link không hợp lệ")
                    return
                # Scrape share link - keep original URL for footer
                original_url = id_or_url
                result = await fireflies.scrape_fireflies(id_or_url)
                if result:
                    scraped_title, transcript_data = result
            else:
                # ID: Try Fireflies API FIRST, then fallback to local backup
                fireflies_id = id_or_url
                
                # 1. Try Fireflies API first
                transcript_data = await fireflies_api.get_transcript_by_id(
                    id_or_url, guild_id=self.guild_id
                )
                
                # 2. If API doesn't have it, fallback to local backup
                if not transcript_data:
                    local_entry = transcript_storage.get_transcript(self.guild_id, id_or_url)
                    
                    # Try restore from archive if not in local
                    if not local_entry:
                        local_entry = await transcript_storage.restore_from_archive(
                            interaction.client, self.guild_id, id_or_url
                        )
                    
                    if local_entry:
                        from_backup = True
                        scraped_title = local_entry.get("title", "Meeting")
                        transcript_data = local_entry.get("transcript", [])

            if not transcript_data:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass
                await interaction.followup.send(
                    f"❌ Không tìm thấy transcript `{id_or_url}` (API và backup đều không có)"
                )
                return

            # Generate summary
            transcript_text = fireflies.format_transcript_for_llm(transcript_data)
            
            # Get user Gemini key for potential usage
            from services import config as config_service
            user_gemini_key = config_service.get_user_gemini_api(interaction.user.id)
            
            # PRIORITY PATH: Gemini (if user has key)
            if user_gemini_key:
                from services import gemini
                try:
                    logger.info(f"Using Gemini for meeting summary (user {interaction.user.id}, slides={'yes' if pdf_path else 'no'})")
                    
                    # Extract links from PDF for References section
                    pdf_links_str = ""
                    if pdf_path:
                        try:
                            pdf_links = slides_service.extract_links_from_pdf(pdf_path)
                            pdf_links_str = slides_service.format_pdf_links_for_prompt(pdf_links)
                            if pdf_links:
                                logger.info(f"Extracted {len(pdf_links)} links from PDF for meeting summary")
                        except Exception as e:
                            logger.warning(f"Failed to extract PDF links: {e}")
                    
                    # Get meeting summary prompt
                    system_prompt = config_service.get_prompt(
                        self.guild_id,
                        mode=mode,
                        prompt_type="summary"
                    )
                    
                    summary = await gemini.summarize_meeting(
                        transcript=transcript_text,
                        pdf_path=pdf_path,  # Can be None
                        prompt=system_prompt,
                        api_key=user_gemini_key,
                        pdf_links=pdf_links_str,
                    )
                except Exception as e:
                    logger.warning(f"Gemini failed, falling back to GLM: {e}")
                    # FALLBACK: GLM
                    summary = await llm.summarize_transcript(
                        transcript_text, 
                        guild_id=self.guild_id, 
                        user_id=interaction.user.id,
                        slide_content=slide_content, 
                        mode=mode
                    )
            else:
                # NO GEMINI KEY: Use GLM directly
                summary = await llm.summarize_transcript(
                    transcript_text, 
                    guild_id=self.guild_id, 
                    user_id=interaction.user.id,
                    slide_content=slide_content, 
                    mode=mode
                )
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except Exception:
                pass
            
            # Cleanup PDF file if exists
            if pdf_path:
                try:
                    import os
                    os.remove(pdf_path)
                    logger.info(f"Cleaned up PDF: {pdf_path}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup PDF {pdf_path}: {e}")

            # Auto save locally - use user title, scraped title, or fallback
            title = (
                self.meeting_title.value
                or scraped_title
                or f"Meeting {fireflies_id[:10] if fireflies_id else 'scraped'}"
            )
            
            # Use Fireflies ID or generate unique ID for scraped
            # Check if ID is in the URL (format: ...::ID or ...::ID?t=...)
            url_id_match = re.search(r"::([A-Za-z0-9]+)(?:\?|$)", original_url or "")
            if url_id_match:
                transcript_id = url_id_match.group(1)
                logger.info(f"Extracted ID from URL: {transcript_id}")
            else:
                transcript_id = fireflies_id or f"scraped_{int(datetime.now().timestamp())}"
            
            # Only save if not from backup (already saved)
            if not from_backup:
                entry, is_new = transcript_storage.save_transcript(
                    guild_id=self.guild_id,
                    transcript_id=transcript_id,
                    title=title,
                    platform="ff",
                    transcript_data=transcript_data,
                )

                # Only upload to archive if new (not duplicate)
                if is_new:
                    await transcript_storage.upload_to_discord(
                        interaction.client, self.guild_id, entry
                    )
                entry_id = entry.get('id') or transcript_id
            else:
                entry_id = transcript_id


            # Build summary header
            source_tag = " (từ backup)" if from_backup else ""
            header = f"📋 **{title}**{source_tag} (ID: `{entry_id}`)\n"
            
            # Check if LLM returned an error
            if summary and summary.startswith("⚠️ LLM"):
                # Create retry callback
                async def retry_summary(retry_interaction, **kwargs):
                    try:
                        new_summary = await llm.summarize_transcript(
                            kwargs["transcript_text"],
                            guild_id=kwargs["guild_id"],
                            user_id=kwargs.get("user_id"),
                            slide_content=kwargs.get("slide_content"),
                            mode=kwargs.get("mode", "meeting")
                        )
                        if new_summary and not new_summary.startswith("⚠️ LLM"):
                            new_summary, latex_imgs = latex_utils.process_latex_formulas(new_summary)
                            if latex_imgs:
                                await _send_with_latex_images(retry_interaction.channel, kwargs["header"] + new_summary, latex_imgs)
                            else:
                                await send_chunked(retry_interaction.channel, kwargs["header"] + new_summary)
                        else:
                            await retry_interaction.followup.send(
                                f"{kwargs['header']}\n{new_summary or '⚠️ Retry failed'}",
                                ephemeral=True
                            )
                    except Exception as err:
                        await retry_interaction.followup.send(f"❌ Retry error: {err}", ephemeral=True)
                
                # Show error with retry buttons
                retry_args = {
                    "transcript_text": transcript_text,
                    "guild_id": self.guild_id,
                    "user_id": interaction.user.id,
                    "slide_content": slide_content,
                    "mode": mode,
                    "header": header,
                }
                view = ErrorRetryView(retry_summary, retry_args)
                await interaction.channel.send(f"{header}\n{summary}", view=view)
                return
            
            # Process summary timestamps: [-123s-] -> [MM:SS](link) if we have a link
            ff_link_for_processing = ""
            if original_url:
                ff_link_for_processing = original_url
            elif fireflies_id:
                ff_link_for_processing = fireflies_api.generate_fireflies_link(title, fireflies_id)
                
            if summary and ff_link_for_processing:
                summary = fireflies.process_summary_timestamps(summary, ff_link_for_processing)
            
            # Send summary to channel (not reply) to avoid deletion issues
            if summary:
                # Process LaTeX formulas: $$...$$ -> image, $...$ -> Unicode
                summary, latex_images = latex_utils.process_latex_formulas(summary)
                
                if latex_images:
                    # Send with embedded images for block formulas
                    await _send_with_latex_images(interaction.channel, header + summary, latex_images)
                else:
                    await send_chunked(interaction.channel, header + summary)
            else:
                await interaction.followup.send(
                    f"⚠️ Summary trống - LLM không trả về nội dung\n{header}",
                    ephemeral=True
                )

        except Exception as e:
            logger.exception("Error in meeting summary")
            await interaction.followup.send(f"❌ Lỗi: {str(e)[:100]}")


class JoinMeetingModal(discord.ui.Modal, title="Join Meeting Now"):
    """Modal for joining a meeting immediately"""

    meeting_link = discord.ui.TextInput(
        label="Meeting Link",
        style=discord.TextStyle.short,
        placeholder="https://meet.google.com/xxx hoặc Zoom link",
    )
    meeting_title = discord.ui.TextInput(
        label="Title (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Tên meeting",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Queue-based deletion: delete oldest if at capacity
        from services import config as config_service
        max_records = config_service.get_fireflies_max_records(self.guild_id)
        current_count = await fireflies_api.get_transcript_count(self.guild_id)
        
        if current_count >= max_records:
            # Get whitelist and find oldest non-whitelisted transcript
            whitelist = config_service.get_whitelist_transcripts(self.guild_id)
            transcripts = await fireflies_api.list_transcripts(self.guild_id, limit=50)
            
            if transcripts:
                # Sort by date (oldest first), skip whitelisted
                for t in sorted(transcripts, key=lambda x: x.get("date", 0)):
                    if t.get("id") not in whitelist:
                        await fireflies_api.delete_transcript(t["id"], self.guild_id)
                        logger.info(f"Queue cleanup: deleted transcript {t['id']}")
                        break

        # Join meeting
        success, msg = await fireflies_api.add_to_live_meeting(
            meeting_link=self.meeting_link.value,
            guild_id=self.guild_id,
            title=self.meeting_title.value or None,
        )

        if not success:
            await interaction.followup.send(f"❌ {msg}")
            return

        await interaction.followup.send(f"✅ {msg}")

        # Now ask for optional document (while bot is joining/recording)
        from .document_views import prompt_for_document
        glossary = await prompt_for_document(
            interaction, interaction.client, self.guild_id
        )

        # Always create poll to fetch transcript later (with or without glossary)
        from datetime import datetime, timedelta
        poll_time = datetime.now() + timedelta(hours=2, minutes=20)
        scheduler.add_poll(
            guild_id=self.guild_id,
            poll_after=poll_time,
            title=self.meeting_title.value,
            glossary_text=glossary,  # May be None
        )
        
        if glossary:
            await interaction.followup.send("📎 Đã lưu tài liệu cho summary sau", ephemeral=True)



class ScheduleMeetingModal(discord.ui.Modal, title="Schedule Meeting"):
    """Modal for scheduling a meeting"""

    meeting_link = discord.ui.TextInput(
        label="Meeting Link",
        style=discord.TextStyle.short,
        placeholder="https://meet.google.com/xxx",
    )
    time_input = discord.ui.TextInput(
        label="Thời gian (HH:MM hoặc +30m)",
        style=discord.TextStyle.short,
        placeholder="14:30 hoặc +30m (sau 30 phút)",
    )
    meeting_title = discord.ui.TextInput(
        label="Title (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Tên meeting",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id
        # Update label with timezone
        from services import config as config_service
        tz_name = config_service.get_timezone(guild_id)
        self.time_input.label = f"Thời gian (HH:MM / +30m) - TZ: {tz_name}"

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        time_str = self.time_input.value.strip()
        
        # Get guild timezone
        from services import config as config_service
        from datetime import timezone as tz_module
        from zoneinfo import ZoneInfo
        
        tz_name = config_service.get_timezone(self.guild_id)
        
        # Parse timezone - support both UTC+X and IANA format
        try:
            if tz_name.upper().startswith("UTC"):
                offset_str = tz_name[3:]
                offset_hours = int(offset_str) if offset_str else 0
                tz = tz_module(timedelta(hours=offset_hours))
            else:
                tz = ZoneInfo(tz_name)
        except Exception:
            tz = tz_module(timedelta(hours=7))  # Default UTC+7
        
        now = datetime.now(tz)

        try:
            # Parse time
            if time_str.startswith("+"):
                # Relative time: +30m, +1h
                value = time_str[1:-1]
                unit = time_str[-1].lower()
                if unit == "m":
                    scheduled_time = now + timedelta(minutes=int(value))
                elif unit == "h":
                    scheduled_time = now + timedelta(hours=int(value))
                else:
                    raise ValueError("Invalid time format")
            else:
                # Absolute time: HH:MM
                time_parts = time_str.split(":")
                scheduled_time = now.replace(
                    hour=int(time_parts[0]),
                    minute=int(time_parts[1]),
                    second=0,
                    microsecond=0,
                )
                # If time is in the past, assume tomorrow
                if scheduled_time < now:
                    scheduled_time += timedelta(days=1)

        except Exception:
            await interaction.followup.send(
                f"❌ Format thời gian không hợp lệ. Dùng HH:MM hoặc +30m\n"
                f"_(Timezone: {tz_name})_",
                ephemeral=True,
            )
            return

        # Prompt for optional document
        from .document_views import prompt_for_document
        glossary = await prompt_for_document(
            interaction, interaction.client, self.guild_id
        )

        # Schedule the meeting with optional glossary
        entry = scheduler.add_scheduled(
            meeting_link=self.meeting_link.value,
            scheduled_time=scheduled_time,
            guild_id=self.guild_id,
            title=self.meeting_title.value or None,
            glossary_text=glossary,  # Store for later use
        )

        doc_status = "\n📎 Có tài liệu đính kèm" if glossary else ""
        confirm_msg = await interaction.followup.send(
            f"✅ Đã lên lịch!{doc_status}\n"
            f"**ID:** `{entry['id']}`\n"
            f"**Time:** {scheduled_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"**Link:** {self.meeting_link.value[:50]}...\n"
            f"_(Dùng View Scheduled để xem/xóa)_",
            wait=True,
        )
        # Auto-delete after 60s
        await asyncio.sleep(60)
        try:
            await confirm_msg.delete()
        except Exception:
            pass


class CancelScheduleModal(discord.ui.Modal, title="Cancel Scheduled Meeting"):
    """Modal for canceling a scheduled meeting"""

    schedule_id = discord.ui.TextInput(
        label="Schedule ID",
        style=discord.TextStyle.short,
        placeholder="1452341542420484127_1734839580",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        schedule_id = self.schedule_id.value.strip()

        if scheduler.remove_scheduled(schedule_id):
            await interaction.response.send_message(
                f"✅ Đã hủy lịch `{schedule_id}`", delete_after=30
            )
        else:
            await interaction.response.send_message(
                f"❌ Không tìm thấy lịch `{schedule_id}`", ephemeral=True
            )


class SaveDeleteModal(discord.ui.Modal, title="Save & Delete from Fireflies"):
    """Modal for saving transcript locally and deleting from Fireflies"""

    fireflies_id = discord.ui.TextInput(
        label="Fireflies Transcript ID",
        style=discord.TextStyle.short,
        placeholder="01K94BJAWM5JMFREPDXKJY16GB",
    )
    meeting_title = discord.ui.TextInput(
        label="Title (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Meeting title",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        ff_id = self.fireflies_id.value.strip()

        # Get transcript from Fireflies
        transcript_data = await fireflies_api.get_transcript_by_id(
            ff_id, guild_id=self.guild_id
        )

        if not transcript_data:
            await interaction.followup.send("❌ Không tìm thấy transcript")
            return

        # Generate summary
        transcript_text = fireflies.format_transcript(transcript_data)
        summary = await llm.summarize_transcript(
            transcript_text, 
            guild_id=self.guild_id,
            user_id=interaction.user.id
        )

        # Save locally
        title = self.meeting_title.value or f"Meeting {ff_id[:10]}"
        entry, _ = transcript_storage.save_transcript(
            guild_id=self.guild_id,
            transcript_id=ff_id,
            title=title,
            platform="ff",
            transcript_data=transcript_data,
            extra_metadata={"summary": summary} if summary else None,
        )

        # Delete from Fireflies
        success, msg = await fireflies_api.delete_transcript(ff_id, self.guild_id)

        if success:
            await interaction.followup.send(
                f"✅ Đã lưu & xóa từ Fireflies!\n"
                f"**Local ID:** `{entry['local_id']}`\n"
                f"**Title:** {title}",
                delete_after=60,
            )
        else:
            await interaction.followup.send(
                f"✅ Đã lưu local (ID: `{entry['local_id']}`)\n"
                f"⚠️ Không xóa được từ FF: {msg}",
                delete_after=60,
            )


class DeleteSavedModal(discord.ui.Modal, title="Delete Saved Transcript"):
    """Modal for deleting a saved transcript"""

    local_id = discord.ui.TextInput(
        label="Local ID",
        style=discord.TextStyle.short,
        placeholder="1452341542420484127_103055221220",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        local_id = self.local_id.value.strip()

        if transcript_storage.delete_transcript(local_id):
            await interaction.response.send_message(
                f"✅ Đã xóa transcript `{local_id}`", delete_after=30
            )
        else:
            await interaction.response.send_message(
                f"❌ Không tìm thấy transcript `{local_id}`", ephemeral=True
            )


class EditTitleModal(discord.ui.Modal, title="Edit Transcript Title"):
    """Modal for editing transcript title"""

    transcript_id = discord.ui.TextInput(
        label="Transcript ID",
        style=discord.TextStyle.short,
        placeholder="01K94BJAWM5J... hoặc full ID",
    )
    new_title = discord.ui.TextInput(
        label="New Title",
        style=discord.TextStyle.short,
        placeholder="Tên mới cho transcript",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        transcript_id = self.transcript_id.value.strip()
        new_title = self.new_title.value.strip()
        
        if not new_title:
            await interaction.followup.send("❌ Title không được để trống", ephemeral=True)
            return
        
        success, message = await transcript_storage.update_title(
            interaction.client, self.guild_id, transcript_id, new_title
        )
        
        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)

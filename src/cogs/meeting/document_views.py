"""
Document Upload Views - UI components for document upload flow
"""

import asyncio
import logging

import discord

from services import llm, slide_cache
from services.prompts import MEETING_VLM_PROMPT, LECTURE_VLM_PROMPT
from utils.document_utils import pdf_to_images, validate_attachment

logger = logging.getLogger(__name__)


class DocumentPromptView(discord.ui.View):
    """Yes/No buttons for document upload prompt"""

    def __init__(self):
        super().__init__(timeout=30)  # 30s timeout for button click
        self.wants_doc = None
        self.doc_interaction = None

    @discord.ui.button(label="✅ Có", style=discord.ButtonStyle.success)
    async def yes_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.wants_doc = True
        self.doc_interaction = interaction
        await interaction.response.send_message(
            "📎 **Upload file PDF** trong 90s...\n"
            "_(Gửi file vào channel này)_",
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="❌ Không", style=discord.ButtonStyle.secondary)
    async def no_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.wants_doc = False
        await interaction.response.defer()
        self.stop()


async def prompt_for_document(
    interaction: discord.Interaction,
    bot,
    guild_id: int,
    mode: str = "meeting",
) -> tuple[str | None, str | None]:
    """
    Prompt user for optional document upload and extract slide content.
    
    Args:
        interaction: Discord interaction (must be deferred)
        bot: Discord bot instance
        guild_id: Guild ID for API key
        mode: "meeting" or "lecture" - determines extraction focus
        
    Returns:
        Tuple of (extracted_content, pdf_path) - both optional
        Content is for GLM fallback, path is for Gemini multimodal
    """
    # Get VLM prompt for cache key
    vlm_prompt = LECTURE_VLM_PROMPT if mode == "lecture" else MEETING_VLM_PROMPT
    
    # Send prompt with buttons
    view = DocumentPromptView()
    prompt_msg = await interaction.followup.send(
        "📎 **Có bổ sung tài liệu?**\n"
        "Trích xuất nội dung slides để summary chi tiết hơn",
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

    if not view.wants_doc:
        return None, None

    # Wait for file upload
    def check(m):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
            and m.attachments
        )

    try:
        msg = await bot.wait_for("message", check=check, timeout=90)
        attachment = msg.attachments[0]
        filename = attachment.filename

        # Validate file
        is_valid, error = validate_attachment(attachment)
        if not is_valid:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return None, None
        
        # Check cache BEFORE downloading (save bandwidth)
        cached_content = slide_cache.get_cached_slide_content(filename, vlm_prompt)
        if cached_content:
            # Delete message immediately
            try:
                await msg.delete()
            except Exception:
                pass
            
            await interaction.followup.send(
                f"✅ Sử dụng cache ({len(cached_content)} chars) ⚡",
                ephemeral=True
            )
            # No PDF path when using cache
            return cached_content, None

        # Download file - create editable status message
        status_msg = await interaction.followup.send(
            "⏳ Đang tải tài liệu...", 
            ephemeral=True,
            wait=True
        )
        file_bytes = await attachment.read()
        
        # Save PDF to temp file for Gemini option
        import hashlib
        pdf_hash = hashlib.md5(file_bytes).hexdigest()[:10]
        pdf_path = f"/tmp/meeting_slides_{pdf_hash}.pdf"
        with open(pdf_path, 'wb') as f:
            f.write(file_bytes)
        
        # Delete user's message with attachment immediately after download
        try:
            await msg.delete()
        except Exception:
            pass

        # Update status for processing
        try:
            await status_msg.edit(content="⏳ Đang xử lý tài liệu...")
        except Exception:
            pass

        # Process file (convert PDF to images)
        images = pdf_to_images(file_bytes)

        if not images:
            try:
                await status_msg.edit(content="❌ Không thể đọc PDF")
            except Exception:
                pass
            return None, None

        # Update status for VLM extraction
        try:
            await status_msg.edit(content="⏳ Đang trích xuất nội dung slides (2-5 phút)...")
        except Exception:
            pass

        # Extract slide content using Vision model
        slide_content = await llm.extract_slide_content(images, guild_id, mode=mode)

        # Check for VLM error
        if slide_content and slide_content.startswith("⚠️ VLM"):
            # Import ErrorRetryView here to avoid circular import
            from cogs.meeting.modals import ErrorRetryView
            
            # Create retry callback
            async def retry_vlm(retry_interaction, **kwargs):
                try:
                    new_content = await llm.extract_slide_content(
                        kwargs["images"],
                        kwargs["guild_id"],
                        mode=kwargs.get("mode", "meeting")
                    )
                    if new_content and not new_content.startswith("⚠️ VLM"):
                        slide_cache.save_slide_content_cache(
                            kwargs["filename"], kwargs["vlm_prompt"], new_content
                        )
                        await retry_interaction.followup.send(
                            f"✅ Retry thành công! ({len(new_content)} chars)",
                            ephemeral=True
                        )
                        # Can't return content, but it's cached now
                    else:
                        await retry_interaction.followup.send(
                            f"❌ Retry failed: {new_content or 'No content'}",
                            ephemeral=True
                        )
                except Exception as err:
                    await retry_interaction.followup.send(f"❌ Retry error: {err}", ephemeral=True)
            
            retry_args = {
                "images": images,
                "guild_id": guild_id,
                "mode": mode,
                "filename": filename,
                "vlm_prompt": vlm_prompt,
            }
            view = ErrorRetryView(retry_vlm, retry_args)
            
            try:
                await status_msg.edit(content=f"❌ VLM Error:\n{slide_content}", view=view)
            except Exception:
                pass
            return None, None  # Return None so summarize proceeds without slides

        # Save to cache and update status
        if slide_content:
            slide_cache.save_slide_content_cache(filename, vlm_prompt, slide_content)
            try:
                await status_msg.edit(
                    content=f"✅ Đã trích xuất slides ({len(slide_content)} chars) - cache 24h"
                )
            except Exception:
                pass

        return slide_content, pdf_path

    except asyncio.TimeoutError:
        await interaction.followup.send(
            "⏰ Timeout - tiếp tục không có tài liệu",
            ephemeral=True,
        )
        return None, None
    except Exception as e:
        logger.exception("Error processing document")
        await interaction.followup.send(
            f"❌ Lỗi xử lý tài liệu: {str(e)[:50]}",
            ephemeral=True,
        )
        return None, None

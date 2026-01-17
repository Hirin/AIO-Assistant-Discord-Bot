"""
Ask Q&A Cog - Lecture Q&A with visual illustrations
Supports both /ask (slash) and !ask (prefix) commands
"""

import os
import re
import io
import logging
from typing import Optional
from dataclasses import dataclass

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

# Temp directory for user images
TEMP_DIR = "/tmp/ask_images"
os.makedirs(TEMP_DIR, exist_ok=True)

# Slide URL patterns
SLIDE_PATTERNS = [
    r'📁 Slides?:\s*(https?://[^\s<>]+)',
    r'📄 Slides?:\s*(https?://[^\s<>]+)',
    r'Slides?:\s*(https?://[^\s<>]+)',
    r'Tài liệu:\s*(https?://[^\s<>]+)',
    r'📎 Tài liệu:\s*(https?://[^\s<>]+)',
]


@dataclass
class AskContext:
    """Context data for /ask command"""
    bot_text: list[str]
    user_messages: list[dict]
    chat_images: list[str]  # Temp file paths
    slide_url: Optional[str]
    pdf_attachment: Optional[str]


class AskRetryView(discord.ui.View):
    """Retry view with 3-minute timeout"""
    
    def __init__(
        self, 
        cog: "AskCog",
        source,  # Interaction or Context
        context: AskContext,
        question: str,
        question_image: Optional[bytes],
        message: discord.Message = None,  # Track the message
    ):
        super().__init__(timeout=180)  # 3 minutes
        self.cog = cog
        self.source = source
        self.context = context
        self.question = question
        self.question_image = question_image
        self.retried = False
        self.message = message
    
    @discord.ui.button(label="🔄 Thử lại", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.retried = True
        await interaction.response.defer()
        await self.cog._process_ask(
            interaction, 
            self.question, 
            self.question_image,
            self.context,  # Reuse context
        )
    
    @discord.ui.button(label="🔑 Đổi Key & Thử lại", style=discord.ButtonStyle.secondary)
    async def change_key_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Force rotate to next API key and retry"""
        self.retried = True
        await interaction.response.defer()
        
        # Mark current key as rate limited to force rotation
        from services import gemini_keys
        user_id = interaction.user.id
        pool = gemini_keys.get_pool(user_id)
        if pool and pool.keys:
            current_key = pool.get_next_key()
            if current_key:
                pool.mark_rate_limited(current_key)
                logger.info(f"Forced key rotation for user {user_id}")
        
        await self.cog._process_ask(
            interaction, 
            self.question, 
            self.question_image,
            self.context,
        )
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self._cleanup()
        self.stop()
    
    async def on_timeout(self):
        """Disable buttons on timeout"""
        if not self.retried:
            self._cleanup()
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            # Try to edit the message to show disabled buttons
            try:
                if self.message:
                    await self.message.edit(view=self)
            except Exception:
                pass  # Message may have been deleted
    
    def _cleanup(self):
        """Remove temp chat images"""
        for path in self.context.chat_images:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logger.debug(f"Cleaned up temp file: {path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup {path}: {e}")


class QuotaExhaustedException(Exception):
    """Raised when all API keys are exhausted (429 rate limit)"""
    pass


class AskQuotaExhaustedView(discord.ui.View):
    """View shown when all API keys hit quota - offers config option"""
    
    def __init__(
        self, 
        cog: "AskCog",
        source,
        context: AskContext,
        question: str,
        question_image: Optional[bytes],
        message: discord.Message = None,
    ):
        super().__init__(timeout=300)  # 5 minutes
        self.cog = cog
        self.source = source
        self.context = context
        self.question = question
        self.question_image = question_image
        self.message = message
        self.retried = False
    
    @discord.ui.button(label="🔄 Thử lại", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Retry - useful after waiting for quota reset"""
        self.retried = True
        
        # Reset rate limit status for all keys
        from services import gemini_keys
        pool = gemini_keys.get_pool(interaction.user.id)
        if pool:
            pool.reset_rate_limits()
            logger.info(f"Reset rate limits for user {interaction.user.id}")
        
        await interaction.response.defer()
        await self.cog._process_ask(
            interaction, 
            self.question, 
            self.question_image,
            self.context,
        )
    
    @discord.ui.button(label="⚙️ Cấu hình API", style=discord.ButtonStyle.secondary)
    async def config_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open GeminiConfigView to add/manage keys"""
        from cogs.shared.gemini_config_view import GeminiConfigView
        
        # Create callback to return to this view after config
        async def return_callback(return_interaction: discord.Interaction):
            embed = discord.Embed(
                title="⚠️ Tất cả API keys đã hết quota",
                description="Bạn có thể:\n"
                    "• **Thử lại** - nếu đã đợi quota reset\n"
                    "• **Cấu hình API** - thêm key mới\n"
                    "• **Đóng** - hủy",
                color=discord.Color.orange()
            )
            await return_interaction.response.edit_message(embed=embed, view=self)
        
        config_view = GeminiConfigView(interaction.user.id, return_callback=return_callback)
        embed = config_view._build_status_embed()
        await interaction.response.edit_message(embed=embed, view=config_view)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self._cleanup()
        self.stop()
    
    async def on_timeout(self):
        """Disable buttons on timeout"""
        if not self.retried:
            self._cleanup()
            for item in self.children:
                item.disabled = True
            try:
                if self.message:
                    await self.message.edit(view=self)
            except Exception:
                pass
    
    def _cleanup(self):
        """Remove temp chat images"""
        for path in self.context.chat_images:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


class AskCog(commands.Cog):
    """Lecture Q&A with visual illustrations"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # =========================================================================
    # Prefix Command Only (for image attachments support)
    # =========================================================================
    
    @commands.command(name="ask")
    async def ask_prefix(self, ctx: commands.Context):
        """!ask <câu hỏi> - Hỏi đáp về bài học (có thể đính kèm hình)"""
        question = ctx.message.content.replace("!ask", "", 1).strip()
        if not question and not ctx.message.attachments:
            await ctx.reply("❌ Vui lòng nhập câu hỏi. Ví dụ: `!ask Giải thích Receptive Field?`")
            return
        
        async with ctx.typing():
            await self._handle_ask(ctx, question, ctx.message.attachments)
    
    # =========================================================================
    # Shared Logic
    # =========================================================================
    
    async def _handle_ask(
        self, 
        source,  # Interaction or Context
        question: str,
        attachments: list[discord.Attachment],
    ):
        """Main handler for both slash and prefix commands"""
        
        # Get channel
        channel = source.channel if hasattr(source, 'channel') else source.channel
        
        # Download question image if any, detect PDF attachment
        question_image = None
        user_pdf_url = None
        
        if attachments:
            for att in attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    question_image = await att.read()
                elif att.filename.endswith('.pdf'):
                    # User attached a PDF - use this as slide context
                    user_pdf_url = att.url
                    logger.info(f"User attached PDF: {att.filename}")
        
        # Check for Google Drive link in question
        if not user_pdf_url:
            from utils import drive_utils
            
            # Extract Drive link from question
            drive_pattern = r'(https://drive\.google\.com/[^\s]+)'
            match = re.search(drive_pattern, question)
            if match:
                drive_link = match.group(1)
                
                # Validate with magic bytes check (only downloads 1KB)
                is_pdf, result = await drive_utils.check_drive_pdf(drive_link)
                
                if is_pdf:
                    user_pdf_url = result  # result is download URL
                    question = question.replace(drive_link, '').strip()
                    logger.info(f"Validated Drive PDF: {drive_link[:50]}...")
                else:
                    await self._send_error(source, f"❌ {result}")
                    return
        
        # Get context from channel history
        context = await self._get_context(channel)
        
        # Override slide_url if user provided their own PDF
        if user_pdf_url:
            context.slide_url = user_pdf_url
            logger.info("Using user-provided PDF as slide context")
        
        # Process
        await self._process_ask(source, question, question_image, context)
    
    async def _send_error(self, source, message: str):
        """Send error message to user"""
        if hasattr(source, 'reply'):
            await source.reply(message)
        elif hasattr(source, 'followup'):
            await source.followup.send(message, ephemeral=True)
        else:
            await source.channel.send(message)
    
    async def _get_context(self, channel, limit: int = 100) -> AskContext:
        """
        Retrieve context from channel history.
        Priority: stored lecture context (summary/preview) > recent chat history
        
        If no stored context: fallback to 200 messages for full context
        Slide URL priority: summary > preview > scan history
        """
        from services import lecture_context_storage
        
        context = AskContext(
            bot_text=[],
            user_messages=[],
            chat_images=[],
            slide_url=None,
            pdf_attachment=None,
        )
        
        thread_id = channel.id
        stored_context = lecture_context_storage.get_lecture_context(thread_id)
        
        # Track message ID ranges to exclude from chat history
        exclude_ranges = []  # List of (start_id, end_id)
        
        # Track slide URLs from different sources
        preview_slide_url = None
        summary_slide_url = None
        
        if stored_context:
            logger.info(f"Found stored lecture context for thread {thread_id}")
            
            # Fetch preview messages by ID range
            preview_start = stored_context.get("preview_msg_start_id")
            preview_end = stored_context.get("preview_msg_end_id")
            
            if preview_start and preview_end:
                exclude_ranges.append((int(preview_start), int(preview_end)))
                preview_slide_url = stored_context.get("slide_url")  # From preview
                try:
                    async for msg in channel.history(
                        after=discord.Object(id=int(preview_start) - 1),
                        before=discord.Object(id=int(preview_end) + 1),
                        oldest_first=True,
                    ):
                        if msg.author.bot:
                            context.bot_text.append(msg.content)
                except Exception as e:
                    logger.warning(f"Failed to fetch preview messages: {e}")
            
            # Fetch summary messages by ID range
            summary_start = stored_context.get("summary_msg_start_id")
            summary_end = stored_context.get("summary_msg_end_id")
            
            if summary_start and summary_end:
                exclude_ranges.append((int(summary_start), int(summary_end)))
                # Summary may have its own slide URL (from meeting recording)
                if stored_context.get("slide_url"):
                    summary_slide_url = stored_context.get("slide_url")
                try:
                    async for msg in channel.history(
                        after=discord.Object(id=int(summary_start) - 1),
                        before=discord.Object(id=int(summary_end) + 1),
                        oldest_first=True,
                    ):
                        if msg.author.bot:
                            context.bot_text.append(msg.content)
                except Exception as e:
                    logger.warning(f"Failed to fetch summary messages: {e}")
            
            # Prioritize slide URL: summary > preview
            context.slide_url = summary_slide_url or preview_slide_url
        
        # Determine chat history limit
        # If no stored context, use 200 for better context coverage
        chat_limit = limit if stored_context else 200
        
        # Check config: should we include chat history?
        from services import config
        guild_id = getattr(channel, 'guild', None)
        if guild_id:
            guild_id = guild_id.id
        include_chat = config.get_ask_include_chat(guild_id) if guild_id else True
        
        if not include_chat:
            logger.info("Skipping chat history (config: ask_include_chat=False)")
        else:
            # Fetch recent chat history (excluding preview/summary ranges)
            async for msg in channel.history(limit=chat_limit):
                msg_id = msg.id
                
                # Skip if in excluded ranges
                is_excluded = any(start <= msg_id <= end for start, end in exclude_ranges)
                if is_excluded:
                    continue
                
                if msg.author.bot:
                    # Only add if we don't have stored context (avoid duplicates)
                    if not stored_context:
                        context.bot_text.append(msg.content)
                        
                        # Find PDF attachment (first one only)
                        if not context.pdf_attachment:
                            for att in msg.attachments:
                                if att.filename.endswith('.pdf'):
                                    context.pdf_attachment = att.url
                                    break
                else:
                    # User message - always include recent discussions
                    context.user_messages.append({
                        "author": msg.author.display_name,
                        "content": msg.content,
                    })
                    
                    # Download user images
                    for att in msg.attachments:
                        if att.content_type and att.content_type.startswith("image/"):
                            path = f"{TEMP_DIR}/{msg.id}_{att.filename}"
                            try:
                                await att.save(path)
                                context.chat_images.append(path)
                            except Exception as e:
                                logger.warning(f"Failed to save image: {e}")
        
        # Fallback: Extract slide URL from bot messages if not stored
        if not context.slide_url:
            context.slide_url = self._extract_slide_url(context.bot_text)
        
        return context
    
    def _extract_slide_url(self, bot_messages: list[str]) -> Optional[str]:
        """Extract most recent slide URL (not in References)"""
        for msg in bot_messages:  # Already in reverse order (newest first)
            content = msg
            
            # Skip References section
            if "📚 References" in msg:
                content = msg.split("📚 References")[0]
            
            # Try patterns
            for pattern in SLIDE_PATTERNS:
                if match := re.search(pattern, content):
                    return match.group(1)
            
            # Fallback: Drive link
            if match := re.search(r'https://drive\.google\.com/file/d/[^\s<>]+', content):
                return match.group(0)
        
        return None
    
    async def _process_ask(
        self,
        source,
        question: str,
        question_image: Optional[bytes],
        context: AskContext,
    ):
        """Process ask request with Gemini"""
        from services.prompts import ASK_PROMPT
        from services import gemini
        
        try:
            # Build lecture context (from bot messages)
            lecture_context = "\n\n".join(context.bot_text[:10])  # Last 10 bot messages
            
            # Build user discussions
            user_discussions = "\n".join([
                f"- **{m['author']}:** {m['content'][:200]}"
                for m in context.user_messages[:20]  # Last 20 user messages
            ])
            
            # Download slide images if available
            slide_images = []
            if context.slide_url or context.pdf_attachment:
                slide_url = context.slide_url or context.pdf_attachment
                slide_images = await self._download_slide_images(slide_url)
            
            # Build prompt
            prompt = ASK_PROMPT.format(
                lecture_context=lecture_context[:8000] or "Không có context",
                user_discussions=user_discussions[:4000] or "Không có thảo luận",
                num_chat_images=len(context.chat_images),
                num_slides=len(slide_images),
                question=question or "(Xem hình đính kèm)",
                has_question_image="Có" if question_image else "Không",
            )
            
            # Build Gemini contents
            from google.genai import types
            contents = []
            
            # Add slides with labels
            if slide_images:
                contents.append("📑 SLIDES (dùng [-PAGE:X-]):")
                for i, img_bytes in enumerate(slide_images, 1):
                    contents.append(f"[Slide {i}]")
                    contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
            
            # Add chat images with labels
            if context.chat_images:
                contents.append("🖼️ HÌNH TỪ THẢO LUẬN (dùng [-CHAT_IMG:X-]):")
                for i, path in enumerate(context.chat_images, 1):
                    contents.append(f"[Chat Image {i}]")
                    with open(path, "rb") as f:
                        img_data = f.read()
                    # Detect mime type
                    mime = "image/png" if path.endswith(".png") else "image/jpeg"
                    contents.append(types.Part.from_bytes(data=img_data, mime_type=mime))
            
            # Add question image
            if question_image:
                contents.append("❓ HÌNH ĐÍNH KÈM CÂU HỎI:")
                contents.append(types.Part.from_bytes(data=question_image, mime_type="image/png"))
            
            # Add prompt text
            contents.append(prompt)
            
            # Get user's Gemini keys with pool rotation
            from services.config import get_user_gemini_apis
            from services.gemini_keys import GeminiKeyPool
            
            user_id = source.user.id if hasattr(source, 'user') else source.author.id
            api_keys = get_user_gemini_apis(user_id)
            
            if not api_keys:
                await self._send_response(
                    source, 
                    "❌ Chưa có Gemini API key. Dùng `/lecture` → 🔑 Gemini API để cấu hình."
                )
                return
            
            # Use key pool for rotation
            from services import gemini_keys
            key_pool = GeminiKeyPool(user_id, api_keys)
            gemini_keys.register_pool(user_id, key_pool)  # Register for access in retry views
            
            response_text = None
            last_error = None
            is_quota_error = False
            
            # Try with key rotation
            for attempt in range(len(api_keys)):
                api_key = key_pool.get_available_key()
                if not api_key:
                    break
                
                try:
                    client = gemini.get_client(api_key)
                    # Run sync Gemini call in thread to avoid blocking event loop
                    import asyncio
                    response_text = await asyncio.to_thread(
                        gemini._call_gemini_sync, client, contents
                    )
                    key_pool.increment_count(api_key)
                    break
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    # Rate limit or quota exceeded - try next key
                    if "429" in error_str or "quota" in error_str or "rate" in error_str:
                        key_pool.mark_rate_limited(api_key)
                        is_quota_error = True
                        logger.warning("Key rate limited, trying next...")
                        continue
                    # Invalid key - try next
                    if "invalid" in error_str and "key" in error_str:
                        key_pool.mark_rate_limited(api_key)
                        logger.warning("Invalid key, trying next...")
                        continue
                    # Other error - raise
                    raise
            
            if not response_text:
                if is_quota_error:
                    raise QuotaExhaustedException("Tất cả API keys đã hết quota (429 rate limit)")
                raise last_error or Exception("All API keys exhausted")
            
            # Process LaTeX formulas
            from utils import latex_utils, table_utils
            response_text, latex_images = latex_utils.process_latex_formulas(response_text)
            
            # Process markdown tables
            response_text, table_images = table_utils.process_markdown_tables(response_text)
            
            # Combine all images (latex + tables)
            all_formula_images = latex_images + table_images
            
            # Send response with interleaved images
            await self._send_interleaved_response(
                source, 
                response_text, 
                slide_images=slide_images,
                chat_images=context.chat_images,
                question=question, 
                latex_images=all_formula_images,
            )
            
            # Cleanup temp files
            self._cleanup_temp(context.chat_images)
            latex_utils.cleanup_latex_images(latex_images)
            table_utils.cleanup_table_images(table_images)
            
        except QuotaExhaustedException:
            logger.warning(f"All API keys exhausted for user {source.user.id if hasattr(source, 'user') else source.author.id}")
            
            # Show quota exhausted view with config option
            view = AskQuotaExhaustedView(self, source, context, question, question_image)
            channel = source.channel if hasattr(source, 'channel') else source.channel
            
            embed = discord.Embed(
                title="⚠️ Tất cả API keys đã hết quota",
                description="Tất cả Gemini API keys của bạn đã đạt giới hạn (429 rate limit).\n\n"
                    "**Bạn có thể:**\n"
                    "• 🔄 **Thử lại** - nếu đã đợi quota reset (00:00 Pacific Time)\n"
                    "• ⚙️ **Cấu hình API** - thêm key mới hoặc xem trạng thái\n"
                    "• ❌ **Đóng** - hủy",
                color=discord.Color.orange()
            )
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
            
        except Exception as e:
            logger.exception("Ask processing failed")
            error_msg = str(e)[:200]
            
            # Show retry view
            view = AskRetryView(self, source, context, question, question_image)
            channel = source.channel if hasattr(source, 'channel') else source.channel
            msg = await channel.send(
                f"❌ **Lỗi:** {error_msg}\n\nBạn có thể thử lại.",
                view=view,
            )
            view.message = msg  # Track message for timeout

    
    async def _download_slide_images(self, url: str) -> list[bytes]:
        """Download PDF and convert to images"""
        import httpx
        import tempfile
        from services.slides import pdf_to_images_async
        
        try:
            # Download PDF
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                # Handle Google Drive links
                if "drive.google.com" in url:
                    # Extract file ID and use direct download
                    import re
                    match = re.search(r'/d/([^/]+)', url)
                    if match:
                        file_id = match.group(1)
                        url = f"https://drive.google.com/uc?export=download&id={file_id}"
                
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Failed to download PDF: {resp.status_code}")
                    return []
                
                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(resp.content)
                    pdf_path = f.name
            
            # Convert to images
            image_paths = await pdf_to_images_async(pdf_path)
            
            # Read images as bytes
            images = []
            for img_path in image_paths[:30]:  # Max 30 pages
                with open(img_path, "rb") as f:
                    images.append(f.read())
            
            # Cleanup
            import os
            os.remove(pdf_path)
            from services.slides import cleanup_slide_images
            cleanup_slide_images(image_paths)
            
            return images
            
        except Exception as e:
            logger.warning(f"Failed to download slides: {e}")
            return []
    
    async def _send_interleaved_response(
        self, 
        source, 
        text: str, 
        slide_images: list[bytes],
        chat_images: list[str],
        question: str = None,
        latex_images: list[tuple[str, str]] = None,
        view: discord.ui.View = None,
    ) -> Optional[discord.Message]:
        """
        Send response with interleaved text and images.
        Parses markers and sends: text -> image -> text -> image...
        """
        from services import image_search
        
        channel = source.channel if hasattr(source, 'channel') else source.channel
        first_msg = None
        
        # Build latex lookup
        latex_lookup = {}
        if latex_images:
            for placeholder, img_path in latex_images:
                latex_lookup[placeholder] = img_path
        
        # Pre-download Google Search images with validation
        search_pattern = r'\[-Google Search:\s*"([^"]+)"-\]'
        search_images = {}  # keyword -> (bytes, description)
        for match in re.finditer(search_pattern, text):
            keyword = match.group(1)
            if keyword not in search_images:
                try:
                    # Extract surrounding text for better context
                    # Get 300 chars before the marker as context
                    start_pos = max(0, match.start() - 300)
                    surrounding_text = text[start_pos:match.start()].strip()
                    
                    # Build context: question + surrounding explanation
                    context_parts = []
                    if question:
                        context_parts.append(f"Câu hỏi: {question}")
                    if surrounding_text:
                        context_parts.append(f"Nội dung liên quan: {surrounding_text[-200:]}")
                    full_context = "\n".join(context_parts) if context_parts else None
                    
                    img_bytes, description = await image_search.search_and_download(
                        keyword, context=full_context
                    )
                    search_images[keyword] = (img_bytes, description)
                except Exception as e:
                    logger.warning(f"Image search failed for '{keyword}': {e}")
                    search_images[keyword] = (None, None)
        
        # Parse text into parts: (text_chunk, marker_type, marker_data)
        # marker_type: 'page', 'chat_img', 'search', 'latex' or None
        parts = []
        
        # Combined pattern for all markers
        combined_pattern = r'(\[-PAGE:(\d+)(?::[^-]+)?-\]|\[-CHAT_IMG:(\d+)-\]|\[-Google Search:\s*"([^"]+)"-\]|\[-LATEX_IMG:[a-f0-9]+?-\])'
        
        last_end = 0
        for match in re.finditer(combined_pattern, text):
            # Text before marker
            text_before = text[last_end:match.start()]
            if text_before.strip():
                parts.append((text_before, None, None))
            
            full_match = match.group(0)
            
            # Determine marker type
            if match.group(2):  # PAGE
                parts.append(("", "page", int(match.group(2))))
            elif match.group(3):  # CHAT_IMG
                parts.append(("", "chat_img", int(match.group(3))))
            elif match.group(4):  # Google Search
                parts.append(("", "search", match.group(4)))
            elif "LATEX_IMG" in full_match:
                parts.append(("", "latex", full_match))
            
            last_end = match.end()
        
        # Remaining text
        remaining = text[last_end:]
        if remaining.strip():
            parts.append((remaining, None, None))
        
        # If no parts, use original text
        if not parts:
            parts = [(text, None, None)]
        
        # Send parts interleaved
        is_first = True
        current_text = ""
        
        async def send_text(txt: str, is_reply: bool = False):
            nonlocal first_msg
            if not txt.strip():
                return
            
            # Handle latex in text
            for placeholder, img_path in latex_lookup.items():
                if placeholder in txt:
                    idx = txt.find(placeholder)
                    before = txt[:idx]
                    after = txt[idx + len(placeholder):]
                    
                    if before.strip():
                        if is_reply and first_msg is None and hasattr(source, 'message'):
                            first_msg = await source.reply(before.strip(), mention_author=False)
                        else:
                            await channel.send(before.strip())
                    
                    if os.path.exists(img_path):
                        await channel.send(file=discord.File(img_path, filename="formula.png"))
                    
                    txt = after
            
            if txt.strip():
                if is_reply and first_msg is None and hasattr(source, 'message'):
                    first_msg = await source.reply(txt.strip(), mention_author=False)
                else:
                    await channel.send(txt.strip())
        
        for text_chunk, marker_type, marker_data in parts:
            current_text += text_chunk
            
            if marker_type:
                # Send accumulated text first
                if is_first and question:
                    header = f"❓ **Câu hỏi:** {question}\n\n"
                    current_text = header + current_text
                
                if current_text.strip():
                    # Chunk if too long
                    while len(current_text) > 1900:
                        split_point = current_text.rfind('\n', 0, 1900)
                        if split_point == -1:
                            split_point = 1900
                        await send_text(current_text[:split_point], is_reply=is_first)
                        is_first = False
                        current_text = current_text[split_point:].lstrip()
                    
                    if current_text.strip():
                        await send_text(current_text.strip(), is_reply=is_first)
                        is_first = False
                    current_text = ""
                
                # Send image based on marker type
                if marker_type == "page" and slide_images:
                    page_num = marker_data
                    if 1 <= page_num <= len(slide_images):
                        img_bytes = slide_images[page_num - 1]
                        file = discord.File(io.BytesIO(img_bytes), filename=f"slide_{page_num}.png")
                        await channel.send(file=file)
                
                elif marker_type == "chat_img" and chat_images:
                    idx = marker_data
                    if 1 <= idx <= len(chat_images):
                        path = chat_images[idx - 1]
                        if os.path.exists(path):
                            await channel.send(file=discord.File(path, filename=f"chat_{idx}.png"))
                
                elif marker_type == "search":
                    keyword = marker_data
                    img_data = search_images.get(keyword)
                    if img_data:
                        img_bytes, description = img_data
                        if img_bytes:
                            file = discord.File(io.BytesIO(img_bytes), filename="search.png")
                            # Include description if available
                            caption = f"🔍 *{description}*" if description else None
                            await channel.send(content=caption, file=file)
                
                elif marker_type == "latex":
                    placeholder = marker_data
                    img_path = latex_lookup.get(placeholder)
                    if img_path and os.path.exists(img_path):
                        await channel.send(file=discord.File(img_path, filename="formula.png"))
        
        # Send any remaining text
        if current_text.strip():
            if is_first and question:
                header = f"❓ **Câu hỏi:** {question}\n\n"
                current_text = header + current_text
            
            while len(current_text) > 1900:
                split_point = current_text.rfind('\n', 0, 1900)
                if split_point == -1:
                    split_point = 1900
                await send_text(current_text[:split_point], is_reply=is_first)
                is_first = False
                current_text = current_text[split_point:].lstrip()
            
            if current_text.strip():
                await send_text(current_text.strip(), is_reply=is_first)
        
        # Send view if provided (for retry button)
        if view:
            msg = await channel.send("​", view=view)  # Zero-width space
            if first_msg is None:
                first_msg = msg
        
        return first_msg
    
    def _chunk_content(self, content: str, limit: int = 1900) -> list[str]:
        """Split content into chunks"""
        if len(content) <= limit:
            return [content]
        
        chunks = []
        lines = content.split('\n')
        current = ""
        
        for line in lines:
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        
        if current:
            chunks.append(current)
        
        return chunks
    
    def _cleanup_temp(self, paths: list[str]):
        """Cleanup temp files"""
        for path in paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AskCog(bot))

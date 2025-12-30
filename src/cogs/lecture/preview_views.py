"""
Preview Views - Handle multi-document input and processing
"""
import discord
import asyncio
import logging
import os
from typing import Optional
from dataclasses import dataclass

from services import gemini, video_download, prompts
from services import slides as slides_service

logger = logging.getLogger(__name__)


@dataclass
class DocumentInfo:
    """Info about a single document"""
    path: str  # Local path to PDF
    original_path: str  # Original path or URL
    source: str  # "drive" or "upload"
    images: list[str] = None  # Converted page images
    
    def __post_init__(self):
        if self.images is None:
            self.images = []


class PreviewSourceView(discord.ui.View):
    """View with buttons to choose upload method"""
    
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
    
    @discord.ui.button(label="📤 Upload PDF", style=discord.ButtonStyle.primary)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Start upload flow"""
        self.choice = "upload"
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        # Start processor with upload flow
        processor = PreviewProcessor(
            interaction=interaction,
            guild_id=self.guild_id,
            user_id=self.user_id,
            source_type="upload",
        )
        await processor.collect_documents()
    
    @discord.ui.button(label="🔗 Google Drive", style=discord.ButtonStyle.secondary)
    async def drive_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show modal for Drive links"""
        modal = DriveLinksModal(self.guild_id, self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Đã đóng", embed=None, view=None)


class DriveLinksModal(discord.ui.Modal, title="Google Drive Links"):
    """Modal for entering multiple Drive links"""
    
    links_input = discord.ui.TextInput(
        label="Drive Links (mỗi link 1 dòng)",
        placeholder="https://drive.google.com/file/d/...\nhttps://drive.google.com/file/d/...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    
    def __init__(self, guild_id: int, user_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        # Parse links (one per line)
        links = [
            line.strip() 
            for line in self.links_input.value.strip().split('\n') 
            if line.strip() and 'drive.google.com' in line
        ]
        
        if not links:
            await interaction.response.send_message(
                "❌ Không tìm thấy link Drive hợp lệ.",
                ephemeral=True
            )
            return
        
        if len(links) > 5:
            await interaction.response.send_message(
                "❌ Tối đa 5 tài liệu. Vui lòng thử lại.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Start processor with drive links
        processor = PreviewProcessor(
            interaction=interaction,
            guild_id=self.guild_id,
            user_id=self.user_id,
            source_type="drive",
            drive_links=links,
        )
        await processor.process()


class PreviewProcessor:
    """Handles the preview processing pipeline"""
    
    def __init__(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        user_id: int,
        source_type: str,  # "upload" or "drive"
        drive_links: list[str] = None,
    ):
        self.interaction = interaction
        self.guild_id = guild_id
        self.user_id = user_id
        self.source_type = source_type
        self.drive_links = drive_links or []
        self.documents: list[DocumentInfo] = []
        self.status_msg: Optional[discord.WebhookMessage] = None
        self.temp_files: list[str] = []
    
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
        from services.video import cleanup_files
        cleanup_files(self.temp_files)
        self.temp_files = []
    
    async def collect_documents(self):
        """Collect documents from user uploads"""
        await self.update_status(
            "📎 **Upload PDF files** (1-5 files, mỗi file gửi riêng)\n"
            "Gửi `done` khi hoàn tất hoặc đợi 2 phút."
        )
        
        collected = []
        
        def check(m):
            if m.author.id != self.user_id or m.channel.id != self.interaction.channel.id:
                return False
            # Check for "done" message or PDF attachments
            if m.content.lower().strip() == 'done':
                return True
            if m.attachments and any(a.filename.lower().endswith('.pdf') for a in m.attachments):
                return True
            return False
        
        try:
            deadline = asyncio.get_event_loop().time() + 120  # 2 minute deadline
            
            while len(collected) < 5:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                
                try:
                    msg = await self.interaction.client.wait_for(
                        "message", check=check, timeout=min(remaining, 60)
                    )
                    
                    # Check for "done"
                    if msg.content.lower().strip() == 'done':
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        break
                    
                    # Process PDF attachment
                    pdf_found = False
                    for attachment in msg.attachments:
                        if attachment.filename.lower().endswith('.pdf') and len(collected) < 5:
                            pdf_found = True
                            file_path = f"/tmp/preview_{self.user_id}_{len(collected)}_{attachment.filename}"
                            file_bytes = await attachment.read()
                            
                            with open(file_path, 'wb') as f:
                                f.write(file_bytes)
                            
                            collected.append(DocumentInfo(
                                path=file_path,
                                original_path=file_path,
                                source="upload",
                            ))
                            self.temp_files.append(file_path)
                            
                            await self.update_status(
                                f"✅ Đã nhận {len(collected)} file(s)\n"
                                f"Tiếp tục upload hoặc gửi `done` để xử lý."
                            )
                    
                    # Show error if no PDF found but files were attached
                    if not pdf_found and msg.attachments:
                        file_ext = msg.attachments[0].filename.split('.')[-1] if '.' in msg.attachments[0].filename else 'unknown'
                        await self.update_status(
                            f"⚠️ File `.{file_ext}` không hợp lệ - chỉ nhận **PDF** (.pdf)\n"
                            f"Đã nhận {len(collected)} file(s). Tiếp tục upload PDF hoặc gửi `done`."
                        )
                    
                    # Delete user's message
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    
                except asyncio.TimeoutError:
                    break  # Timeout, process what we have
        
        except Exception as e:
            logger.exception("Error collecting documents")
            await self.update_status(f"❌ Lỗi: {str(e)[:100]}")
            return
        
        if not collected:
            await self.update_status("❌ Không nhận được file nào. Vui lòng thử lại.")
            return
        
        self.documents = collected
        await self.process()
    
    async def process(self):
        """Main processing pipeline"""
        from services import config as config_service
        
        try:
            user_gemini_key = config_service.get_user_gemini_api(self.user_id)
            
            # ==================================
            # STAGE 1: Download Drive files (if any)
            # ==================================
            if self.source_type == "drive" and self.drive_links:
                await self.update_status(f"⏳ Đang tải {len(self.drive_links)} file từ Drive...")
                
                for i, link in enumerate(self.drive_links):
                    try:
                        pdf_path = f"/tmp/preview_drive_{self.user_id}_{i}.pdf"
                        await video_download.download_video(link, pdf_path)
                        
                        self.documents.append(DocumentInfo(
                            path=pdf_path,
                            original_path=link,
                            source="drive",
                        ))
                        self.temp_files.append(pdf_path)
                        
                        await self.update_status(f"✅ Đã tải {i+1}/{len(self.drive_links)} file")
                    except Exception as e:
                        logger.warning(f"Failed to download {link}: {e}")
                        await self.update_status(f"⚠️ Lỗi tải file {i+1}: {str(e)[:50]}")
            
            if not self.documents:
                await self.update_status("❌ Không có tài liệu nào để xử lý.")
                return
            
            # ==================================
            # STAGE 2: Convert PDFs to images (parallel)
            # ==================================
            await self.update_status(f"⏳ Đang xử lý {len(self.documents)} tài liệu...")
            
            # Start Gemini API call while converting
            # Build document files for Gemini
            pdf_files = [doc.path for doc in self.documents]
            
            # Run Gemini API call and PDF conversion in parallel
            async def call_gemini():
                """Call Gemini with all PDF files using shared service"""
                return await gemini.summarize_pdfs(
                    pdf_paths=pdf_files,
                    prompt=prompts.PREVIEW_SLIDES_PROMPT,
                    api_key=user_gemini_key,
                    thinking_level="high",
                )
            
            async def convert_pdfs():
                """Convert all PDFs to images"""
                for doc in self.documents:
                    try:
                        doc.images = slides_service.pdf_to_images(doc.path)
                        logger.info(f"Converted {doc.path}: {len(doc.images)} pages")
                    except Exception as e:
                        logger.warning(f"Failed to convert {doc.path}: {e}")
                        doc.images = []
            
            # Run in parallel
            await self.update_status("⏳ Đang gọi Gemini API và convert PDF...")
            gemini_task = asyncio.create_task(call_gemini())
            convert_task = asyncio.create_task(convert_pdfs())
            
            # Wait for both
            summary, _ = await asyncio.gather(gemini_task, convert_task)
            
            # ==================================
            # STAGE 3: Parse and send output
            # ==================================
            await self.update_status("⏳ Đang gửi kết quả...")
            
            # Parse multi-doc page markers
            parsed_parts = parse_multi_doc_pages(summary)
            
            # Build doc_images dict for sending
            doc_images = {}
            for i, doc in enumerate(self.documents, 1):
                doc_images[i] = doc.images
            
            # Send with embedded slides
            await send_chunked_with_multi_doc_pages(
                self.interaction.channel,
                parsed_parts,
                doc_images,
            )
            
            # ==================================
            # STAGE 4: Send original files footer
            # ==================================
            # Send Drive links as footer
            drive_docs = [d for d in self.documents if d.source == "drive"]
            if drive_docs:
                links_text = "\n".join([f"• <{d.original_path}>" for d in drive_docs])
                await self.interaction.channel.send(f"📄 **Tài liệu gốc:**\n{links_text}")
            
            # Re-upload uploaded files
            upload_docs = [d for d in self.documents if d.source == "upload"]
            for doc in upload_docs[:3]:  # Max 3 files to avoid spam
                try:
                    if os.path.exists(doc.path):
                        filename = os.path.basename(doc.path)
                        # Remove prefix
                        if filename.startswith("preview_"):
                            parts = filename.split("_", 3)
                            if len(parts) > 3:
                                filename = parts[3]
                        
                        file = discord.File(doc.path, filename=filename)
                        await self.interaction.channel.send("📄 **Tài liệu:**", file=file)
                except Exception as e:
                    logger.warning(f"Failed to re-upload {doc.path}: {e}")
            
            await self.update_status("✅ Hoàn thành!")
            self.cleanup()
            
        except Exception as e:
            logger.exception("Preview processing failed")
            error_msg = str(e)[:200]
            
            # Show retry view
            view = PreviewErrorView(self)
            await self.update_status(f"❌ Lỗi: {error_msg}")
            await self.interaction.followup.send(
                f"❌ **Lỗi xử lý:** {error_msg}\n\nBạn có thể thử lại hoặc đổi API key.",
                view=view,
                ephemeral=True,
            )


class PreviewErrorView(discord.ui.View):
    """View shown on processing error with retry options"""
    
    def __init__(self, processor: PreviewProcessor):
        super().__init__(timeout=300)
        self.processor = processor
    
    @discord.ui.button(label="🔄 Thử lại", style=discord.ButtonStyle.primary)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Retry processing"""
        await interaction.response.defer(ephemeral=True)
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        
        # Retry
        await self.processor.process()
    
    @discord.ui.button(label="🔑 Đổi API Key", style=discord.ButtonStyle.secondary)
    async def change_api_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open API key modal"""
        from cogs.lecture.cog import GeminiApiModal
        modal = GeminiApiModal(self.processor.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="❌ Đóng", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close error view"""
        self.processor.cleanup()
        await interaction.response.edit_message(content="✅ Đã đóng", view=None)


def parse_multi_doc_pages(text: str) -> list[tuple[str, int | None, int | None]]:
    """
    Parse text and split at [-DOC{N}:PAGE:{X}-] markers.
    
    Returns list of tuples: (text_chunk, doc_number, page_number)
    Example: "Hello [-DOC1:PAGE:5-] World" -> [("Hello ", 1, 5), (" World", None, None)]
    """
    import re
    
    # Pattern: [-DOC1:PAGE:5-] or [-DOC2:PAGE:10-]
    pattern = r'\[-DOC(\d+):PAGE:(\d+)-\]'
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Text before this marker
        text_before = text[last_end:match.start()]
        doc_num = int(match.group(1))
        page_num = int(match.group(2))
        
        if text_before.strip():
            parts.append((text_before, doc_num, page_num))
        else:
            parts.append(("", doc_num, page_num))
        
        last_end = match.end()
    
    # Remaining text after last marker
    remaining = text[last_end:]
    if remaining.strip():
        parts.append((remaining, None, None))
    
    # If no markers found, return original text
    if not parts:
        parts.append((text, None, None))
    
    return parts


async def send_chunked_with_multi_doc_pages(
    channel: discord.TextChannel,
    parsed_parts: list[tuple[str, int | None, int | None]],
    doc_images: dict[int, list[str]],  # {doc_num: [image_paths]}
    chunk_size: int = 1900,
):
    """
    Send text chunks with embedded slide images from multiple documents.
    
    Args:
        channel: Discord channel to send to
        parsed_parts: List of (text, doc_num, page_num) tuples from parse_multi_doc_pages
        doc_images: Dict mapping doc number to list of image paths
        chunk_size: Max characters per message
    """
    current_text = ""
    
    for text_chunk, doc_num, page_num in parsed_parts:
        # Add text to current buffer
        current_text += text_chunk
        
        # If we have a page marker, send current text + image
        if doc_num is not None and page_num is not None:
            # Send accumulated text first
            if current_text.strip():
                # Split if too long
                while len(current_text) > chunk_size:
                    split_point = current_text.rfind('\n', 0, chunk_size)
                    if split_point == -1:
                        split_point = chunk_size
                    
                    await channel.send(current_text[:split_point])
                    current_text = current_text[split_point:].lstrip()
                
                if current_text.strip():
                    await channel.send(current_text.strip())
                current_text = ""
            
            # Send image if available
            images = doc_images.get(doc_num, [])
            if images and 0 < page_num <= len(images):
                image_path = images[page_num - 1]  # 1-indexed
                if os.path.exists(image_path):
                    try:
                        file = discord.File(image_path, filename=f"doc{doc_num}_page{page_num}.png")
                        await channel.send(file=file)
                    except Exception as e:
                        logger.warning(f"Failed to send image doc{doc_num} page{page_num}: {e}")
    
    # Send any remaining text
    if current_text.strip():
        while len(current_text) > chunk_size:
            split_point = current_text.rfind('\n', 0, chunk_size)
            if split_point == -1:
                split_point = chunk_size
            
            await channel.send(current_text[:split_point])
            current_text = current_text[split_point:].lstrip()
        
        if current_text.strip():
            await channel.send(current_text.strip())

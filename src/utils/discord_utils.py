"""
Discord Utilities
"""

import asyncio
import re
from typing import Union

import discord


def suppress_url_embeds(text: str) -> str:
    """
    Wrap URLs in angle brackets to suppress Discord's auto-embed previews.
    
    https://example.com → <https://example.com>
    Already wrapped URLs are left unchanged.
    """
    # Pattern to match URLs not already wrapped in < >
    # Negative lookbehind for < and negative lookahead for >
    url_pattern = r'(?<![<\(])(https?://[^\s\)<>]+)(?![>\)])'
    
    def wrap_url(match):
        url = match.group(1)
        return f'<{url}>'
    
    return re.sub(url_pattern, wrap_url, text)


async def send_chunked(
    target: Union[discord.Interaction, discord.TextChannel],
    text: str,
    chunk_size: int = 1900,  # Slightly less than 2000 for safety
    suppress_embeds: bool = True,  # Wrap URLs to prevent Discord embeds
) -> list[discord.Message]:
    """
    Send a long message in chunks to avoid Discord's 2000 char limit.
    Splits by newlines to keep text coherent.
    """
    if not text:
        return []
    
    # Suppress URL embeds if enabled
    if suppress_embeds:
        text = suppress_url_embeds(text)

    chunks = []
    current_chunk = ""
    
    # split by lines to avoid cutting sentences
    lines = text.split('\n')
    
    for line in lines:
        # If line itself is too long, we must split it by chars
        if len(line) > chunk_size:
            # If we have content pending, flush it first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            
            # Split long line
            for i in range(0, len(line), chunk_size):
                chunks.append(line[i : i + chunk_size])
            continue
            
        # Check if adding this line would exceed chunk size
        # +1 for newline character that was stripped by split
        if len(current_chunk) + len(line) + 1 > chunk_size:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line
    
    if current_chunk:
        chunks.append(current_chunk)

    sent_messages = []
    
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
            
        if isinstance(target, discord.Interaction):
            if i == 0 and not target.response.is_done():
                await target.response.send_message(chunk)
                msg = await target.original_response()
                sent_messages.append(msg)
            else:
                msg = await target.followup.send(chunk)
                sent_messages.append(msg)
        else:
            msg = await target.send(chunk)
            sent_messages.append(msg)

        # Rate limit protection
        if i < len(chunks) - 1:
            await asyncio.sleep(0.5)
            
    return sent_messages


async def send_chunked_with_frames(
    channel: discord.TextChannel,
    parts: list[tuple[str, int | None]],
    video_path: str,
    chunk_size: int = 1900,
) -> list[str]:
    """
    Send text chunks with embedded frame images.
    
    Args:
        channel: Discord channel to send to
        parts: List of (text, frame_seconds or None) from parse_frames_and_text
        video_path: Path to video file for frame extraction
        chunk_size: Max chars per message
        
    Returns:
        tuple[list[str], list[discord.Message]]: (frame_paths, sent_messages)
    """
    from services.video import extract_frame
    
    frame_paths = []
    sent_messages = []
    
    for text, frame_seconds in parts:
        # Send text chunk(s)
        if text.strip():
            msgs = await send_chunked(channel, text, chunk_size)
            sent_messages.extend(msgs)
        
        # Extract and send frame if specified
        if frame_seconds is not None:
            frame_path = await extract_frame(video_path, frame_seconds)
            if frame_path:
                frame_paths.append(frame_path)
                try:
                    file = discord.File(frame_path)
                    msg = await channel.send(file=file)
                    sent_messages.append(msg)
                    await asyncio.sleep(0.5)  # Rate limit
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to send frame: {e}")
    
    return frame_paths, sent_messages


async def send_chunked_with_pages(
    channel: discord.TextChannel,
    parts: list[tuple[str, int | None, str | None]],
    slide_images: list[str],
    latex_images: list[tuple[str, str]] | None = None,
    chunk_size: int = 1900,
) -> list[discord.Message]:
    """
    Send text chunks with embedded slide page images and LaTeX formula images.
    
    Args:
        channel: Discord channel to send to
        parts: List of (text, page_number or None, description or None) from parse_pages_and_text
        slide_images: List of slide image paths (0-indexed)
        latex_images: Optional list of (placeholder, image_path) for LaTeX formulas
        chunk_size: Max chars per message
    """
    from services.slides import get_page_image
    import os
    import logging
    logger = logging.getLogger(__name__)
    
    # Build a lookup dict for LaTeX images
    latex_lookup = {placeholder: path for placeholder, path in (latex_images or [])}
    
    # Collect all messages sent
    sent_messages = []

    async def send_text_with_latex(text: str):
        """Send text, replacing any LaTeX placeholders with images"""
        if not latex_lookup:
            msgs = await send_chunked(channel, text, chunk_size)
            sent_messages.extend(msgs)
            return
        
        remaining = text
        for placeholder, img_path in (latex_images or []):
            if placeholder in remaining:
                parts_split = remaining.split(placeholder, 1)
                if parts_split[0].strip():
                    msgs = await send_chunked(channel, parts_split[0], chunk_size)
                    sent_messages.extend(msgs)
                
                # Send LaTeX image
                if os.path.exists(img_path):
                    try:
                        file = discord.File(img_path, filename="formula.png")
                        msg = await channel.send(file=file)
                        sent_messages.append(msg)
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.warning(f"Failed to send LaTeX image: {e}")
                
                remaining = parts_split[1] if len(parts_split) > 1 else ""
        
        if remaining.strip():
            msgs = await send_chunked(channel, remaining, chunk_size)
            sent_messages.extend(msgs)
    
    for part in parts:
        # Handle both old (text, page_num) and new (text, page_num, desc) formats
        if len(part) == 2:
            text, page_num = part
            description = None
        else:
            text, page_num, description = part
        
        # Send text chunk(s) with LaTeX images
        if text.strip():
            await send_text_with_latex(text)
        
        # Send slide image if specified
        if page_num is not None and slide_images:
            image_path = get_page_image(slide_images, page_num)
            if image_path:
                try:
                    file = discord.File(image_path, filename=f"slide_{page_num}.jpg")
                    # Include description in caption if available
                    if description:
                        caption = f"📄 **Slide {page_num}**\n*({description})*"
                    else:
                        caption = f"📄 **Slide {page_num}**"
                    msg = await channel.send(caption, file=file)
                    sent_messages.append(msg)
                    await asyncio.sleep(0.5)  # Rate limit
                except Exception as e:
                    logger.warning(f"Failed to send slide {page_num}: {e}")
    
    # Cleanup LaTeX images after sending
    for _, img_path in (latex_images or []):
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
        except Exception:
            pass
            
    return sent_messages

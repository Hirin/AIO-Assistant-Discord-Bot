"""
Discord Utilities
"""

import asyncio
from typing import Union

import discord


async def send_chunked(
    target: Union[discord.Interaction, discord.TextChannel],
    text: str,
    chunk_size: int = 1900,  # Slightly less than 2000 for safety
) -> None:
    """
    Send a long message in chunks to avoid Discord's 2000 char limit.
    Splits by newlines to keep text coherent.
    """
    if not text:
        return

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

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
            
        if isinstance(target, discord.Interaction):
            if i == 0 and not target.response.is_done():
                await target.response.send_message(chunk)
            else:
                await target.followup.send(chunk)
        else:
            await target.send(chunk)

        # Rate limit protection
        if i < len(chunks) - 1:
            await asyncio.sleep(0.5)


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
        List of extracted frame paths for cleanup
    """
    from services.video import extract_frame
    
    frame_paths = []
    
    for text, frame_seconds in parts:
        # Send text chunk(s)
        if text.strip():
            await send_chunked(channel, text, chunk_size)
        
        # Extract and send frame if specified
        if frame_seconds is not None:
            frame_path = await extract_frame(video_path, frame_seconds)
            if frame_path:
                frame_paths.append(frame_path)
                try:
                    file = discord.File(frame_path)
                    await channel.send(file=file)
                    await asyncio.sleep(0.5)  # Rate limit
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to send frame: {e}")
    
    return frame_paths


async def send_chunked_with_pages(
    channel: discord.TextChannel,
    parts: list[tuple[str, int | None]],
    slide_images: list[str],
    chunk_size: int = 1900,
) -> None:
    """
    Send text chunks with embedded slide page images.
    
    Args:
        channel: Discord channel to send to
        parts: List of (text, page_number or None) from parse_pages_and_text
        slide_images: List of slide image paths (0-indexed)
        chunk_size: Max chars per message
    """
    from services.slides import get_page_image
    
    for text, page_num in parts:
        # Send text chunk(s)
        if text.strip():
            await send_chunked(channel, text, chunk_size)
        
        # Send slide image if specified
        if page_num is not None and slide_images:
            image_path = get_page_image(slide_images, page_num)
            if image_path:
                try:
                    file = discord.File(image_path, filename=f"slide_{page_num}.jpg")
                    await channel.send(f"📄 **Slide {page_num}**", file=file)
                    await asyncio.sleep(0.5)  # Rate limit
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to send slide {page_num}: {e}")

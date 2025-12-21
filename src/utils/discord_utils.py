"""
Discord Utilities
"""
import asyncio
from typing import Union

import discord


async def send_chunked(
    target: Union[discord.Interaction, discord.TextChannel],
    text: str,
    chunk_size: int = 2000
) -> None:
    """
    Send a long message in chunks to avoid Discord's 2000 char limit.
    Includes rate limit protection with 0.1s delay between chunks.
    """
    if not text:
        return
    
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        if isinstance(target, discord.Interaction):
            if i == 0:
                await target.followup.send(chunk)
            else:
                await target.followup.send(chunk)
        else:
            await target.send(chunk)
        
        # Rate limit protection
        if i < len(chunks) - 1:
            await asyncio.sleep(0.1)

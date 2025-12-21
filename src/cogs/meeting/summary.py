"""
Meeting Summary Command
/meeting summary <url> - Summarize a Fireflies meeting
"""
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from services import fireflies, llm
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)


class Meeting(commands.GroupCog, name="meeting"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
    
    @app_commands.command(name="summary", description="Summarize a Fireflies meeting")
    @app_commands.describe(url="Fireflies meeting URL")
    async def summary(self, interaction: discord.Interaction, url: str):
        start_time = time.time()
        request_id = f"{interaction.id}"
        
        logger.info(f"[{request_id}] Meeting summary requested by {interaction.user}")
        
        # Validate URL
        if "fireflies.ai" not in url:
            await interaction.response.send_message(
                "❌ Vui lòng cung cấp link Fireflies.ai hợp lệ",
                ephemeral=True
            )
            return
        
        # Defer response immediately
        await interaction.response.defer(thinking=True)
        
        try:
            # Step 1: Scrape transcript
            logger.info(f"[{request_id}] Scraping transcript...")
            transcript_data = await fireflies.scrape_fireflies(url)
            
            if not transcript_data:
                await interaction.followup.send(
                    "❌ Không thể lấy transcript từ link này. "
                    "Vui lòng kiểm tra link hoặc thử lại sau."
                )
                return
            
            # Format transcript for LLM
            transcript_text = fireflies.format_transcript(transcript_data)
            logger.info(f"[{request_id}] Transcript: {len(transcript_data)} entries, {len(transcript_text)} chars")
            
            # Step 2: Summarize with LLM
            logger.info(f"[{request_id}] Generating summary...")
            summary = await llm.summarize_transcript(transcript_text)
            
            if not summary:
                # Fallback: return template
                logger.warning(f"[{request_id}] LLM failed, using fallback template")
                summary = llm.get_fallback_template()
            
            # Step 3: Send result
            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[{request_id}] Completed in {latency_ms}ms")
            
            # Add header
            header = f"📋 **Meeting Summary**\n🔗 {url[:50]}...\n\n"
            full_response = header + summary
            
            # Send (chunked if needed)
            await send_chunked(interaction, full_response)
            
        except Exception as e:
            logger.exception(f"[{request_id}] Error in meeting summary")
            await interaction.followup.send(
                f"❌ Có lỗi xảy ra: {str(e)[:100]}"
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Meeting(bot))

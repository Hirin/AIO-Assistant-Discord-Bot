"""
Meeting Commands
/meeting list - List recent meetings
/meeting summary <id_or_url> - Summarize a meeting
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from services import fireflies, fireflies_api, llm
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)


class Meeting(commands.GroupCog, name="meeting"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="list", description="List your recent meetings")
    @app_commands.describe(limit="Number of meetings to show (default: 5)")
    async def list_meetings(self, interaction: discord.Interaction, limit: int = 5):
        """List recent meetings from Fireflies API"""
        await interaction.response.defer(thinking=True)

        try:
            transcripts = await fireflies_api.list_transcripts(
                guild_id=interaction.guild_id, limit=min(limit, 10)
            )

            if not transcripts:
                await interaction.followup.send(
                    "❌ Không tìm thấy meetings. "
                    "Hãy đảm bảo đã config Fireflies API key với `/config set-api fireflies <key>`"
                )
                return

            embed = discord.Embed(
                title="📋 Recent Meetings",
                color=discord.Color.blue(),
            )

            for t in transcripts:
                # Format duration
                duration = t.get("duration", 0)
                mins = int(duration // 60)

                # Format date
                date_str = t.get("date", "")[:10] if t.get("date") else "N/A"

                embed.add_field(
                    name=f"📝 {t['title'][:50]}",
                    value=(
                        f"**ID:** `{t['id']}`\n"
                        f"**Date:** {date_str} | **Duration:** {mins} min"
                    ),
                    inline=False,
                )

            embed.set_footer(text="Dùng /meeting summary <ID> để xem tóm tắt")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception("Error listing meetings")
            await interaction.followup.send(f"❌ Có lỗi xảy ra: {str(e)[:100]}")

    @app_commands.command(name="summary", description="Summarize a meeting")
    @app_commands.describe(id_or_url="Fireflies meeting ID or shared URL")
    async def summary(self, interaction: discord.Interaction, id_or_url: str):
        """Summarize a meeting by ID (API) or URL (scraping)"""
        start_time = time.time()
        request_id = f"{interaction.id}"

        logger.info(f"[{request_id}] Meeting summary requested by {interaction.user}")

        await interaction.response.defer(thinking=True)

        try:
            # Detect: URL or ID
            is_url = id_or_url.startswith("http")

            if is_url:
                # Validate Fireflies URL
                if "fireflies.ai" not in id_or_url:
                    await interaction.followup.send(
                        "❌ Vui lòng cung cấp link Fireflies.ai hoặc meeting ID",
                        ephemeral=True,
                    )
                    return

                # Scraping method
                logger.info(f"[{request_id}] Scraping transcript from URL...")
                transcript_data = await fireflies.scrape_fireflies(id_or_url)
                source = "scraping"
            else:
                # API method
                logger.info(f"[{request_id}] Getting transcript from API...")
                transcript_data = await fireflies_api.get_transcript_by_id(
                    id_or_url, guild_id=interaction.guild_id
                )
                source = "api"

            if not transcript_data:
                await interaction.followup.send(
                    "❌ Không thể lấy transcript. "
                    "Kiểm tra ID/URL hoặc config Fireflies API key."
                )
                return

            # Format transcript for LLM
            transcript_text = fireflies.format_transcript(transcript_data)
            logger.info(
                f"[{request_id}] Transcript ({source}): {len(transcript_data)} entries, {len(transcript_text)} chars"
            )

            # Summarize with LLM
            logger.info(f"[{request_id}] Generating summary...")
            summary = await llm.summarize_transcript(
                transcript_text, guild_id=interaction.guild_id
            )

            if not summary:
                logger.warning(f"[{request_id}] LLM failed, using fallback")
                summary = llm.get_fallback_template()

            # Send result
            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[{request_id}] Completed in {latency_ms}ms")

            header = (
                f"📋 **Meeting Summary** (via {source})\n🔗 `{id_or_url[:50]}...`\n\n"
            )
            await send_chunked(interaction, header + summary)

        except Exception as e:
            logger.exception(f"[{request_id}] Error in meeting summary")
            await interaction.followup.send(f"❌ Có lỗi xảy ra: {str(e)[:100]}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Meeting(bot))

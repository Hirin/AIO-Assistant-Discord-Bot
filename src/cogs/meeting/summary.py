"""
Meeting Command - Single command with dropdown
/meeting
"""

import logging
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from services import fireflies, fireflies_api, llm
from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)


class MeetingIdModal(discord.ui.Modal, title="Meeting Summary"):
    """Modal for entering meeting ID or URL"""

    id_or_url = discord.ui.TextInput(
        label="Meeting ID or Fireflies URL",
        style=discord.TextStyle.short,
        placeholder="01K94... hoặc https://app.fireflies.ai/view/...",
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        id_or_url = self.id_or_url.value
        start_time = time.time()

        try:
            is_url = id_or_url.startswith("http")

            if is_url:
                if "fireflies.ai" not in id_or_url:
                    await interaction.followup.send("❌ Link không hợp lệ")
                    return
                transcript_data = await fireflies.scrape_fireflies(id_or_url)
                source = "scraping"
            else:
                transcript_data = await fireflies_api.get_transcript_by_id(
                    id_or_url, guild_id=self.guild_id
                )
                source = "api"

            if not transcript_data:
                await interaction.followup.send("❌ Không lấy được transcript")
                return

            transcript_text = fireflies.format_transcript(transcript_data)
            summary = await llm.summarize_transcript(
                transcript_text, guild_id=self.guild_id
            )

            if not summary:
                summary = "⚠️ LLM error"
            await send_chunked(interaction, summary)

        except Exception as e:
            logger.exception("Error in meeting summary")
            await interaction.followup.send(f"❌ Lỗi: {str(e)[:100]}")


class MeetingView(discord.ui.View):
    """Dropdown view for meeting actions"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.select(
        placeholder="Chọn action...",
        options=[
            discord.SelectOption(label="List Meetings", value="list", emoji="📋"),
            discord.SelectOption(
                label="Summarize Meeting", value="summary", emoji="📝"
            ),
        ],
    )
    async def select_action(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        action = select.values[0]

        if action == "list":
            await interaction.response.defer(thinking=True)

            try:
                transcripts = await fireflies_api.list_transcripts(
                    guild_id=self.guild_id, limit=5
                )

                if not transcripts:
                    await interaction.followup.send(
                        "❌ Không tìm thấy meetings. Kiểm tra Fireflies API key."
                    )
                    return

                embed = discord.Embed(
                    title="📋 Recent Meetings", color=discord.Color.blue()
                )

                for t in transcripts:
                    duration = t.get("duration", 0) or 0
                    mins = int(duration // 60)

                    date_val = t.get("date", "")
                    if isinstance(date_val, (int, float)):
                        date_str = datetime.fromtimestamp(date_val / 1000).strftime(
                            "%Y-%m-%d"
                        )
                    elif isinstance(date_val, str) and date_val:
                        date_str = date_val[:10]
                    else:
                        date_str = "N/A"

                    embed.add_field(
                        name=f"📝 {t['title'][:40]}",
                        value=f"ID: `{t['id']}`\n{date_str} | {mins}min",
                        inline=False,
                    )

                await interaction.followup.send(embed=embed)

            except Exception as e:
                logger.exception("Error listing meetings")
                await interaction.followup.send(f"❌ Lỗi: {str(e)[:100]}")

        elif action == "summary":
            await interaction.response.send_modal(MeetingIdModal(self.guild_id))


class Meeting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_messages: dict[int, discord.Message] = {}

    @app_commands.command(name="meeting", description="Meeting tools")
    async def meeting(self, interaction: discord.Interaction):
        """Show meeting options"""
        if not interaction.guild_id:
            await interaction.response.send_message(
                "❌ Chỉ dùng trong server", ephemeral=True
            )
            return

        # Delete previous dropdown
        user_id = interaction.user.id
        if user_id in self._active_messages:
            try:
                await self._active_messages[user_id].delete()
            except Exception:
                pass

        view = MeetingView(interaction.guild_id)
        await interaction.response.send_message(
            "📋 **Meeting** - Chọn action:",
            view=view,
            delete_after=60,
        )

        self._active_messages[user_id] = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Meeting(bot))

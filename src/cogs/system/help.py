"""
Help Command
"""

import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📚 Commands", color=discord.Color.blue())

        embed.add_field(
            name="/config",
            value=(
                "`api <type> <key>` - Set API key\n"
                "`prompt set|view|reset` - LLM prompt\n"
                "`info` - View config"
            ),
            inline=False,
        )

        embed.add_field(
            name="/meeting",
            value=(
                "`list` - List recent meetings\n`summary <id|url>` - Summarize meeting"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))

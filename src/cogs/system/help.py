"""
Help Command - List all available commands
"""
import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="help", description="Show all available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Available Commands",
            color=discord.Color.blue()
        )
        
        # System commands
        embed.add_field(
            name="🔧 System",
            value=(
                "`/ping` - Check bot latency\n"
                "`/help` - Show this help message"
            ),
            inline=False
        )
        
        # Meeting commands
        embed.add_field(
            name="📋 Meeting",
            value=(
                "`/meeting summary <url>` - Summarize a Fireflies meeting"
            ),
            inline=False
        )
        
        embed.set_footer(text="Use slash commands to interact with the bot")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))

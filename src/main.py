"""
Discord Bot - Entry Point
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from bot import DiscordBot


def main():
    load_dotenv()
    
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN not found in environment")
        sys.exit(1)
    
    bot = DiscordBot()
    bot.run(token)


if __name__ == "__main__":
    main()

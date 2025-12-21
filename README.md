# Discord Bot

Discord bot với Python + Docker, hỗ trợ meeting summary.

## Features
- `/ping` - Check latency
- `/help` - List commands  
- `/meeting summary <url>` - Tóm tắt meeting từ Fireflies

## Setup

```bash
# Local
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env  # Add tokens
python src/main.py

# Docker
docker compose up --build
```

## Env Variables

```
BOT_TOKEN=discord_token
GUILD_ID=test_server_id
GLM_API_KEY=z_ai_api_key
```
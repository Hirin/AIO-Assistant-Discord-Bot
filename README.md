# Discord Bot

Meeting summary bot với Fireflies + LLM.

## Commands

| Command | Options |
|---------|---------|
| `/help` | Show commands |
| `/config` | `api` `prompt` `info` |
| `/meeting` | `list` `summary` |

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium
cp .env.example .env && nano .env
python src/main.py
```

## Deploy

```bash
./deploy.sh
```

## Env Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Discord bot token |
| `GUILD_ID` | Test server ID |
| `GLM_API_KEY` | Z.AI API key |
| `FIREFLIES_API_KEY` | Fireflies API key |
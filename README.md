# Discord Bot

Discord bot với Python + Docker, hỗ trợ meeting summary.

## Features

| Command | Description |
|---------|-------------|
| `/ping` | Check bot latency |
| `/help` | List available commands |
| `/config set-api <type> <key>` | Set API key per server (Admin) |
| `/config show` | View current config |
| `/meeting list` | List recent meetings (Fireflies API) |
| `/meeting summary <id\|url>` | Summarize meeting by ID or shared URL |

## Setup

### Local Development

```bash
# Create venv with uv (recommended)
uv venv && source .venv/bin/activate

# Install dependencies (pinned with hashes)
uv pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your tokens

# Run
python src/main.py
```

### Docker

```bash
docker compose up --build
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Discord bot token |
| `GUILD_ID` | ❌ | Test server ID (faster sync) |
| `GLM_API_KEY` | ✅ | Z.AI API key for LLM |
| `GLM_MODEL` | ❌ | Model name (default: glm-4.6) |
| `FIREFLIES_API_KEY` | ❌ | Fireflies API key (for /meeting list) |

## Per-Server Configuration

Each server can configure their own API keys:

```
/config set-api glm <your_api_key>
/config set-api fireflies <your_api_key>
```

Keys are stored locally in `data/guild_configs.json` (gitignored).

## Project Structure

```
src/
├── main.py              # Entry point
├── bot.py               # Bot class, cog loader
├── cogs/
│   ├── system/          # ping, help, config
│   └── meeting/         # summary, list
├── services/
│   ├── fireflies.py     # Scraper (for shared URLs)
│   ├── fireflies_api.py # API client (for your meetings)
│   ├── llm.py           # GLM summarization
│   └── config.py        # Guild config storage
└── utils/
    └── discord_utils.py # Chunked sending
```
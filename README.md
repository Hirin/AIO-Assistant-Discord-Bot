# Discord Bot

Meeting summary bot với Fireflies.ai + GLM (Z.AI).

## Features

- 🎙️ **Join Meeting** - Bot tham gia và record Google Meet/Zoom
- 📝 **Summarize** - Tóm tắt meeting bằng LLM (tiếng Việt)
- 📎 **Document Upload** - Upload PDF tài liệu để trích xuất glossary, summary chi tiết hơn
- 📅 **Schedule** - Lên lịch join meeting tự động
- 💾 **Local Storage** - Lưu transcript local, auto xóa khỏi Fireflies

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Hiển thị danh sách commands |
| `/config` | Cấu hình API keys, prompts, channel |
| `/meeting` | Dropdown với: List, Summarize, Join, Schedule |

## Project Structure

```
src/
├── bot.py                 # Bot core + cog loader
├── main.py                # Entry point
├── cogs/
│   ├── meeting/           # Meeting commands
│   │   ├── __init__.py
│   │   ├── cog.py         # Meeting cog + View
│   │   ├── modals.py      # UI Modals
│   │   └── document_views.py  # Document upload UI
│   └── system/            # System commands
│       ├── config.py      # Config cog
│       └── help.py        # Help cog
├── services/
│   ├── config.py          # Guild config storage
│   ├── fireflies.py       # Fireflies scraper
│   ├── fireflies_api.py   # Fireflies GraphQL API
│   ├── llm.py             # GLM API (text + vision)
│   ├── scheduler.py       # Meeting scheduler
│   └── transcript_storage.py
└── utils/
    ├── discord_utils.py   # Discord helpers
    └── document_utils.py  # PDF → images conversion
```

## Setup

```bash
# Install dependencies
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
nano .env

# Run
python src/main.py
```

## Deploy (AWS)

```bash
./deploy.sh
```

## Bot Permissions

Required Discord permissions (integer: `274877975552`):

| Permission | Reason |
|------------|--------|
| Send Messages | Gửi summary, thông báo |
| Read Message History | Chờ file upload |
| Manage Messages | Xóa attachments sau khi xử lý |
| Use Application Commands | Slash commands |
| Embed Links | Embed messages |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Discord bot token |
| `GUILD_ID` | ❌ | Test server ID (instant sync) |
| `GLM_API_KEY` | ❌* | Z.AI API key |
| `GLM_MODEL` | ❌ | Text model (default: `glm-4.6`) |
| `GLM_VISION_MODEL` | ❌ | Vision model (default: `glm-4.6v-flash`) |
| `FIREFLIES_API_KEY` | ❌* | Fireflies API key |

> *Can be set per-guild via `/config`

## Supported Platforms

- Google Meet
- Zoom
- MS Teams
- [All Fireflies integrations](https://fireflies.ai/integrations)
# Discord Bot

Meeting summary bot với Fireflies.ai + GLM (Z.AI) và Lecture summarization với Gemini + AssemblyAI.

## Features

### Meeting (`/meeting`)
- 🎙️ **Join Meeting** - Bot tham gia và record Google Meet/Zoom
- 📝 **Meeting Summarize** - Tóm tắt transcript với **Gemini** (priority) hoặc GLM (fallback)
- 🧠 **Gemini Multimodal** - Xử lý slides PDF + transcript trong 1 call (khi có Gemini API key)
- 📎 **Document Upload** - Upload PDF slides, tích hợp trực tiếp vào Gemini (max 200 trang)
- 💾 **24h Slide Cache** - Cache VLM output cho fallback GLM
- 📅 **Schedule** - Lên lịch join meeting tự động
- 📥 **Archive Backup** - Backup transcripts vào Discord channel
- 🛡️ **Whitelist** - Bảo vệ transcripts quan trọng

### Lecture (`/lecture`)
- 🎬 **Video Summarize** - Tóm tắt video bài giảng từ Google Drive/Direct URL
- 🧠 **Gemini API** - Dùng Gemini 3 Flash với Thinking Mode
- 🎙️ **AssemblyAI** - Transcribe audio từ video (~100h free/month)
- 📄 **PDF Slides** - Upload slides minh họa (Drive link hoặc file)
- 💬 **Chat Session Upload** - Upload chat .txt với Q&A, community insights (auto filter junk)
- 🔗 **Smart URL Formatting** - Auto wrap URLs với `<>` để hide Discord embeds
- 🔢 **LaTeX Support** - Render block formulas $$...$$ to images, convert inline $...$ to Unicode
- 🔀 **Parallel Processing** - Download + Transcribe + Slides xử lý song song
- 💾 **Multi-stage Cache** - Cache video, transcript, slides, và part summaries
- 📄 **Slides Footer** - Auto attach Drive link hoặc re-upload file sau summary
- 📑 **Preview Mode** - Tóm tắt nhiều PDF trước buổi học (1-5 files)

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Hiển thị danh sách commands |
| `/config` | Cấu hình API keys, prompts, channels, limits |
| `/meeting` | Menu với các meeting actions |
| `/lecture` | Menu với Video/Transcript mode, Preview và API config |

### Meeting Actions

| Action | Description |
|--------|-------------|
| 📋 List from Fireflies | Xem transcripts trên Fireflies (có badge 🛡️ whitelist) |
| 📥 View Backup | Xem backup transcripts với pagination và ID |
| ✏️ Summarize | Tóm tắt từ ID/URL (Fireflies transcript) |
| 📝 Edit Title | Đổi tên transcript, re-upload backup với tên mới |
| 🚀 Join Now | Bot join meeting ngay |
| 📅 Schedule | Lên lịch join |
| 🛡️ Manage Whitelist | Toggle bảo vệ transcripts |

### Lecture Actions

| Action | Description |
|--------|-------------|
| 🎬 Video Mode | Tóm tắt từ video (Google Drive/Direct URL) với Gemini |
| � Transcript Mode | Tóm tắt từ Fireflies transcript (giống Meeting) |
| 📄 Preview Mode | Tóm tắt nhiều PDF documents (1-5 files) |
| 🔑 Config Gemini API | Set API key Gemini (per-user) |
| 🎙️ Config AssemblyAI API | Set API key AssemblyAI (per-user) |

## AI Features

| Feature | Description |
|---------|-------------|
| 🤖 **Deep Thinking** | VLM/LLM sử dụng thinking mode cho kết quả sâu hơn |
| 📄 **Gemini Multimodal Meeting** | Xử lý PDF slides + transcript trong 1 call (không cần VLM riêng) |
| 📄 **VLM Slide Extraction (GLM)** | Fallback: Trích xuất content từ slides với GLM-4.6V-Flash |
| 🎬 **Video + Slides + Transcript** | Gemini multimodal: video + images + text |
| � **Community Insights Extraction** | Tự động lọc và trích chat session (Q&A, explanations, links) |
| 🔗 **Smart URL Formatting** | Auto wrap external links với `<>` để hide Discord embeds |
| 🔢 **LaTeX Rendering** | Block formulas → images, inline formulas → Unicode symbols |
| �💾 **Multi-layer Cache** | Video, transcript, slides, part summaries đều được cache |
| ⏱️ **Timestamp/Slide Links** | Convert `[-123s-]` và `[-PAGE:X-]` markers |
| 🔄 **Error Recovery** | Retry buttons + Continue/Cancel options |

## Project Structure

```
src/
├── bot.py                     # Bot core + cog loader
├── main.py                    # Entry point
├── cogs/
│   ├── meeting/               # Meeting commands
│   │   ├── cog.py             # Meeting cog + Views
│   │   ├── modals.py          # UI Modals + ErrorRetryView
│   │   └── document_views.py  # Document upload + VLM
│   ├── lecture/               # Lecture commands
│   │   ├── cog.py             # Lecture cog + API config views
│   │   ├── video_views.py     # Video processing + error views
│   │   └── preview_views.py   # Multi-doc preview processing
│   └── system/                # System commands
│       ├── config.py          # Config cog + nested button views
│       └── help.py            # Help cog
├── services/
│   ├── config.py              # Guild config + per-user API keys
│   ├── prompts.py             # Meeting/Lecture VLM/LLM prompts
│   ├── fireflies.py           # Fireflies scraper
│   ├── fireflies_api.py       # Fireflies GraphQL API
│   ├── llm.py                 # GLM API (VLM + LLM with thinking)
│   ├── gemini.py              # Gemini API (multimodal + thinking)
│   ├── video.py               # Video processing (split, frames)
│   ├── video_download.py      # yt-dlp + Google Drive download
│   ├── assemblyai_transcript.py  # AssemblyAI transcription
│   ├── lecture_cache.py       # Multi-stage lecture caching
│   ├── slides.py              # PDF → images conversion
│   ├── scheduler.py           # Meeting scheduler + cache cleanup
│   ├── slide_cache.py         # 24h slide content caching
│   └── transcript_storage.py  # Local storage + archive
└── utils/
    ├── document_utils.py      # PDF → images (max 200 pages)
    └── discord_utils.py       # Chunked message sending + pages
```

## Meeting Summary Pipeline

```mermaid
flowchart TD
    subgraph User Input
        A["/meeting → Summarize"] --> B["Enter ID/URL + Title"]
        B --> C["📋 Meeting Mode"]
    end

    subgraph Document Upload
        C --> E{"Upload PDF?"}
        E -->|"Yes"| F["Wait for attachment"]
        E -->|"Skip"| L["No slide context"]
        F --> G{"Check Cache"}
        G -->|"Cache Hit"| H["Use cached content ⚡"]
        G -->|"Cache Miss"| I["Download PDF"]
        I --> J["PDF → Images"]
        J --> K["VLM Extract Slides"]
        K -->|"Success"| K1["Save to Cache 💾"]
        K -->|"Error"| K2["Show Retry/Cancel buttons"]
        K1 --> L
        H --> L
    end

    subgraph Transcript Retrieval
        L --> M{"Input Type"}
        M -->|"Fireflies ID"| N["Fireflies API"]
        M -->|"Local ID"| O["Local Backup"]
        M -->|"Share URL"| P["Scrape URL"]
        N -->|"Found"| Q["Get transcript"]
        N -->|"Not found"| O
        O --> Q
        P --> Q
    end

    subgraph LLM Summarization
        Q --> R["Format transcript"]
        R --> S{"User has Gemini key?"}
        S -->|"Yes"| S1["🧠 Gemini Multimodal"]
        S1 --> S1a{"Has PDF?"}
        S1a -->|"Yes"| S1b["Upload PDF + Transcript"]
        S1a -->|"No"| S1c["Transcript only"]
        S1b --> T1["Gemini 3 Flash + Thinking"]
        S1c --> T1
        T1 -->|"Success"| U["Process timestamps"]
        T1 -->|"Error"| T2["⚠️ Fallback to GLM"]
        
        S -->|"No key"| T["GLM + VLM slide content"]
        T2 --> T
        T -->|"Success"| U
        T -->|"Error 429"| V["Show Retry/Đóng buttons 🔄"]
        T -->|"Empty"| W["Retry automatically"]
        W --> T
        V -->|"Retry"| T
    end

    subgraph Output
        U --> X["Add header + metadata"]
        X --> Y["Send to channel 📤"]
        Y --> Z["Save to local backup"]
    end
```

## Lecture Video Pipeline

```mermaid
flowchart TD
    subgraph User Input
        A["/lecture → Summary"] --> B["🎬 Video Mode"]
        B --> C["Enter Google Drive/Direct URL + Title"]
        C --> D{"Add Slides PDF?"}
        D -->|"📤 Upload"| D1["Wait 90s for attachment"]
        D -->|"🔗 Drive"| D2["Enter Drive link"]
        D -->|"❌ Skip"| D3["No slides"]
        D1 --> E["slides_source = upload"]
        D2 --> E2["slides_source = drive"]
        D3 --> E3["slides_source = None"]
    end

    subgraph Stage 1 - Video Download
        E & E2 & E3 --> F{"Check Video Cache"}
        F -->|"Hit"| G["Use cached video ⚡"]
        F -->|"Miss"| H["Download video (yt-dlp)"]
        H --> I["Get duration + size"]
        I --> J["Calculate num_parts"]
        G --> K["video_path ready"]
        J --> K
    end

    subgraph Stage 2 - Parallel Processing
        K --> L["🔀 Run in Parallel"]
        
        L --> M1["📝 AssemblyAI Transcribe"]
        M1 --> M1a{"Cached?"}
        M1a -->|"Yes"| M1b["Use cached transcript"]
        M1a -->|"No"| M1c["Upload + Transcribe ~6min"]
        M1c --> M1d["Cache transcript"]
        
        L --> M2["📄 Process Slides"]
        M2 --> M2a{"Cached?"}
        M2a -->|"Yes"| M2b["Use cached images"]
        M2a -->|"No"| M2c["Download PDF"]
        M2c --> M2d["Convert to images"]
        M2d -->|"Error"| M2e["🔴 SlidesErrorView"]
        M2e -->|"Continue"| M2f["slides = empty"]
        M2e -->|"Retry"| M2c
        M2e -->|"Cancel"| CANCEL["❌ Abort"]
        M2d -->|"Success"| M2g["Cache slides"]
        
        L --> M3["✂️ Split Video"]
        M3 --> M3a{"Cached?"}
        M3a -->|"Yes"| M3b["Use cached parts"]
        M3a -->|"No"| M3c["FFmpeg split"]
        M3c --> M3d["Cache segments"]
    end

    subgraph Stage 3 - Gemini Summarization
        M1b & M1d --> N1["transcript ready"]
        M2b & M2g & M2f --> N2["slide_images ready"]
        M3b & M3d --> N3["parts ready"]
        
        N1 & N2 & N3 --> O["For each video part"]
        O --> P{"Check Part Cache"}
        P -->|"Hit"| Q["Use cached summary"]
        P -->|"Miss"| R["Build Gemini prompt"]
        R --> S["Add video + slides + transcript"]
        S --> T["🤖 Gemini with Thinking"]
        T -->|"Success"| U["Cache part summary"]
        T -->|"Error"| V["VideoErrorView 🔄"]
        V -->|"Retry"| T
        V -->|"Change API"| T
        U --> W{"More parts?"}
        Q --> W
        W -->|"Yes"| O
        W -->|"No"| X["Merge all summaries"]
    end

    subgraph Stage 4 - Final Merge
        X --> Y["🤖 Gemini Final Merge"]
        Y --> Z["Strip PAGE markers if no slides"]
    end

    subgraph Stage 5 - Output
        Z --> AA{"Has slide_images?"}
        AA -->|"Yes"| AB["Parse [-PAGE:X-] markers"]
        AB --> AC["Send text + images"]
        AA -->|"No"| AD["Send text only"]
        AC & AD --> AE{"slides_source?"}
        AE -->|"drive"| AF["📄 Send Drive link footer"]
        AE -->|"upload"| AG["📄 Re-upload PDF file"]
        AE -->|"None"| AH["Skip footer"]
        AF & AG & AH --> AI["✅ Cleanup + Done"]
    end
```

## Setup

```bash
uv sync
playwright install chromium
cp .env.example .env
nano .env
uv run python src/main.py
```

## Deploy (AWS)

```bash
AWS_HOST="ubuntu@your-ip" ./deploy.sh
```

## Bot Permissions

Required Discord permissions (integer: `274877975552`):

- Send Messages, Read Message History
- Manage Messages (xóa attachments)
- Use Application Commands
- Embed Links, Attach Files

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Discord bot token |
| `GUILD_ID` | ❌ | Test server ID (faster sync) |
| `GLM_API_KEY` | ❌* | Z.AI API key |
| `GLM_BASE_URL` | ❌ | Z.AI API base URL |
| `GLM_MODEL` | ❌ | LLM model (default: GLM-4.5-Flash) |
| `GLM_VISION_MODEL` | ❌ | VLM model (default: GLM-4.6V-Flash) |
| `FIREFLIES_API_KEY` | ❌* | Fireflies API key |

> *Can be set per-guild via `/config`

## Supported Platforms

Google Meet, Zoom, MS Teams, [+more](https://fireflies.ai/integrations)
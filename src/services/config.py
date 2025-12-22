"""
Guild Config Service
Store and retrieve per-guild configuration (API keys, settings)
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Config file path
CONFIG_FILE = Path(__file__).parent.parent.parent / "data" / "guild_configs.json"


def _ensure_config_file():
    """Ensure config file and directory exist"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text("{}")


def _load_configs() -> dict:
    """Load all guild configs from file"""
    _ensure_config_file()
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        logger.error(f"Failed to load configs: {e}")
        return {}


def _save_configs(configs: dict):
    """Save all guild configs to file"""
    _ensure_config_file()
    CONFIG_FILE.write_text(json.dumps(configs, indent=2))


def get_guild_config(guild_id: int) -> dict:
    """Get config for a specific guild"""
    configs = _load_configs()
    return configs.get(str(guild_id), {})


def set_guild_config(guild_id: int, key: str, value: str):
    """Set a config value for a guild"""
    configs = _load_configs()
    guild_key = str(guild_id)

    if guild_key not in configs:
        configs[guild_key] = {}

    configs[guild_key][key] = value
    _save_configs(configs)
    logger.info(f"Config set for guild {guild_id}: {key}")


def get_api_key(guild_id: int, key_type: str) -> Optional[str]:
    """Get API key for a guild, fallback to env if not set"""
    import os

    config = get_guild_config(guild_id)

    # Try guild-specific key first
    guild_key = config.get(f"{key_type}_api_key")
    if guild_key:
        return guild_key

    # Fallback to environment variable
    env_mapping = {
        "glm": "GLM_API_KEY",
        "fireflies": "FIREFLIES_API_KEY",
    }
    env_var = env_mapping.get(key_type)
    if env_var:
        return os.getenv(env_var)

    return None


def mask_key(key: str) -> str:
    """Mask API key for display"""
    if not key or len(key) < 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


DEFAULT_PROMPT = """Bạn là trợ lý tóm tắt cuộc họp chuyên nghiệp. 
Hãy tóm tắt cuộc họp theo cấu trúc:
## 📋 Tóm tắt tổng quan
(2-3 câu về nội dung chính)
## 🎯 Các điểm chính
- Điểm 1
- Điểm 2
...
## ✅ Quyết định & Action Items
- [Người] - Việc cần làm
## 📌 Ghi chú quan trọng
(Nếu có)
Hãy tóm tắt ngắn gọn, súc tích, bằng tiếng Việt."""


def get_custom_prompt(guild_id: int) -> str:
    """Get custom prompt for a guild, fallback to default"""
    config = get_guild_config(guild_id)
    return config.get("custom_prompt") or DEFAULT_PROMPT

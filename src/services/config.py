"""
Guild Config Service
Store and retrieve per-guild configuration (API keys, settings)
Also supports per-user settings (e.g., Gemini API key)
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Config file paths
CONFIG_FILE = Path(__file__).parent.parent.parent / "data" / "guild_configs.json"
USER_CONFIG_FILE = Path(__file__).parent.parent.parent / "data" / "user_configs.json"


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
        "gemini": "GEMINI_API_KEY",
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


# ============================================================================
# PER-USER CONFIG (for rate-limited APIs like Gemini)
# ============================================================================

def _ensure_user_config_file():
    """Ensure user config file exists"""
    USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not USER_CONFIG_FILE.exists():
        USER_CONFIG_FILE.write_text("{}")


def _load_user_configs() -> dict:
    """Load all user configs"""
    _ensure_user_config_file()
    try:
        return json.loads(USER_CONFIG_FILE.read_text())
    except Exception as e:
        logger.error(f"Failed to load user configs: {e}")
        return {}


def _save_user_configs(configs: dict):
    """Save all user configs"""
    _ensure_user_config_file()
    USER_CONFIG_FILE.write_text(json.dumps(configs, indent=2))


def get_user_gemini_api(user_id: int) -> Optional[str]:
    """Get user's personal Gemini API key"""
    import os
    
    configs = _load_user_configs()
    user_key = str(user_id)
    
    # Try user-specific key first
    user_config = configs.get(user_key, {})
    if user_config.get("gemini_api_key"):
        return user_config["gemini_api_key"]
    
    # Fallback to environment variable
    return os.getenv("GEMINI_API_KEY")


def set_user_gemini_api(user_id: int, api_key: str):
    """Set user's personal Gemini API key"""
    configs = _load_user_configs()
    user_key = str(user_id)
    
    if user_key not in configs:
        configs[user_key] = {}
    
    configs[user_key]["gemini_api_key"] = api_key
    _save_user_configs(configs)
    logger.info(f"Gemini API key set for user {user_id}")


def get_user_fireflies_api(user_id: int) -> Optional[str]:
    """Get user's personal Fireflies API key (no fallback to global)"""
    configs = _load_user_configs()
    user_key = str(user_id)
    
    user_config = configs.get(user_key, {})
    return user_config.get("fireflies_api_key")


def set_user_fireflies_api(user_id: int, api_key: str):
    """Set user's personal Fireflies API key"""
    configs = _load_user_configs()
    user_key = str(user_id)
    
    if user_key not in configs:
        configs[user_key] = {}
    
    configs[user_key]["fireflies_api_key"] = api_key
    _save_user_configs(configs)
    logger.info(f"Fireflies API key set for user {user_id}")


def get_user_assemblyai_api(user_id: int) -> Optional[str]:
    """Get user's personal AssemblyAI API key (no fallback to global)"""
    configs = _load_user_configs()
    user_key = str(user_id)
    
    user_config = configs.get(user_key, {})
    return user_config.get("assemblyai_api_key")


def set_user_assemblyai_api(user_id: int, api_key: str):
    """Set user's personal AssemblyAI API key"""
    configs = _load_user_configs()
    user_key = str(user_id)
    
    if user_key not in configs:
        configs[user_key] = {}
    
    configs[user_key]["assemblyai_api_key"] = api_key
    _save_user_configs(configs)
    logger.info(f"AssemblyAI API key set for user {user_id}")



def get_custom_prompt(guild_id: int) -> str:
    """
    Get custom prompt for a guild, fallback to default meeting prompt
    
    DEPRECATED: Use get_prompt(guild_id, "meeting", "summary") instead
    Kept for backward compatibility
    """
    from services.prompts import MEETING_SUMMARY_PROMPT
    
    config = get_guild_config(guild_id)
    # Check new config key first, fallback to old custom_prompt
    return (
        config.get("meeting_summary_prompt") 
        or config.get("custom_prompt") 
        or MEETING_SUMMARY_PROMPT
    )


def get_prompt(guild_id: int, mode: str, prompt_type: str) -> str:
    """
    Get prompt with fallback to default
    
    Args:
        guild_id: Guild ID
        mode: "meeting", "lecture", or "gemini"
        prompt_type: "vlm", "summary", "lecture_part1", "lecture_part_n", "merge"
    
    Returns:
        Custom prompt or default from prompts.py
    """
    from services.prompts import (
        MEETING_VLM_PROMPT, MEETING_SUMMARY_PROMPT,
        LECTURE_VLM_PROMPT, LECTURE_SUMMARY_PROMPT,
        GEMINI_LECTURE_PROMPT_PART1, GEMINI_LECTURE_PROMPT_PART_N, GEMINI_MERGE_PROMPT
    )
    
    config = get_guild_config(guild_id)
    
    # Map to config key
    key = f"{mode}_{prompt_type}_prompt"
    
    # Defaults
    defaults = {
        "meeting_vlm": MEETING_VLM_PROMPT,
        "meeting_summary": MEETING_SUMMARY_PROMPT,
        "lecture_vlm": LECTURE_VLM_PROMPT,
        "lecture_summary": LECTURE_SUMMARY_PROMPT,
        "gemini_lecture_part1": GEMINI_LECTURE_PROMPT_PART1,
        "gemini_lecture_part_n": GEMINI_LECTURE_PROMPT_PART_N,
        "gemini_merge": GEMINI_MERGE_PROMPT,
    }
    
    default_key = f"{mode}_{prompt_type}"

    
    # Get custom or default
    custom = config.get(key)
    if custom:
        return custom
    
    # Backward compatibility: old custom_prompt -> meeting_summary
    if mode == "meeting" and prompt_type == "summary":
        old_custom = config.get("custom_prompt")
        if old_custom:
            return old_custom
    
    return defaults.get(default_key, "")


def set_prompt(guild_id: int, mode: str, prompt_type: str, value: str):
    """
    Set custom prompt
    
    Args:
        guild_id: Guild ID
        mode: "meeting" or "lecture"
        prompt_type: "vlm" or "summary"
        value: Prompt text
    """
    key = f"{mode}_{prompt_type}_prompt"
    set_guild_config(guild_id, key, value)


def reset_prompt(guild_id: int, mode: str, prompt_type: str):
    """
    Reset prompt to default (delete custom)
    
    Args:
        guild_id: Guild ID
        mode: "meeting" or "lecture"
        prompt_type: "vlm" or "summary"
    """
    configs = _load_configs()
    guild_key = str(guild_id)
    
    if guild_key in configs:
        key = f"{mode}_{prompt_type}_prompt"
        if key in configs[guild_key]:
            del configs[guild_key][key]
            _save_configs(configs)


def get_meetings_channel(guild_id: int) -> Optional[int]:
    """Get meetings channel ID for a guild"""
    config = get_guild_config(guild_id)
    channel_id = config.get("meetings_channel")
    return int(channel_id) if channel_id else None


def set_meetings_channel(guild_id: int, channel_id: int):
    """Set meetings channel for a guild"""
    set_guild_config(guild_id, "meetings_channel", str(channel_id))


# Default timezone is Vietnam (UTC+7)
DEFAULT_TIMEZONE = "UTC+7"


def get_timezone(guild_id: int) -> str:
    """Get timezone for a guild, default to Vietnam"""
    config = get_guild_config(guild_id)
    return config.get("timezone") or DEFAULT_TIMEZONE


def set_timezone(guild_id: int, timezone: str):
    """Set timezone for a guild"""
    set_guild_config(guild_id, "timezone", timezone)


# Default max Fireflies records (queue-based deletion)
DEFAULT_FIREFLIES_MAX_RECORDS = 6


def get_fireflies_max_records(guild_id: int) -> int:
    """Get max Fireflies records for a guild, default to 6"""
    config = get_guild_config(guild_id)
    try:
        return int(config.get("fireflies_max_records") or DEFAULT_FIREFLIES_MAX_RECORDS)
    except (ValueError, TypeError):
        return DEFAULT_FIREFLIES_MAX_RECORDS


def set_fireflies_max_records(guild_id: int, max_records: int):
    """Set max Fireflies records for a guild"""
    set_guild_config(guild_id, "fireflies_max_records", str(max(1, min(max_records, 50))))


def get_archive_channel(guild_id: int) -> Optional[int]:
    """Get archive channel ID for a guild"""
    config = get_guild_config(guild_id)
    channel_id = config.get("archive_channel")
    return int(channel_id) if channel_id else None


def set_archive_channel(guild_id: int, channel_id: int):
    """Set archive channel for a guild"""
    set_guild_config(guild_id, "archive_channel", str(channel_id))


def get_whitelist_transcripts(guild_id: int) -> list[str]:
    """Get whitelist transcript IDs that won't be auto-deleted"""
    config = get_guild_config(guild_id)
    whitelist = config.get("whitelist_transcripts", "")
    return [x.strip() for x in whitelist.split(",") if x.strip()]


def set_whitelist_transcripts(guild_id: int, transcript_ids: list[str]):
    """Set whitelist transcript IDs"""
    set_guild_config(guild_id, "whitelist_transcripts", ",".join(transcript_ids))


def add_to_whitelist(guild_id: int, transcript_id: str):
    """Add a transcript ID to whitelist"""
    current = get_whitelist_transcripts(guild_id)
    if transcript_id not in current:
        current.append(transcript_id)
        set_whitelist_transcripts(guild_id, current)


def remove_from_whitelist(guild_id: int, transcript_id: str):
    """Remove a transcript ID from whitelist"""
    current = get_whitelist_transcripts(guild_id)
    if transcript_id in current:
        current.remove(transcript_id)
        set_whitelist_transcripts(guild_id, current)

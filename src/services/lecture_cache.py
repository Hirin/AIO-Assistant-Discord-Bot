"""
Lecture Cache Service
Caches full pipeline stages to allow resuming on error/interruption

Cache key is based on:
- Video: Drive ID (extracted from URL)
- Slides: Drive ID OR (filename + size for uploads)
- User ID
"""
import json
import time
import logging
import hashlib
import re
import os
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/lecture_cache")
CACHE_EXPIRY_SECONDS = 7200  # 2 hours (for long videos)


def _get_cache_path(cache_id: str) -> Path:
    """Get cache file path for a pipeline"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{cache_id}.json"


def extract_drive_id(url: str) -> Optional[str]:
    """Extract Google Drive file ID from URL"""
    if not url:
        return None
    
    patterns = [
        r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/.*?/d/([a-zA-Z0-9_-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def generate_slides_key(slides_url: Optional[str]) -> str:
    """
    Generate cache key for slides:
    - Drive link: use Drive ID
    - Local upload: use filename + size
    - None: empty string
    """
    if not slides_url:
        return ""
    
    # Check if it's a Drive link
    drive_id = extract_drive_id(slides_url)
    if drive_id:
        return f"drive:{drive_id}"
    
    # Local file (upload) - use filename + size
    if slides_url.startswith('/tmp/') and os.path.exists(slides_url):
        filename = os.path.basename(slides_url)
        size = os.path.getsize(slides_url)
        return f"file:{filename}:{size}"
    
    # Fallback to URL hash
    return hashlib.md5(slides_url.encode()).hexdigest()[:12]


def generate_pipeline_id(
    video_url: str,
    slides_url: Optional[str],
    user_id: int,
) -> str:
    """
    Generate unique pipeline cache ID based on:
    - Video Drive ID
    - Slides key (Drive ID or filename+size)
    - User ID
    """
    # Extract video Drive ID
    video_id = extract_drive_id(video_url)
    if not video_id:
        # Fallback to URL hash for non-Drive URLs
        video_id = hashlib.md5(video_url.encode()).hexdigest()[:12]
    
    # Generate slides key
    slides_key = generate_slides_key(slides_url)
    
    # Combine all parts
    content = f"v:{video_id}|s:{slides_key}|u:{user_id}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


# ====================================
# Pipeline Cache Functions
# ====================================

def get_pipeline_cache(cache_id: str) -> Optional[dict]:
    """Load full pipeline cache, returns None if expired or not found"""
    cache_path = _get_cache_path(cache_id)
    
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, "r") as f:
            cache = json.load(f)
        
        # Check expiry
        created_at = cache.get("created_at", 0)
        if time.time() - created_at > CACHE_EXPIRY_SECONDS:
            logger.info(f"Pipeline cache expired for {cache_id}")
            cache_path.unlink()
            return None
        
        return cache
    except Exception as e:
        logger.warning(f"Error loading pipeline cache: {e}")
        return None


def save_stage(
    cache_id: str,
    stage_name: str,
    data: dict,
    config: Optional[dict] = None
) -> None:
    """
    Save a stage's result to cache.
    
    stage_name: 'video', 'transcript', 'slides', 'segments'
    data: stage-specific data
    config: initial config (only for first save)
    """
    cache_path = _get_cache_path(cache_id)
    
    # Load existing or create new
    if cache_path.exists():
        with open(cache_path, "r") as f:
            cache = json.load(f)
    else:
        cache = {
            "cache_id": cache_id,
            "created_at": time.time(),
            "config": config or {},
            "stages": {},
            "parts": {},
        }
    
    cache["updated_at"] = time.time()
    cache["stages"][stage_name] = {
        "status": "completed",
        "saved_at": time.time(),
        **data
    }
    
    with open(cache_path, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved stage '{stage_name}' for cache {cache_id}")


def get_stage(cache_id: str, stage_name: str) -> Optional[dict]:
    """Get a specific stage's cached data"""
    cache = get_pipeline_cache(cache_id)
    if not cache:
        return None
    
    stages = cache.get("stages", {})
    return stages.get(stage_name)


def clear_stage(cache_id: str, stage_name: str) -> None:
    """Clear a specific stage from cache"""
    cache_path = _get_cache_path(cache_id)
    
    if not cache_path.exists():
        return
    
    with open(cache_path, "r") as f:
        cache = json.load(f)
    
    if stage_name in cache.get("stages", {}):
        del cache["stages"][stage_name]
        cache["updated_at"] = time.time()
        
        with open(cache_path, "w") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Cleared stage '{stage_name}' for cache {cache_id}")


# ====================================
# Part Summaries (existing functionality)
# ====================================

def save_part_summary(
    cache_id: str,
    part_num: int,
    summary: str,
    start_seconds: float,
) -> None:
    """Save a part summary to cache"""
    cache_path = _get_cache_path(cache_id)
    
    # Load existing or create new
    if cache_path.exists():
        with open(cache_path, "r") as f:
            cache = json.load(f)
    else:
        cache = {
            "cache_id": cache_id,
            "created_at": time.time(),
            "stages": {},
            "parts": {},
        }
    
    cache["updated_at"] = time.time()
    cache["parts"][str(part_num)] = {
        "summary": summary,
        "start_seconds": start_seconds,
        "processed_at": time.time(),
    }
    
    with open(cache_path, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Cached part {part_num} for {cache_id}")


def get_cached_parts(cache_id: str) -> dict[int, dict]:
    """
    Get cached summaries for a lecture
    Returns dict of part_num -> {summary, start_seconds}
    """
    cache = get_pipeline_cache(cache_id)
    if not cache:
        return {}
    
    parts = cache.get("parts", {})
    return {int(k): v for k, v in parts.items()}


# ====================================
# Cleanup Functions
# ====================================

def clear_pipeline_cache(cache_id: str) -> None:
    """Delete entire pipeline cache"""
    cache_path = _get_cache_path(cache_id)
    if cache_path.exists():
        cache_path.unlink()
        logger.info(f"Deleted pipeline cache {cache_id}")


# Alias for backward compatibility
delete_cache = clear_pipeline_cache


def cleanup_expired_caches() -> int:
    """Delete all expired caches, returns count deleted"""
    if not CACHE_DIR.exists():
        return 0
    
    deleted = 0
    now = time.time()
    
    for cache_file in CACHE_DIR.glob("*.json"):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
            
            created_at = cache.get("created_at", 0)
            if now - created_at > CACHE_EXPIRY_SECONDS:
                cache_file.unlink()
                deleted += 1
                logger.info(f"Cleaned up expired cache: {cache_file.name}")
        except Exception as e:
            logger.warning(f"Error cleaning cache {cache_file}: {e}")
    
    return deleted


# ====================================
# Legacy compatibility
# ====================================

def generate_lecture_id(youtube_url: str, guild_id: int) -> str:
    """
    DEPRECATED: Use generate_pipeline_id instead.
    Kept for backward compatibility.
    """
    return generate_pipeline_id(youtube_url, None, guild_id)

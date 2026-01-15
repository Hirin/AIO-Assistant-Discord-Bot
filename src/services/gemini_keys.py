"""
Gemini Key Manager
Smart key rotation, rate limit handling, and request counting for multi-key Gemini API.
"""
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Storage for usage tracking
USAGE_FILE = Path(__file__).parent.parent.parent / "data" / "gemini_usage.json"

# Pacific Time for Gemini quota reset
PT_TIMEZONE = ZoneInfo("America/Los_Angeles")


def _ensure_usage_file():
    """Ensure usage file exists."""
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not USAGE_FILE.exists():
        USAGE_FILE.write_text("{}")


def _load_usage() -> dict:
    """Load usage data."""
    _ensure_usage_file()
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception as e:
        logger.error(f"Failed to load usage data: {e}")
        return {}


def _save_usage(data: dict):
    """Save usage data."""
    _ensure_usage_file()
    USAGE_FILE.write_text(json.dumps(data, indent=2))


def get_pt_date() -> str:
    """Get current date in Pacific Time (for Gemini quota reset)."""
    return datetime.now(PT_TIMEZONE).strftime("%Y-%m-%d")


def _hash_key(api_key: str) -> str:
    """Hash API key for storage (privacy). Internal use only."""
    return hashlib.md5(api_key.encode()).hexdigest()[:8]


def increment_request_count(user_id: int, api_key: str):
    """Increment request count for a key on current PT date."""
    data = _load_usage()
    user_key = str(user_id)
    pt_date = get_pt_date()
    key_hash = _hash_key(api_key)
    
    if user_key not in data:
        data[user_key] = {}
    
    if pt_date not in data[user_key]:
        # New day - reset counts
        data[user_key] = {pt_date: {}}
    
    if key_hash not in data[user_key][pt_date]:
        data[user_key][pt_date][key_hash] = 0
    
    data[user_key][pt_date][key_hash] += 1
    _save_usage(data)


def get_daily_counts(user_id: int) -> dict[str, int]:
    """
    Get request counts for current PT date.
    
    Returns:
        Dict of key_hash -> count
    """
    data = _load_usage()
    user_key = str(user_id)
    pt_date = get_pt_date()
    
    if user_key not in data:
        return {}
    
    return data[user_key].get(pt_date, {})


def get_key_count(user_id: int, api_key: str) -> int:
    """Get request count for a specific key today."""
    counts = get_daily_counts(user_id)
    key_hash = _hash_key(api_key)
    return counts.get(key_hash, 0)


def is_key_rate_limited(user_id: int, api_key: str, limit: int = 20) -> bool:
    """Check if key has reached daily limit."""
    return get_key_count(user_id, api_key) >= limit


class GeminiKeyPool:
    """
    Smart key rotation for personal Gemini API keys.
    Round-robin selection, skip rate-limited keys.
    """
    
    DAILY_LIMIT = 20  # Gemini free tier RPD
    
    def __init__(self, user_id: int, keys: list[str]):
        self.user_id = user_id
        self.keys = keys
        self._current_index = 0
        self._rate_limited_keys: set[str] = set()
    
    def get_available_key(self) -> Optional[str]:
        """
        Get next available key (round-robin, skip rate-limited).
        
        Returns:
            API key or None if all keys exhausted
        """
        if not self.keys:
            return None
        
        # Try each key starting from current index
        for i in range(len(self.keys)):
            idx = (self._current_index + i) % len(self.keys)
            key = self.keys[idx]
            key_hash = _hash_key(key)
            
            # Skip manually marked rate-limited
            if key_hash in self._rate_limited_keys:
                continue
            
            # Skip if over daily limit
            if is_key_rate_limited(self.user_id, key, self.DAILY_LIMIT):
                self._rate_limited_keys.add(key_hash)
                continue
            
            # Found available key
            self._current_index = (idx + 1) % len(self.keys)
            return key
        
        return None
    
    def mark_rate_limited(self, api_key: str):
        """Mark a key as rate-limited (called on 429 error)."""
        self._rate_limited_keys.add(_hash_key(api_key))
        logger.warning(f"Key {_hash_key(api_key)} marked as rate-limited")
    
    def get_status(self) -> list[dict]:
        """
        Get status of all keys.
        
        Returns:
            List of {index, hash, count, limit, rate_limited}
        """
        result = []
        counts = get_daily_counts(self.user_id)
        
        for i, key in enumerate(self.keys):
            key_hash = _hash_key(key)
            count = counts.get(key_hash, 0)
            result.append({
                "index": i,
                "hash": key_hash,
                "count": count,
                "limit": self.DAILY_LIMIT,
                "rate_limited": key_hash in self._rate_limited_keys or count >= self.DAILY_LIMIT
            })
        
        return result
    
    def increment_count(self, api_key: str):
        """Increment request count for a key."""
        increment_request_count(self.user_id, api_key)
    
    def reset_rate_limits(self):
        """Reset rate limit status for all keys (for manual retry)."""
        self._rate_limited_keys.clear()
        logger.info(f"Reset rate limits for user {self.user_id}")
    
    def get_next_key(self) -> Optional[str]:
        """Get current key without rotating (for logging)."""
        if not self.keys:
            return None
        return self.keys[self._current_index % len(self.keys)]


# Global pool cache for pool access across modules
_pool_cache: dict[int, GeminiKeyPool] = {}


def get_pool(user_id: int) -> Optional[GeminiKeyPool]:
    """Get existing pool for a user (if any)."""
    return _pool_cache.get(user_id)


def register_pool(user_id: int, pool: GeminiKeyPool):
    """Register a pool for a user."""
    _pool_cache[user_id] = pool

"""
Feedback logging service for satisfaction statistics.
Stores feedback data in JSONL format for easy analysis.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Feedback log file path
FEEDBACK_LOG_PATH = Path(__file__).parent.parent.parent / "data" / "feedback.jsonl"


def log_feedback(
    guild_id: int,
    user_id: int,
    feature: str,
    title: str,
    satisfied: bool,
    reason: Optional[str] = None,
) -> None:
    """
    Log user feedback to JSONL file.
    
    Args:
        guild_id: Discord guild ID
        user_id: Discord user ID
        feature: Feature name (e.g., "lecture", "preview", "meeting")
        title: Title of the content (e.g., lecture title)
        satisfied: True if user was satisfied, False otherwise
        reason: Optional reason (usually provided when not satisfied)
    """
    try:
        # Ensure directory exists
        FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "guild_id": guild_id,
            "user_id": user_id,
            "feature": feature,
            "title": title,
            "satisfied": satisfied,
            "reason": reason,
        }
        
        with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        logger.info(f"Logged feedback: feature={feature} satisfied={satisfied}")
        
    except Exception as e:
        logger.error(f"Failed to log feedback: {e}")


def get_statistics(feature: Optional[str] = None) -> dict:
    """
    Get feedback statistics.
    
    Args:
        feature: Optional filter by feature name
        
    Returns:
        Dict with statistics: total, satisfied, unsatisfied, satisfaction_rate
    """
    if not FEEDBACK_LOG_PATH.exists():
        return {"total": 0, "satisfied": 0, "unsatisfied": 0, "satisfaction_rate": 0.0}
    
    total = 0
    satisfied = 0
    
    try:
        with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if feature and entry.get("feature") != feature:
                        continue
                    total += 1
                    if entry.get("satisfied"):
                        satisfied += 1
                except json.JSONDecodeError:
                    continue
        
        unsatisfied = total - satisfied
        rate = (satisfied / total * 100) if total > 0 else 0.0
        
        return {
            "total": total,
            "satisfied": satisfied,
            "unsatisfied": unsatisfied,
            "satisfaction_rate": round(rate, 1),
        }
        
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        return {"total": 0, "satisfied": 0, "unsatisfied": 0, "satisfaction_rate": 0.0}


def get_recent_feedback(limit: int = 20, feature: Optional[str] = None) -> list[dict]:
    """
    Get recent feedback entries.
    
    Args:
        limit: Maximum number of entries to return
        feature: Optional filter by feature name
        
    Returns:
        List of recent feedback entries (newest first)
    """
    if not FEEDBACK_LOG_PATH.exists():
        return []
    
    entries = []
    
    try:
        with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if feature and entry.get("feature") != feature:
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
        
        # Return newest first
        return entries[-limit:][::-1]
        
    except Exception as e:
        logger.error(f"Failed to get recent feedback: {e}")
        return []

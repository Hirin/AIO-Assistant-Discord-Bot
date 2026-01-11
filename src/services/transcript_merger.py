"""
Transcript Merger - Merge chat session with AssemblyAI transcript by timestamp.
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TimedEntry:
    """Entry with timestamp for merging."""
    time_seconds: float
    text: str
    entry_type: str  # "transcript" or "chat"



def parse_chat_session(chat_text: str) -> list[TimedEntry]:
    """
    Parse chat session JSON into timed entries.
    
    Expected format from preprocess_chat_session:
    [{"name": "...", "time": "1:23:45", "content": "..."}]
    
    Args:
        chat_text: JSON string from preprocess_chat_session
        
    Returns:
        List of TimedEntry objects with parsed timestamps
    """
    import json
    
    entries = []
    
    try:
        messages = json.loads(chat_text)
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict) and "time" in msg and "content" in msg:
                    time_str = msg["time"]  # Format: "1:23:45" or "23:45"
                    content = msg.get("content", "")
                    name = msg.get("name", "")
                    
                    # Parse time string to seconds
                    time_sec = parse_time_string_to_seconds(time_str)
                    if time_sec is not None:
                        # Include name in the text
                        text = f"{name}: {content}" if name else content
                        entries.append(TimedEntry(
                            time_seconds=time_sec,
                            text=text,
                            entry_type="chat"
                        ))
            
            if entries:
                logger.info(f"Parsed {len(entries)} chat entries from JSON")
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to parse chat JSON: {e}")
    
    return entries


def parse_time_string_to_seconds(time_str: str) -> Optional[float]:
    """
    Parse time string like "1:23:45" or "23:45" to seconds.
    """
    parts = time_str.strip().split(':')
    try:
        if len(parts) == 3:
            # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return None
    except (ValueError, TypeError):
        return None


def parse_transcript_text(transcript_text: str) -> list[TimedEntry]:
    """
    Parse transcript text with [123s] format into timed entries.
    
    Args:
        transcript_text: Transcript text with format "[123s] text"
        
    Returns:
        List of TimedEntry objects
    """
    entries = []
    # Pattern: [123s] text
    pattern = r'^\[(\d+)s\]\s*(.+)$'
    
    for line in transcript_text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
            
        match = re.match(pattern, line)
        if match:
            time_sec = int(match.group(1))
            text = match.group(2).strip()
            entries.append(TimedEntry(
                time_seconds=time_sec,
                text=text,
                entry_type="transcript"
            ))
    
    return entries


def merge_transcript_with_chat(
    transcript_text: str,  # [123s] text format from AssemblyAI
    chat_text: Optional[str],
) -> str:
    """
    Merge transcript with chat session by timestamp.
    
    Args:
        transcript_text: Transcript text with [123s] format
        chat_text: Raw chat session text (optional)
        
    Returns:
        Merged timeline as text with both transcript and chat entries
        
    Example output:
        [0s] Xin chào các bạn, hôm nay chúng ta học về...
        [45s] 💬 CHAT: Thầy ơi slide có trên moodle không ạ?
        [60s] Tiếp theo chúng ta xem phần...
        [120s] 💬 CHAT: Em không hiểu phần này lắm
    """
    if not transcript_text:
        return chat_text or ""
    
    if not chat_text:
        # No chat to merge, return transcript as-is
        return transcript_text
    
    # Parse chat entries
    chat_entries = parse_chat_session(chat_text)
    
    if not chat_entries:
        # Chat should always have timestamps - if not found, log error
        logger.warning(f"No parseable timestamps in chat session ({len(chat_text)} chars) - check chat processing step")
        return f"{transcript_text}\n\n--- Chat Session (⚠️ timestamps không parse được) ---\n{chat_text}"
    
    # Parse transcript entries
    transcript_entries = parse_transcript_text(transcript_text)
    
    if not transcript_entries:
        # Couldn't parse transcript, return as-is with chat
        return f"{transcript_text}\n\n--- Chat Session ---\n{chat_text}"
    
    # Merge all entries
    all_entries = transcript_entries + chat_entries
    
    # Sort by timestamp
    all_entries.sort(key=lambda e: e.time_seconds)
    
    # Format output
    lines = []
    for entry in all_entries:
        ts = int(entry.time_seconds)
        if entry.entry_type == "transcript":
            lines.append(f"[{ts}s] {entry.text}")
        else:
            # Chat entry - mark with 💬 for visibility
            lines.append(f"[{ts}s] 💬 CHAT: {entry.text}")
    
    logger.info(f"Merged {len(transcript_entries)} transcript paragraphs with {len(chat_entries)} chat entries")
    return "\n\n".join(lines)

"""
Transcript Storage Service
Save transcripts locally organized by guild, supporting multiple platforms:
- ff: Fireflies (meeting transcripts)
- aai: AssemblyAI (lecture transcripts)

File naming: {platform}_{transcript_id}.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

logger = logging.getLogger(__name__)

# Store transcripts in JSON, organized by guild
TRANSCRIPTS_DIR = Path(__file__).parent.parent.parent / "data" / "transcripts"

# Platform types
Platform = Literal["ff", "aai"]


def _get_guild_dir(guild_id: int) -> Path:
    """Get transcript directory for a guild"""
    guild_dir = TRANSCRIPTS_DIR / str(guild_id)
    guild_dir.mkdir(parents=True, exist_ok=True)
    return guild_dir


def _sanitize_title(title: str, max_len: int = 30) -> str:
    """Sanitize title for use in filename"""
    import re
    safe = re.sub(r'[^\w\s-]', '', title)[:max_len].strip()
    return re.sub(r'[\s]+', '-', safe)


def _get_file_path(guild_id: int, platform: Platform, transcript_id: str, title: str = "") -> Path:
    """Get file path for a transcript: {platform}_{id}_{title_slug}.json"""
    guild_dir = _get_guild_dir(guild_id)
    if title:
        title_slug = _sanitize_title(title, 25)
        return guild_dir / f"{platform}_{transcript_id}_{title_slug}.json"
    return guild_dir / f"{platform}_{transcript_id}.json"


def _find_transcript_file(guild_id: int, platform: Platform, transcript_id: str) -> Optional[Path]:
    """Find transcript file by platform and ID (handles title in filename)"""
    guild_dir = _get_guild_dir(guild_id)
    # Pattern: {platform}_{transcript_id}*.json
    pattern = f"{platform}_{transcript_id}*.json"
    matches = list(guild_dir.glob(pattern))
    if matches:
        return matches[0]
    return None


def transcript_exists(guild_id: int, transcript_id: str, platform: Platform = "ff") -> bool:
    """Check if transcript already exists locally"""
    return _find_transcript_file(guild_id, platform, transcript_id) is not None


def save_transcript(
    guild_id: int,
    transcript_id: str,
    title: str,
    platform: Platform = "ff",
    transcript_data: Optional[list[dict]] = None,
    video_url: Optional[str] = None,
    duration: Optional[float] = None,
    extra_metadata: Optional[dict] = None,
) -> tuple[dict, bool]:
    """
    Save transcript metadata to local storage.
    
    Args:
        guild_id: Discord guild ID
        transcript_id: Unique transcript ID from platform
        title: Transcript/meeting title
        platform: "ff" (Fireflies) or "aai" (AssemblyAI)
        transcript_data: Full transcript entries (only for Fireflies, optional for AssemblyAI)
        video_url: Source video URL (for AssemblyAI)
        duration: Audio/video duration in seconds
        extra_metadata: Additional platform-specific metadata

    Returns:
        Tuple of (entry dict, is_new) - is_new=False if already existed
    """
    # Check if already exists (by pattern since filename includes title)
    existing_file = _find_transcript_file(guild_id, platform, transcript_id)
    if existing_file:
        logger.info(f"Transcript {platform}:{transcript_id} already exists, skipping save")
        existing = json.loads(existing_file.read_text())
        return (existing, False)
    
    file_path = _get_file_path(guild_id, platform, transcript_id, title)
    
    entry = {
        "id": transcript_id,
        "platform": platform,
        "guild_id": guild_id,
        "title": title,
        "created_at": datetime.now().isoformat(),
        "created_timestamp": int(datetime.now().timestamp()),
    }
    
    # Platform-specific fields (metadata only - no transcript_data in local file)
    if platform == "ff":
        entry["fireflies_id"] = transcript_id  # Backward compat
    elif platform == "aai":
        entry["assemblyai_id"] = transcript_id
        if video_url:
            entry["video_url"] = video_url
        if duration:
            entry["duration"] = duration
    
    # Extra metadata
    if extra_metadata:
        entry.update(extra_metadata)
    
    # NOTE: transcript_data is NOT saved locally - only to Discord archive
    # Store it temporarily for upload_to_discord, then remove
    entry["_transcript_data"] = transcript_data  # Underscore = temp field

    file_path.write_text(json.dumps({k: v for k, v in entry.items() if not k.startswith('_')}, ensure_ascii=False, indent=2))
    logger.info(f"Saved new transcript {platform}:{transcript_id} for guild {guild_id}")
    return (entry, True)


def generate_backup_filename(title: str) -> str:
    """Generate backup filename: DDMMYYYY-Title-HHMMSS.json"""
    import re
    now = datetime.now()
    # Sanitize title - remove special chars
    safe_title = re.sub(r'[^\w\s-]', '', title)[:30].strip()
    safe_title = re.sub(r'[\s]+', '-', safe_title)
    return f"{now.strftime('%d%m%Y')}-{safe_title}-{now.strftime('%H%M%S')}.json"


async def upload_to_discord(bot, guild_id: int, entry: dict) -> Optional[str]:
    """
    Upload transcript JSON to Discord archive channel.
    Includes full transcript_data in the uploaded file.
    
    Returns:
        Attachment URL if successful, None otherwise
    """
    from services import config
    import io
    import discord
    
    channel_id = config.get_archive_channel(guild_id)
    if not channel_id:
        logger.debug(f"No archive channel set for guild {guild_id}")
        return None
    
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.warning(f"Archive channel {channel_id} not found")
        return None
    
    try:
        # Build full entry for Discord (includes transcript_data)
        full_entry = {k: v for k, v in entry.items() if not k.startswith('_')}
        
        # Add transcript_data if available (from temp field)
        transcript_data = entry.get("_transcript_data")
        if transcript_data:
            full_entry["transcript"] = transcript_data
        
        # Create JSON content
        json_content = json.dumps(full_entry, ensure_ascii=False, indent=2)
        
        platform = entry.get("platform", "ff")
        filename = f"{platform}_{generate_backup_filename(entry.get('title', 'transcript'))}"
        
        # Upload as file
        file = discord.File(
            io.BytesIO(json_content.encode('utf-8')),
            filename=filename
        )
        
        # Message with platform indicator
        platform_emoji = "📋" if platform == "ff" else "🎓"
        msg = await channel.send(
            f"{platform_emoji} **{entry.get('title', 'Transcript')}**\nID: `{platform}:{entry.get('id')}`",
            file=file
        )
        
        # Get attachment URL
        if msg.attachments:
            backup_url = msg.attachments[0].url
            
            # Update local file with backup URL
            transcript_id = entry.get("id")
            update_backup_url(guild_id, transcript_id, backup_url, platform)
            
            logger.info(f"Uploaded transcript backup: {filename}")
            return backup_url
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to upload transcript backup: {e}")
        return None


def update_backup_url(guild_id: int, transcript_id: str, backup_url: str, platform: Platform = "ff") -> bool:
    """Update backup URL for a transcript"""
    file_path = _find_transcript_file(guild_id, platform, transcript_id)
    if file_path:
        entry = json.loads(file_path.read_text())
        entry["backup_url"] = backup_url
        file_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        return True
    return False


async def update_title(
    bot, guild_id: int, transcript_id: str, new_title: str
) -> tuple[bool, str]:
    """
    Update transcript title and re-upload to Discord archive.
    
    Args:
        bot: Discord bot instance
        guild_id: Guild ID
        transcript_id: Transcript ID
        new_title: New title for the transcript
        
    Returns:
        Tuple of (success, message)
    """
    from services import config
    import io
    import discord
    
    # Get existing entry
    entry = get_transcript(guild_id, transcript_id)
    if not entry:
        return (False, "Transcript not found")
    
    old_title = entry.get("title", "Untitled")
    old_backup_url = entry.get("backup_url")
    
    # Update title in local storage
    entry["title"] = new_title
    guild_dir = _get_guild_dir(guild_id)
    file_path = guild_dir / f"{transcript_id}.json"
    file_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    
    # If there's a backup URL, try to delete old message and re-upload
    if old_backup_url:
        channel_id = config.get_archive_channel(guild_id)
        if channel_id:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    # Try to find and delete old message
                    # Search recent messages for the old backup
                    async for msg in channel.history(limit=100):
                        if msg.author.id == bot.user.id and msg.attachments:
                            for att in msg.attachments:
                                if att.url == old_backup_url or transcript_id in str(msg.content):
                                    await msg.delete()
                                    logger.info(f"Deleted old backup message for {transcript_id}")
                                    break
                    
                    # Re-upload with new title
                    json_content = json.dumps(entry, ensure_ascii=False, indent=2)
                    filename = generate_backup_filename(new_title)
                    
                    file = discord.File(
                        io.BytesIO(json_content.encode('utf-8')),
                        filename=filename
                    )
                    
                    new_msg = await channel.send(
                        f"📋 **{new_title}**\nID: `{transcript_id}`",
                        file=file
                    )
                    
                    # Update backup URL
                    if new_msg.attachments:
                        entry["backup_url"] = new_msg.attachments[0].url
                        file_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
                    
                    logger.info(f"Re-uploaded transcript with new title: {new_title}")
                    return (True, f"Title updated: `{old_title}` → `{new_title}`")
                    
                except Exception as e:
                    logger.error(f"Failed to update archive: {e}")
                    return (True, f"Title updated locally (archive update failed: {str(e)[:50]})")
    
    return (True, f"Title updated: `{old_title}` → `{new_title}`")


def get_transcript(guild_id: int, transcript_id: str, platform: Optional[Platform] = None) -> Optional[dict]:
    """
    Get transcript by ID.
    
    Args:
        guild_id: Guild ID
        transcript_id: Transcript ID
        platform: Optional platform filter ("ff" or "aai"). If None, searches all.
    """
    guild_dir = _get_guild_dir(guild_id)
    
    # If platform specified, use direct search
    if platform:
        file_path = _find_transcript_file(guild_id, platform, transcript_id)
        if file_path:
            return json.loads(file_path.read_text())
        return None
    
    # Try both platforms
    for p in ["ff", "aai"]:
        file_path = _find_transcript_file(guild_id, p, transcript_id)
        if file_path:
            return json.loads(file_path.read_text())
    
    # Fallback: search old format (direct transcript_id.json) for backward compat
    old_path = guild_dir / f"{transcript_id}.json"
    if old_path.exists():
        return json.loads(old_path.read_text())
    
    # Fallback: search by id field in all files
    for f in guild_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("id") == transcript_id or data.get("fireflies_id") == transcript_id or data.get("assemblyai_id") == transcript_id:
                return data
        except Exception:
            pass
    
    return None

async def fetch_transcript_data(backup_url: str) -> Optional[list[dict]]:
    """
    Download transcript data from backup URL (Discord attachment).
    
    Args:
        backup_url: Discord attachment URL
        
    Returns:
        Transcript data list or None if failed
    """
    import httpx
    
    if not backup_url:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(backup_url)
            if response.status_code == 200:
                data = response.json()
                return data.get("transcript")
    except Exception as e:
        logger.error(f"Failed to fetch transcript from backup: {e}")
    
    return None


async def get_transcript_with_data(guild_id: int, transcript_id: str, platform: Optional[Platform] = None) -> Optional[dict]:
    """
    Get transcript metadata and fetch transcript data from backup if available.
    
    Returns full entry with transcript data populated from backup_url.
    """
    entry = get_transcript(guild_id, transcript_id, platform)
    if not entry:
        return None
    
    # If transcript data not in local, fetch from backup_url
    if "transcript" not in entry and entry.get("backup_url"):
        transcript_data = await fetch_transcript_data(entry["backup_url"])
        if transcript_data:
            entry["transcript"] = transcript_data
    
    return entry


async def restore_from_archive(bot, guild_id: int, transcript_id: str) -> Optional[dict]:
    """
    Search archive channel for a transcript by ID and restore it.
    
    Args:
        bot: Discord bot instance
        guild_id: Guild ID
        transcript_id: Transcript ID to search for
    
    Returns:
        Restored transcript entry or None if not found
    """
    from services import config
    import httpx
    
    channel_id = config.get_archive_channel(guild_id)
    if not channel_id:
        logger.debug(f"No archive channel set for guild {guild_id}")
        return None
    
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.warning(f"Archive channel {channel_id} not found")
        return None
    
    try:
        # Search recent messages for matching ID
        async for message in channel.history(limit=200):
            # Check if message mentions this ID
            if transcript_id in message.content:
                # Found matching message - download attachment
                if message.attachments:
                    attachment = message.attachments[0]
                    if attachment.filename.endswith('.json'):
                        # Download JSON
                        async with httpx.AsyncClient() as client:
                            response = await client.get(attachment.url)
                            if response.status_code == 200:
                                entry = response.json()
                                
                                # Save to guild folder
                                entry["backup_url"] = attachment.url
                                guild_dir = _get_guild_dir(guild_id)
                                file_path = guild_dir / f"{transcript_id}.json"
                                file_path.write_text(
                                    json.dumps(entry, ensure_ascii=False, indent=2)
                                )
                                
                                logger.info(f"Restored transcript {transcript_id} from archive")
                                return entry
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to restore from archive: {e}")
        return None

def list_transcripts(guild_id: int, limit: int = 10) -> list[dict]:
    """List transcripts for a guild, sorted by newest first"""
    guild_dir = _get_guild_dir(guild_id)

    transcripts = []
    # Read all files first to get metadata
    all_entries = []
    files = list(guild_dir.glob("*.json"))
    
    for file_path in files:
        try:
            entry = json.loads(file_path.read_text())
            all_entries.append(entry)
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            
    # Sort by created_timestamp (newest first)
    all_entries.sort(key=lambda x: x.get("created_timestamp", 0), reverse=True)
    
    for entry in all_entries[:limit]:
        transcripts.append(
            {
                "id": entry.get("id") or entry.get("fireflies_id"),
                "local_id": entry.get("local_id") or entry.get("id"),  # Backward compat
                "fireflies_id": entry.get("fireflies_id"),
                "title": entry.get("title"),
                "created_at": entry.get("created_at"),
                "created_timestamp": entry.get("created_timestamp"),
                "backup_url": entry.get("backup_url"),
            }
        )

    return transcripts


def delete_transcript(guild_id: int, transcript_id: str) -> bool:
    """Delete transcript by ID"""
    guild_dir = _get_guild_dir(guild_id)

    file_path = guild_dir / f"{transcript_id}.json"
    if file_path.exists():
        file_path.unlink()
        logger.info(f"Deleted transcript {transcript_id}")
        return True
    return False


def update_summary(local_id: str, summary: str) -> bool:
    """Update summary for a transcript"""
    entry = get_transcript(local_id)
    if entry:
        entry["summary"] = summary
        file_path = TRANSCRIPTS_DIR / f"{local_id}.json"
        file_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        return True
    return False


def cleanup_old_transcripts(max_age_days: int = 120) -> int:
    """
    Delete transcripts older than max_age_days (default 120 days = 4 months).

    Returns:
        Number of deleted transcripts
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0
    
    # Ensure base directory exists (though should already exist)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # recurse into guild directories
    for file_path in TRANSCRIPTS_DIR.rglob("*.json"):
        try:
            entry = json.loads(file_path.read_text())
            created_at = entry.get("created_at", "")
            if created_at:
                created = datetime.fromisoformat(created_at)
                if created < cutoff:
                    file_path.unlink()
                    logger.info(f"Auto-deleted old transcript: {file_path.stem}")
                    deleted += 1
        except Exception as e:
            logger.error(f"Error checking {file_path}: {e}")

    if deleted:
        logger.info(f"Cleanup: deleted {deleted} old transcripts")
    return deleted

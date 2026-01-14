"""
Meeting Scheduler Service
- Schedule Fireflies bot to join meetings
- Auto-poll for transcripts after Join and send summary to channel
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from utils.discord_utils import send_chunked

logger = logging.getLogger(__name__)

# Store scheduled meetings and pending polls in JSON
SCHEDULE_FILE = Path(__file__).parent.parent.parent / "data" / "scheduled_meetings.json"
POLLS_FILE = Path(__file__).parent.parent.parent / "data" / "pending_polls.json"


def _ensure_file(file_path: Path):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists():
        file_path.write_text("[]")


# === Scheduled Meetings ===


def load_scheduled() -> list[dict]:
    """Load scheduled meetings from file"""
    _ensure_file(SCHEDULE_FILE)
    try:
        return json.loads(SCHEDULE_FILE.read_text())
    except Exception:
        return []


def save_scheduled(meetings: list[dict]):
    """Save scheduled meetings to file"""
    _ensure_file(SCHEDULE_FILE)
    SCHEDULE_FILE.write_text(json.dumps(meetings, indent=2, default=str))


def add_scheduled(
    meeting_link: str,
    scheduled_time: datetime,
    guild_id: int,
    title: Optional[str] = None,
    glossary_text: Optional[str] = None,
) -> dict:
    """Add a meeting to schedule"""
    meetings = load_scheduled()

    entry = {
        "id": f"{guild_id}_{int(scheduled_time.timestamp())}",
        "meeting_link": meeting_link,
        "scheduled_time": scheduled_time.isoformat(),
        "guild_id": guild_id,
        "title": title,
        "status": "pending",
        "glossary_text": glossary_text,  # Optional document glossary
    }

    meetings.append(entry)
    save_scheduled(meetings)
    logger.info(f"Scheduled meeting: {entry['id']} at {scheduled_time}")
    return entry


def get_pending() -> list[dict]:
    """Get pending scheduled meetings"""
    from datetime import timezone
    
    meetings = load_scheduled()
    now = datetime.now(timezone.utc)

    pending = []
    for m in meetings:
        if m.get("status") == "pending":
            scheduled = datetime.fromisoformat(m["scheduled_time"])
            # Convert to UTC if timezone-aware, else assume UTC
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            else:
                scheduled = scheduled.astimezone(timezone.utc)
            if scheduled <= now:
                pending.append(m)

    return pending


def mark_completed(meeting_id: str, status: str = "completed"):
    """Mark a scheduled meeting as completed or failed"""
    meetings = load_scheduled()
    for m in meetings:
        if m.get("id") == meeting_id:
            m["status"] = status
            break
    save_scheduled(meetings)


def get_scheduled_for_guild(guild_id: int) -> list[dict]:
    """Get pending meetings for a specific guild"""
    meetings = load_scheduled()
    return [
        m
        for m in meetings
        if m.get("guild_id") == guild_id and m.get("status") == "pending"
    ]


def remove_scheduled(meeting_id: str) -> bool:
    """Remove a scheduled meeting"""
    meetings = load_scheduled()
    new_meetings = [m for m in meetings if m.get("id") != meeting_id]
    if len(new_meetings) < len(meetings):
        save_scheduled(new_meetings)
        return True
    return False


# === Pending Polls (for auto-summary after Join) ===


def load_polls() -> list[dict]:
    """Load pending polls from file"""
    _ensure_file(POLLS_FILE)
    try:
        return json.loads(POLLS_FILE.read_text())
    except Exception:
        return []


def save_polls(polls: list[dict]):
    """Save pending polls to file"""
    _ensure_file(POLLS_FILE)
    POLLS_FILE.write_text(json.dumps(polls, indent=2, default=str))


def add_poll(
    guild_id: int,
    poll_after: datetime,
    title: Optional[str] = None,
    duration_min: int = 120,
    glossary_text: Optional[str] = None,
) -> dict:
    """
    Add a poll entry to check for new transcripts.

    Args:
        guild_id: Discord guild ID
        poll_after: When to start polling (e.g., meeting end time + 20 min)
        title: Optional meeting title to match
        duration_min: Expected meeting duration for reference
        glossary_text: Optional glossary from uploaded document
    """
    polls = load_polls()

    entry = {
        "id": f"poll_{guild_id}_{int(datetime.now().timestamp())}",
        "guild_id": guild_id,
        "poll_after": poll_after.isoformat(),
        "title": title,
        "created_at": datetime.now().isoformat(),
        "attempts": 0,
        "max_attempts": 9,  # Poll every 10min for 90min (1h to 2h30m window)
        "status": "pending",
        "glossary_text": glossary_text,  # Optional document glossary
    }

    polls.append(entry)
    save_polls(polls)
    logger.info(f"Added poll: {entry['id']} starts at {poll_after}")
    return entry


def get_pending_polls() -> list[dict]:
    """Get polls that are ready to execute (pending or retry_pending past time)"""
    polls = load_polls()
    now = datetime.now()

    pending = []
    for p in polls:
        status = p.get("status")
        
        if status == "pending":
            poll_after = datetime.fromisoformat(p["poll_after"])
            if poll_after <= now:
                pending.append(p)
        elif status == "retry_pending":
            # Check if retry time has passed
            next_poll_time = p.get("next_poll_time")
            if next_poll_time:
                retry_time = datetime.fromisoformat(next_poll_time)
                if retry_time <= now:
                    pending.append(p)

    return pending


def update_poll(poll_id: str, **kwargs):
    """Update a poll entry with arbitrary fields"""
    polls = load_polls()
    for p in polls:
        if p.get("id") == poll_id:
            for key, value in kwargs.items():
                if value is not None:
                    p[key] = value
            break
    save_polls(polls)


def _clear_poll_glossary(poll_id: str):
    """Clear glossary_text from poll to save memory after use"""
    polls = load_polls()
    for p in polls:
        if p.get("id") == poll_id and "glossary_text" in p:
            p["glossary_text"] = None
            break
    save_polls(polls)



# === Main Scheduler Loop ===


async def run_scheduler(bot):
    """Background task to:
    1. Execute scheduled meetings (Join Now at scheduled time)
    2. Poll for new transcripts after Join
    3. Daily cleanup of old transcripts
    """
    from services import config, fireflies, fireflies_api, llm, transcript_storage

    last_cleanup = datetime.now()
    last_poll_check = datetime.now()

    while True:
        try:
            # === 1. Execute pending scheduled meetings ===
            pending_meetings = get_pending()
            for meeting in pending_meetings:
                logger.info(f"Executing scheduled meeting: {meeting['id']}")

                success, msg = await fireflies_api.add_to_live_meeting(
                    meeting_link=meeting["meeting_link"],
                    guild_id=meeting.get("guild_id"),
                    title=meeting.get("title"),
                )

                if success:
                    # Schedule a poll for 2h20m later, pass glossary if any
                    poll_time = datetime.now() + timedelta(hours=2, minutes=20)
                    add_poll(
                        guild_id=meeting.get("guild_id"),
                        poll_after=poll_time,
                        title=meeting.get("title"),
                        glossary_text=meeting.get("glossary_text"),  # Pass glossary
                    )

                mark_completed(
                    meeting["id"], status="completed" if success else "failed"
                )

            # === 2. Poll for new transcripts (every 10 min) ===
            now = datetime.now()
            if (now - last_poll_check).total_seconds() >= 600:  # 10 minutes
                last_poll_check = now

                pending_polls = get_pending_polls()
                for poll in pending_polls:
                    guild_id = poll.get("guild_id")
                    poll_id = poll.get("id")
                    attempts = poll.get("attempts", 0)
                    max_attempts = poll.get("max_attempts", 6)

                    logger.info(
                        f"Polling for transcript: {poll_id} (attempt {attempts + 1})"
                    )

                    # Get recent transcripts from Fireflies
                    transcripts = await fireflies_api.list_transcripts(
                        guild_id=guild_id, limit=3
                    )

                    # Check if any new transcript matches
                    found_new = False
                    for t in transcripts or []:
                        t_id = t.get("id")
                        # Check if already saved locally
                        local = transcript_storage.list_transcripts(guild_id, limit=50)
                        already_saved = any(
                            x.get("fireflies_id") == t_id
                            or t_id in str(x.get("local_id", ""))
                            for x in local
                        )

                        if not already_saved:
                            found_new = True
                            logger.info(f"Found new transcript: {t_id}")

                            # Get full transcript via scraping + AssemblyAI
                            # (replaces fireflies_api.get_transcript_by_id which needs paid plan)
                            from services import fireflies_scraper
                            transcript_data = await fireflies_scraper.get_meeting_transcript(
                                t_id, guild_id=guild_id
                            )

                            if transcript_data:
                                # Get glossary from poll if available
                                glossary = poll.get("glossary_text")
                                
                                # Summarize with glossary context
                                # Format for LLM: Use seconds for better citation
                                transcript_text = fireflies.format_transcript_for_llm(
                                    transcript_data
                                )
                                summary = await llm.summarize_transcript(
                                    transcript_text, guild_id=guild_id, glossary=glossary
                                )
                                
                                # Check if summary failed (rate limit / API error)
                                if summary and summary.startswith("⚠️ LLM Error"):
                                    # Check if this is already a retry
                                    retry_count = poll.get("retry_count", 0)
                                    
                                    channel_id = config.get_meetings_channel(guild_id)
                                    if channel_id and bot:
                                        channel = bot.get_channel(channel_id)
                                        if channel:
                                            if retry_count < 2:  # Allow 2 retries (1h and 2h later)
                                                # Schedule retry in 1 hour
                                                retry_time = datetime.now() + timedelta(hours=1)
                                                poll["retry_count"] = retry_count + 1
                                                poll["next_poll_time"] = retry_time.isoformat()
                                                poll["status"] = "retry_pending"
                                                update_poll(poll_id, **poll)
                                                
                                                await channel.send(
                                                    f"⚠️ **LLM API Error** (Rate Limit): Không thể tóm tắt `{t.get('title', 'Meeting')}` ngay bây giờ.\n"
                                                    f"🔄 Sẽ thử lại sau **1 giờ** (lần thử {retry_count + 1}/2)."
                                                )
                                                logger.warning(f"Summary failed for {t_id}, scheduling retry in 1 hour")
                                            else:
                                                # Give up after 2 retries
                                                await channel.send(
                                                    f"❌ **LLM API Error**: Không thể tóm tắt `{t.get('title', 'Meeting')}` sau 2 lần thử.\n"
                                                    f"📋 Vui lòng dùng `/meeting` > `Summarize Meeting` để tóm tắt thủ công.\n"
                                                    f"**ID:** `{t_id}`"
                                                )
                                                logger.error(f"Summary failed for {t_id} after 2 retries, giving up")
                                                update_poll(poll_id, status="failed")
                                    break  # Exit loop, either scheduled retry or gave up

                                # Save locally (metadata only - data goes to Discord archive)
                                title = t.get("title", "Auto-polled Meeting")
                                entry, is_new = transcript_storage.save_transcript(
                                    guild_id=guild_id,
                                    transcript_id=t_id,
                                    title=title,
                                    platform="ff",
                                    transcript_data=transcript_data,
                                )

                                # Only upload to archive if new (not duplicate)
                                if is_new:
                                    await transcript_storage.upload_to_discord(
                                        bot, guild_id, entry
                                    )

                                # No longer delete from Fireflies (queue-based deletion instead)
                                # Generate Fireflies link
                                ff_link = fireflies_api.generate_fireflies_link(title, t_id)
                                
                                # Process summary timestamps: [-123s-] -> [MM:SS](link)
                                if summary:
                                    summary = fireflies.process_summary_timestamps(summary, ff_link)

                                # Send to Discord channel
                                channel_id = config.get_meetings_channel(guild_id)
                                if channel_id and bot:
                                    channel = bot.get_channel(channel_id)
                                    if channel:
                                        doc_status = " 📎" if glossary else ""
                                        msg = (
                                            f"📋 **{title}**{doc_status} (ID: `{entry.get('id') or t_id}`)\n\n"
                                            f"{summary or 'No summary'}\n\n"
                                            f"🔗 [Xem recording]({ff_link})"
                                        )
                                        
                                        # 1. Send detailed summary first (chunked)
                                        await send_chunked(channel, msg)
                                        
                                        # 2. Tag everyone at the end
                                        await channel.send("@everyone Đây là nội dung meeting hôm nay")
                                        
                                        # 3. Log to tracking channel
                                        from services import discord_logger
                                        guild = bot.get_guild(guild_id)
                                        await discord_logger.log_process(
                                            bot=bot,
                                            guild=guild,
                                            user=None,  # Auto-polled, no specific user
                                            process="Meeting Summary (Auto)",
                                            status="Success",
                                            success=True,
                                        )

                            break  # Process one transcript per poll cycle

                    if found_new:
                        update_poll(poll_id, status="completed")
                        # Clear glossary after use to save memory
                        _clear_poll_glossary(poll_id)
                    else:
                        # Increment attempts
                        new_attempts = attempts + 1
                        if new_attempts >= max_attempts:
                            update_poll(
                                poll_id, attempts=new_attempts, status="exhausted"
                            )
                            logger.info(f"Poll exhausted: {poll_id}")
                        else:
                            update_poll(poll_id, attempts=new_attempts)

            # === 3. Daily cleanup of old transcripts (4 months) ===
            if (now - last_cleanup).days >= 1:
                logger.info("Running daily cleanup...")
                
                # Cleanup old transcripts (120 days)
                transcript_storage.cleanup_old_transcripts(max_age_days=120)
                
                # Cleanup expired slide caches (24h TTL)
                from services import slide_cache
                slide_cache.cleanup_expired_caches()
                
                logger.info("Daily cleanup completed")
                last_cleanup = now

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        await asyncio.sleep(30)  # Check every 30 seconds

"""
Fireflies API Service
GraphQL API client for Fireflies.ai
"""

import logging
from typing import Optional

import httpx

from services import config as config_service

logger = logging.getLogger(__name__)

API_URL = "https://api.fireflies.ai/graphql"


def get_api_key(guild_id: Optional[int] = None) -> Optional[str]:
    """Get Fireflies API key for guild (no fallback to env)"""
    if guild_id:
        key = config_service.get_api_key(guild_id, "fireflies")
        if key:
            return key
    return None  # No fallback - guild must have its own key


async def list_transcripts(
    guild_id: Optional[int] = None, limit: int = 10
) -> Optional[list[dict]]:
    """
    List recent transcripts from Fireflies API.

    Returns:
        List of transcript dicts with id, title, date, duration
    """
    api_key = get_api_key(guild_id)
    if not api_key:
        logger.warning("No Fireflies API key configured")
        return None

    query = """
    query Transcripts($limit: Int) {
      transcripts(limit: $limit) {
        id
        title
        date
        duration
      }
    }
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                json={"query": query, "variables": {"limit": limit}},
                headers=headers,
                timeout=30,
            )

            data = response.json()

            if "errors" in data:
                logger.error(f"Fireflies API error: {data['errors']}")
                return None

            transcripts = data.get("data", {}).get("transcripts", [])
            logger.info(f"Listed {len(transcripts)} transcripts")
            return transcripts

    except Exception as e:
        logger.error(f"Fireflies API request failed: {e}")
        return None


async def get_transcript_count(guild_id: Optional[int] = None) -> int:
    """Get count of transcripts on Fireflies"""
    transcripts = await list_transcripts(guild_id, limit=50)
    return len(transcripts) if transcripts else 0


async def get_oldest_transcript(guild_id: Optional[int] = None) -> Optional[dict]:
    """Get the oldest transcript (by date) from Fireflies"""
    transcripts = await list_transcripts(guild_id, limit=50)
    if not transcripts:
        return None
    
    # Sort by date (oldest first) - date is timestamp in milliseconds
    oldest = min(transcripts, key=lambda t: t.get("date", 0))
    return oldest


def generate_fireflies_link(title: str, transcript_id: str) -> str:
    """
    Generate Fireflies share link from title and ID.
    
    Format: https://app.fireflies.ai/view/{slug}::{id}
    Slug: replace @ with -, spaces/special chars with -
    """
    import re
    # Replace @ and special chars with -
    slug = re.sub(r'[@\s.,;:!?\'"()\[\]{}]', '-', title)
    # Remove consecutive dashes and trim
    slug = re.sub(r'-+', '-', slug).strip('-')
    return f"https://app.fireflies.ai/view/{slug}::{transcript_id}"


async def get_transcript_by_id(
    transcript_id: str, guild_id: Optional[int] = None
) -> Optional[list[dict]]:
    """
    Get transcript sentences by ID from Fireflies API.

    Returns:
        List of dicts with name, time, content (same format as scraper)
    """
    api_key = get_api_key(guild_id)
    if not api_key:
        logger.warning("No Fireflies API key configured")
        return None

    query = """
    query Transcript($id: String!) {
      transcript(id: $id) {
        id
        title
        sentences {
          speaker_name
          text
          start_time
        }
      }
    }
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                json={"query": query, "variables": {"id": transcript_id}},
                headers=headers,
                timeout=30,
            )

            data = response.json()

            if "errors" in data:
                logger.error(f"Fireflies API error: {data['errors']}")
                return None

            transcript = data.get("data", {}).get("transcript")
            if not transcript:
                logger.warning(f"Transcript not found: {transcript_id}")
                return None

            sentences = transcript.get("sentences", [])

            # Convert to same format as scraper
            result = []
            for s in sentences:
                time_sec = int(s.get("start_time", 0))
                mins, secs = divmod(time_sec, 60)
                result.append(
                    {
                        "name": s.get("speaker_name", "Unknown"),
                        "time": f"{mins:02d}:{secs:02d}",
                        "content": s.get("text", ""),
                    }
                )

            logger.info(f"Got transcript with {len(result)} sentences")
            return result

    except Exception as e:
        logger.error(f"Fireflies API request failed: {e}")
        return None


async def add_to_live_meeting(
    meeting_link: str,
    guild_id: Optional[int] = None,
    title: Optional[str] = None,
    duration: int = 60,
) -> tuple[bool, str]:
    """
    Add Fireflies bot to a live meeting.

    Args:
        meeting_link: Valid meeting URL (Zoom, Google Meet, etc.)
        guild_id: Guild ID for API key lookup
        title: Optional meeting title
        duration: Meeting duration in minutes (15-120, default 60)

    Returns:
        Tuple of (success: bool, message: str)
    """
    api_key = get_api_key(guild_id)
    if not api_key:
        return False, "Chưa cấu hình Fireflies API key"

    mutation = """
    mutation AddToLiveMeeting($meeting_link: String!, $title: String, $duration: Int) {
      addToLiveMeeting(meeting_link: $meeting_link, title: $title, duration: $duration) {
        success
        message
      }
    }
    """

    variables = {
        "meeting_link": meeting_link,
        "duration": min(max(duration, 15), 120),  # Clamp 15-120
    }
    if title:
        variables["title"] = title[:256]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                json={"query": mutation, "variables": variables},
                headers=headers,
                timeout=30,
            )

            data = response.json()

            if "errors" in data:
                error_msg = data["errors"][0].get("message", "Unknown error")
                logger.error(f"Fireflies addToLiveMeeting error: {error_msg}")
                return False, f"API Error: {error_msg}"

            result = data.get("data", {}).get("addToLiveMeeting", {})
            if result.get("success"):
                logger.info(f"Bot added to meeting: {meeting_link}")
                return True, result.get("message", "Bot đã được thêm vào meeting!")
            else:
                return False, result.get("message", "Không thể thêm bot vào meeting")

    except Exception as e:
        logger.error(f"Fireflies addToLiveMeeting failed: {e}")
        return False, f"Error: {str(e)[:100]}"


async def delete_transcript(
    transcript_id: str, guild_id: Optional[int] = None
) -> tuple[bool, str]:
    """
    Delete a transcript from Fireflies.

    Args:
        transcript_id: Fireflies transcript ID
        guild_id: Guild ID for API key lookup

    Returns:
        Tuple of (success: bool, message: str)
    """
    api_key = get_api_key(guild_id)
    if not api_key:
        return False, "Chưa cấu hình Fireflies API key"

    mutation = """
    mutation DeleteTranscript($id: String!) {
      deleteTranscript(id: $id) {
        id
        title
      }
    }
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                json={"query": mutation, "variables": {"id": transcript_id}},
                headers=headers,
                timeout=30,
            )

            data = response.json()

            if "errors" in data:
                error_msg = data["errors"][0].get("message", "Unknown error")
                logger.error(f"Fireflies deleteTranscript error: {error_msg}")
                return False, f"API Error: {error_msg}"

            result = data.get("data", {}).get("deleteTranscript")
            if result:
                logger.info(f"Deleted transcript from Fireflies: {transcript_id}")
                return True, "Đã xóa transcript từ Fireflies!"
            else:
                return False, "Không thể xóa transcript"

    except Exception as e:
        logger.error(f"Fireflies deleteTranscript failed: {e}")
        return False, f"Error: {str(e)[:100]}"

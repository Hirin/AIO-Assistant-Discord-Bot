"""
Fireflies API Service
GraphQL API client for Fireflies.ai
"""

import logging
import os
from typing import Optional

import httpx

from services import config as config_service

logger = logging.getLogger(__name__)

API_URL = "https://api.fireflies.ai/graphql"


def get_api_key(guild_id: Optional[int] = None) -> Optional[str]:
    """Get Fireflies API key (guild-specific or env)"""
    if guild_id:
        key = config_service.get_api_key(guild_id, "fireflies")
        if key:
            return key
    return os.getenv("FIREFLIES_API_KEY")


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

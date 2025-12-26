"""
Fireflies Transcript Service

Upload audio to Gofile.io, send to Fireflies for transcription,
poll for completion, and parse transcript.
"""

import asyncio
import aiohttp
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GOFILE_API = "https://api.gofile.io"
FIREFLIES_API = "https://api.fireflies.ai/graphql"


@dataclass
class TranscriptSentence:
    """Single sentence with timestamp"""
    text: str
    start_time: float  # seconds
    end_time: float
    speaker_name: Optional[str] = None


@dataclass 
class Transcript:
    """Full transcript with sentences"""
    id: str
    title: str
    duration: float  # seconds
    sentences: list[TranscriptSentence]
    
    def to_text(self, include_timestamps: bool = True) -> str:
        """Convert to readable text format"""
        lines = []
        for s in self.sentences:
            if include_timestamps:
                ts = int(s.start_time)
                speaker = f"{s.speaker_name}: " if s.speaker_name else ""
                lines.append(f"[{ts}s] {speaker}{s.text}")
            else:
                lines.append(s.text)
        return "\n".join(lines)
    
    def get_segment(self, start_sec: float, end_sec: float) -> str:
        """Get transcript segment for a time range"""
        segment_sentences = [
            s for s in self.sentences 
            if s.start_time >= start_sec and s.start_time < end_sec
        ]
        lines = []
        for s in segment_sentences:
            ts = int(s.start_time)
            speaker = f"{s.speaker_name}: " if s.speaker_name else ""
            lines.append(f"[{ts}s] {speaker}{s.text}")
        return "\n".join(lines)


async def upload_to_gofile(file_path: str) -> str:
    """
    Upload file to Gofile.io and get public URL.
    No file size limit on free tier.
    
    Args:
        file_path: Path to file to upload
        
    Returns:
        Public URL for the file (direct download link)
    """
    logger.info(f"Uploading to Gofile.io: {file_path}")
    
    async with aiohttp.ClientSession() as session:
        # Step 1: Get best server
        async with session.get(f"{GOFILE_API}/servers") as resp:
            if resp.status != 200:
                raise Exception(f"Gofile getServer failed: {resp.status}")
            result = await resp.json()
            if result.get("status") != "ok":
                raise Exception(f"Gofile getServer failed: {result}")
            
            # Get first available server
            servers = result.get("data", {}).get("servers", [])
            if not servers:
                raise Exception("No Gofile servers available")
            server = servers[0].get("name", "store1")
        
        logger.info(f"Using Gofile server: {server}")
        
        # Step 2: Upload file to server
        upload_url = f"https://{server}.gofile.io/contents/uploadfile"
        
        with open(file_path, 'rb') as f:
            data = aiohttp.FormData()
            data.add_field('file', f, filename=file_path.split('/')[-1])
            
            async with session.post(upload_url, data=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Gofile upload failed: {resp.status} - {text}")
                
                result = await resp.json()
                
                if result.get("status") != "ok":
                    raise Exception(f"Gofile upload failed: {result}")
                
                # Get direct download URL
                download_url = result.get("data", {}).get("downloadPage")
                file_id = result.get("data", {}).get("fileId")
                
                # Construct direct download link
                # Format: https://store1.gofile.io/download/direct/{fileId}/{filename}
                filename = file_path.split('/')[-1]
                direct_url = f"https://{server}.gofile.io/download/direct/{file_id}/{filename}"
                
                logger.info(f"Uploaded to Gofile: {download_url}")
                logger.info(f"Direct URL: {direct_url}")
                
                # Return direct download URL for Fireflies
                return direct_url


async def upload_audio_to_fireflies(
    audio_url: str, 
    title: str, 
    api_key: str
) -> str:
    """
    Upload audio to Fireflies for transcription.
    
    Args:
        audio_url: Public URL of audio file
        title: Title for the transcript
        api_key: Fireflies API key
        
    Returns:
        Transcript ID
    """
    logger.info(f"Uploading to Fireflies: {title}")
    
    mutation = """
    mutation uploadAudio($input: AudioUploadInput) {
        uploadAudio(input: $input) {
            success
            title
            message
        }
    }
    """
    
    variables = {
        "input": {
            "url": audio_url,
            "title": title
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            FIREFLIES_API,
            json={"query": mutation, "variables": variables},
            headers=headers
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Fireflies upload failed: {resp.status} - {text}")
            
            result = await resp.json()
            
            if "errors" in result:
                raise Exception(f"Fireflies GraphQL error: {result['errors']}")
            
            data = result.get("data", {}).get("uploadAudio", {})
            if not data.get("success"):
                raise Exception(f"Fireflies upload failed: {data.get('message')}")
            
            logger.info(f"Fireflies upload queued: {data.get('title')}")
            # Note: uploadAudio doesn't return transcript_id directly
            # We need to poll transcripts list to find it
            return title  # Return title to find later


async def get_latest_transcript(api_key: str, title: str) -> Optional[Transcript]:
    """
    Get transcript by title from Fireflies.
    
    Args:
        api_key: Fireflies API key
        title: Title to search for
        
    Returns:
        Transcript if found and ready, None otherwise
    """
    query = """
    query Transcripts {
        transcripts {
            id
            title
            duration
            sentences {
                text
                start_time
                end_time
                speaker_name
            }
        }
    }
    """
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            FIREFLIES_API,
            json={"query": query},
            headers=headers
        ) as resp:
            if resp.status != 200:
                return None
            
            result = await resp.json()
            
            if "errors" in result:
                logger.error(f"Fireflies query error: {result['errors']}")
                return None
            
            transcripts = result.get("data", {}).get("transcripts", [])
            
            # Find by title
            for t in transcripts:
                if t.get("title") == title:
                    sentences = [
                        TranscriptSentence(
                            text=s.get("text", ""),
                            start_time=s.get("start_time", 0),
                            end_time=s.get("end_time", 0),
                            speaker_name=s.get("speaker_name")
                        )
                        for s in t.get("sentences", [])
                    ]
                    
                    # Only return if has sentences (processing complete)
                    if sentences:
                        return Transcript(
                            id=t.get("id"),
                            title=t.get("title"),
                            duration=t.get("duration", 0),
                            sentences=sentences
                        )
            
            return None


async def poll_transcript(
    title: str, 
    api_key: str,
    initial_wait: int = 720,  # 12 minutes
    poll_interval: int = 300,  # 5 minutes
    max_attempts: int = 10
) -> Transcript:
    """
    Poll Fireflies until transcript is ready.
    
    Args:
        title: Transcript title to look for
        api_key: Fireflies API key
        initial_wait: Initial wait time in seconds (default 12min)
        poll_interval: Time between polls in seconds (default 5min)
        max_attempts: Max number of poll attempts
        
    Returns:
        Transcript when ready
        
    Raises:
        TimeoutError if max attempts reached
    """
    logger.info(f"Waiting {initial_wait}s before first poll...")
    await asyncio.sleep(initial_wait)
    
    for attempt in range(max_attempts):
        logger.info(f"Polling for transcript '{title}' (attempt {attempt + 1}/{max_attempts})")
        
        transcript = await get_latest_transcript(api_key, title)
        
        if transcript:
            logger.info(f"Transcript ready: {transcript.id} ({transcript.duration}s)")
            return transcript
        
        if attempt < max_attempts - 1:
            logger.info(f"Not ready, waiting {poll_interval}s...")
            await asyncio.sleep(poll_interval)
    
    raise TimeoutError(f"Transcript '{title}' not ready after {max_attempts} attempts")


async def delete_transcript(transcript_id: str, api_key: str) -> bool:
    """
    Delete transcript from Fireflies.
    
    Args:
        transcript_id: Transcript ID to delete
        api_key: Fireflies API key
        
    Returns:
        True if successful
    """
    mutation = """
    mutation DeleteTranscript($transcriptId: String!) {
        deleteTranscript(id: $transcriptId) {
            success
            message
        }
    }
    """
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            FIREFLIES_API,
            json={"query": mutation, "variables": {"transcriptId": transcript_id}},
            headers=headers
        ) as resp:
            if resp.status != 200:
                logger.warning(f"Failed to delete transcript: {resp.status}")
                return False
            
            result = await resp.json()
            success = result.get("data", {}).get("deleteTranscript", {}).get("success", False)
            
            if success:
                logger.info(f"Deleted transcript: {transcript_id}")
            else:
                logger.warning(f"Failed to delete transcript: {result}")
            
            return success


def split_transcript_by_time(
    transcript: Transcript, 
    time_ranges: list[tuple[float, float]]
) -> list[str]:
    """
    Split transcript into segments based on time ranges.
    
    Args:
        transcript: Full transcript
        time_ranges: List of (start_sec, end_sec) tuples
        
    Returns:
        List of transcript segments as text
    """
    segments = []
    for start_sec, end_sec in time_ranges:
        segment = transcript.get_segment(start_sec, end_sec)
        segments.append(segment)
    
    return segments

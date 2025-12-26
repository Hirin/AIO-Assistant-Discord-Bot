"""
AssemblyAI Transcript Service

Upload audio to AssemblyAI for transcription,
poll for completion, and parse transcript with paragraphs.
"""

import asyncio
import aiohttp
import logging
import os
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ASSEMBLYAI_API = "https://api.assemblyai.com/v2"


@dataclass
class TranscriptParagraph:
    """Single paragraph with timestamp"""
    text: str
    start_time: float  # seconds
    end_time: float


@dataclass 
class Transcript:
    """Full transcript with paragraphs"""
    id: str
    title: str
    duration: float  # seconds
    paragraphs: list[TranscriptParagraph]
    
    def to_text(self, include_timestamps: bool = True) -> str:
        """Convert to readable text format"""
        lines = []
        for p in self.paragraphs:
            if include_timestamps:
                ts = int(p.start_time)
                lines.append(f"[{ts}s] {p.text}")
            else:
                lines.append(p.text)
        return "\n\n".join(lines)
    
    def get_segment(self, start_sec: float, end_sec: float) -> str:
        """Get transcript segment for a time range"""
        segment_paragraphs = [
            p for p in self.paragraphs 
            if p.start_time >= start_sec and p.start_time < end_sec
        ]
        lines = []
        for p in segment_paragraphs:
            ts = int(p.start_time)
            lines.append(f"[{ts}s] {p.text}")
        return "\n\n".join(lines)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for cache serialization"""
        return {
            "id": self.id,
            "title": self.title,
            "duration": self.duration,
            "paragraphs": [
                {
                    "text": p.text,
                    "start_time": p.start_time,
                    "end_time": p.end_time
                }
                for p in self.paragraphs
            ]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        """Create Transcript from dictionary (cache deserialization)"""
        paragraphs = [
            TranscriptParagraph(
                text=p["text"],
                start_time=p["start_time"],
                end_time=p["end_time"]
            )
            for p in data.get("paragraphs", [])
        ]
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            duration=data.get("duration", 0),
            paragraphs=paragraphs
        )


async def upload_file(file_path: str, api_key: str) -> str:
    """
    Upload audio/video file to AssemblyAI.
    AssemblyAI automatically extracts audio from video files.
    
    Args:
        file_path: Path to audio or video file
        api_key: AssemblyAI API key
        
    Returns:
        Upload URL for transcription
    """
    logger.info(f"Uploading file to AssemblyAI: {file_path}")
    
    headers = {"authorization": api_key}
    
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            async with session.post(
                f"{ASSEMBLYAI_API}/upload",
                headers=headers,
                data=f
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"AssemblyAI upload failed: {resp.status} - {text}")
                
                result = await resp.json()
                upload_url = result.get("upload_url")
                
                if not upload_url:
                    raise Exception(f"AssemblyAI upload failed: no upload_url in response")
                
                logger.info(f"File uploaded to AssemblyAI")
                return upload_url


async def start_transcription(
    audio_url: str, 
    api_key: str,
    language_code: str = "vi"
) -> str:
    """
    Start transcription job.
    
    Args:
        audio_url: URL from upload_audio
        api_key: AssemblyAI API key
        language_code: Language code (default: vi for Vietnamese)
        
    Returns:
        Transcript ID
    """
    logger.info(f"Starting AssemblyAI transcription")
    
    headers = {
        "authorization": api_key,
        "content-type": "application/json"
    }
    
    data = {
        "audio_url": audio_url,
        "language_code": language_code
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{ASSEMBLYAI_API}/transcript",
            headers=headers,
            json=data
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"AssemblyAI transcription start failed: {resp.status} - {text}")
            
            result = await resp.json()
            transcript_id = result.get("id")
            
            if not transcript_id:
                raise Exception("AssemblyAI transcription start failed: no id in response")
            
            logger.info(f"Transcription started: {transcript_id}")
            return transcript_id


async def poll_transcription(
    transcript_id: str, 
    api_key: str,
    poll_interval: int = 5,
    max_wait: int = 1800  # 30 minutes max
) -> dict:
    """
    Poll for transcription completion.
    
    Args:
        transcript_id: Transcript ID from start_transcription
        api_key: AssemblyAI API key
        poll_interval: Seconds between polls
        max_wait: Maximum wait time in seconds
        
    Returns:
        Transcript result dict
        
    Raises:
        TimeoutError if max_wait exceeded
        Exception if transcription fails
    """
    logger.info(f"Polling for transcription {transcript_id}...")
    
    headers = {"authorization": api_key}
    url = f"{ASSEMBLYAI_API}/transcript/{transcript_id}"
    
    elapsed = 0
    
    async with aiohttp.ClientSession() as session:
        while elapsed < max_wait:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"AssemblyAI poll failed: {resp.status} - {text}")
                
                result = await resp.json()
                status = result.get("status")
                
                if status == "completed":
                    logger.info(f"Transcription completed: {transcript_id}")
                    return result
                
                elif status == "error":
                    error = result.get("error", "Unknown error")
                    raise Exception(f"AssemblyAI transcription failed: {error}")
                
                else:
                    logger.debug(f"Transcription status: {status}")
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
    
    raise TimeoutError(f"Transcription {transcript_id} timed out after {max_wait}s")


async def get_paragraphs(transcript_id: str, api_key: str) -> list[TranscriptParagraph]:
    """
    Get paragraphs for a completed transcript.
    
    Args:
        transcript_id: Transcript ID
        api_key: AssemblyAI API key
        
    Returns:
        List of TranscriptParagraph
    """
    logger.info(f"Getting paragraphs for {transcript_id}")
    
    headers = {"authorization": api_key}
    url = f"{ASSEMBLYAI_API}/transcript/{transcript_id}/paragraphs"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"AssemblyAI get paragraphs failed: {resp.status} - {text}")
            
            result = await resp.json()
            paragraphs = result.get("paragraphs", [])
            
            return [
                TranscriptParagraph(
                    text=p.get("text", ""),
                    start_time=p.get("start", 0) / 1000,  # Convert ms to seconds
                    end_time=p.get("end", 0) / 1000
                )
                for p in paragraphs
            ]


async def transcribe_file(
    file_path: str,
    api_key: str,
    title: str = "Lecture",
    language_code: str = "vi",
    cache_id: str = None,  # Optional: for caching upload_url to avoid re-upload
) -> Transcript:
    """
    Full transcription pipeline: upload, transcribe, get paragraphs.
    Accepts both audio and video files - AssemblyAI extracts audio automatically.
    
    Args:
        file_path: Path to audio or video file
        api_key: AssemblyAI API key
        title: Title for the transcript
        language_code: Language code
        cache_id: Optional cache ID to save/retrieve upload_url
        
    Returns:
        Transcript object with paragraphs
    """
    file_url = None
    
    # Generate API key hash for cache key (so different API keys have separate caches)
    import hashlib
    api_key_hash = hashlib.md5(api_key.encode()).hexdigest()[:8]
    cache_stage_name = f"assemblyai_upload_{api_key_hash}"
    
    # Try to get cached upload_url first
    if cache_id:
        try:
            from services import lecture_cache
            aai_cache = lecture_cache.get_stage(cache_id, cache_stage_name)
            if aai_cache and aai_cache.get("upload_url"):
                file_url = aai_cache["upload_url"]
                logger.info(f"Using cached AssemblyAI upload_url (api_key: ...{api_key[-4:]})")
        except Exception as e:
            logger.warning(f"Error checking AssemblyAI upload cache: {e}")
    
    # Upload file if not cached
    if not file_url:
        file_url = await upload_file(file_path, api_key)
        
        # Cache the upload_url immediately
        if cache_id:
            try:
                from services import lecture_cache
                lecture_cache.save_stage(cache_id, cache_stage_name, {
                    "upload_url": file_url,
                    "file_path": file_path,
                })
                logger.info(f"Cached AssemblyAI upload_url (api_key: ...{api_key[-4:]})")
            except Exception as e:
                logger.warning(f"Error caching AssemblyAI upload_url: {e}")
    
    # Step 2: Start transcription
    transcript_id = await start_transcription(file_url, api_key, language_code)
    
    # Step 3: Poll for completion
    result = await poll_transcription(transcript_id, api_key)
    
    # Step 4: Get paragraphs
    paragraphs = await get_paragraphs(transcript_id, api_key)
    
    # Build Transcript object
    duration = result.get("audio_duration", 0)
    
    return Transcript(
        id=transcript_id,
        title=title,
        duration=duration,
        paragraphs=paragraphs
    )


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

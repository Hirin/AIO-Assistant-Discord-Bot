"""
Video Processing Service
Handles video info extraction and splitting
"""
import os
import logging
import asyncio
from typing import NamedTuple

logger = logging.getLogger(__name__)

MAX_PART_SIZE_MB = 380  # Leave buffer for 400MB limit


class VideoInfo(NamedTuple):
    duration: float  # seconds
    size_bytes: int
    width: int
    height: int


async def get_video_info(video_path: str) -> VideoInfo:
    """Get video duration, size, and resolution"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration,size",
        "-of", "json",
        video_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    
    import json
    data = json.loads(stdout.decode())
    
    stream = data.get("streams", [{}])[0]
    fmt = data.get("format", {})
    
    return VideoInfo(
        duration=float(fmt.get("duration", 0)),
        size_bytes=int(fmt.get("size", 0)),
        width=int(stream.get("width", 0)),
        height=int(stream.get("height", 0)),
    )


MAX_DURATION_SINGLE_PART = 7200  # 2 hours - Gemini 3 Flash struggles with longer videos


def calculate_num_parts(size_bytes: int, duration_seconds: float = 0) -> int:
    """Calculate number of parts needed based on file size and duration.
    
    Args:
        size_bytes: File size in bytes
        duration_seconds: Video duration in seconds (if 0, only size is used)
    """
    size_mb = size_bytes / (1024 * 1024)
    
    # Calculate parts needed by size
    if size_mb <= MAX_PART_SIZE_MB:
        parts_by_size = 1
    elif size_mb <= MAX_PART_SIZE_MB * 2:
        parts_by_size = 2
    else:
        parts_by_size = 3  # Max 3 parts
    
    # Calculate parts needed by duration (>2h = 2 parts, >4h = 3 parts)
    if duration_seconds > MAX_DURATION_SINGLE_PART * 2:
        parts_by_duration = 3
    elif duration_seconds > MAX_DURATION_SINGLE_PART:
        parts_by_duration = 2
    else:
        parts_by_duration = 1
    
    # Use the larger of the two
    return max(parts_by_size, parts_by_duration)


async def split_video(
    input_path: str,
    num_parts: int,
    output_dir: str = "/tmp",
) -> list[dict]:
    """
    Split video into N equal parts by duration
    
    Returns list of dicts with:
        - path: str
        - start_seconds: float
        - duration: float
    """
    if num_parts <= 1:
        info = await get_video_info(input_path)
        return [{
            "path": input_path,
            "start_seconds": 0,
            "duration": info.duration,
        }]
    
    info = await get_video_info(input_path)
    part_duration = info.duration / num_parts
    
    parts = []
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    for i in range(num_parts):
        start = i * part_duration
        output_path = os.path.join(output_dir, f"{base_name}_part{i+1}.mp4")
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", input_path,
            "-t", str(part_duration),
            "-c", "copy",  # Fast copy, no re-encode
            output_path
        ]
        
        logger.info(f"Splitting part {i+1}/{num_parts}: {start:.0f}s - {start+part_duration:.0f}s")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg failed to split part {i+1}")
        
        parts.append({
            "path": output_path,
            "start_seconds": start,
            "duration": part_duration,
        })
    
    return parts


async def extract_audio(video_path: str, output_dir: str = "/tmp") -> str:
    """
    Extract audio from video as MP3.
    
    Args:
        video_path: Path to video file
        output_dir: Directory to save audio file
        
    Returns:
        Path to extracted audio file
    """
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}_audio.mp3")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "libmp3lame",
        "-ab", "128k",  # 128kbps for smaller size
        "-ar", "44100",  # Standard sample rate
        output_path
    ]
    
    logger.info(f"Extracting audio from {video_path}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {stderr.decode()}")
    
    logger.info(f"Audio extracted: {output_path}")
    return output_path


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or H:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def extract_frame(video_path: str, seconds: int, output_dir: str = "/tmp") -> str:
    """
    Extract a single frame from video at specified timestamp.
    Returns path to the extracted frame image.
    """
    import uuid
    
    frame_filename = f"frame_{seconds}s_{uuid.uuid4().hex[:8]}.jpg"
    output_path = os.path.join(output_dir, frame_filename)
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seconds),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",  # High quality JPEG
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.warning(f"Failed to extract frame at {seconds}s: {stderr.decode()}")
        return None
    
    logger.info(f"Extracted frame at {seconds}s: {output_path}")
    return output_path


def cleanup_files(paths: list[str]) -> None:
    """Delete temporary files"""
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted: {path}")
        except Exception as e:
            logger.warning(f"Failed to delete {path}: {e}")

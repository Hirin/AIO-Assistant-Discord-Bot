"""
Gemini API Service for Video Lecture Summarization
Supports multi-part video processing with chaining
"""
import os
import time
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

# No global client - always create fresh per request


def get_client(api_key: Optional[str] = None):
    """
    Create Gemini client with given or env API key.
    Always creates a fresh client per request.
    """
    from google import genai
    
    if api_key:
        return genai.Client(api_key=api_key)
    
    # Fallback to env
    env_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not env_key:
        raise ValueError("No Gemini API key provided")
    return genai.Client(api_key=env_key)


async def upload_video(video_path: str, api_key: Optional[str] = None):
    """Upload video to Gemini Files API and wait for processing"""
    client = get_client(api_key)
    
    logger.info(f"Uploading video: {video_path}")
    start = time.time()
    
    # Upload (sync, but fast)
    myfile = client.files.upload(file=video_path)
    logger.info(f"Uploaded in {time.time()-start:.1f}s, name={myfile.name}")
    
    # Wait for processing
    while myfile.state.name == "PROCESSING":
        await asyncio.sleep(10)
        myfile = client.files.get(name=myfile.name)
        logger.info(f"  State: {myfile.state.name}")
    
    if myfile.state.name == "FAILED":
        raise ValueError(f"Video processing failed: {video_path}")
    
    logger.info(f"Video ready: {myfile.name}")
    return myfile


async def generate_lecture_summary(
    video_file,
    prompt: str,
    guild_id: Optional[int] = None,
    api_key: Optional[str] = None,
) -> str:
    """Generate lecture summary from video with thinking mode"""
    from google.genai import types
    
    client = get_client(api_key)
    
    logger.info("Generating lecture summary...")
    start = time.time()
    
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[video_file, prompt],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="high")
        ),
    )
    
    logger.info(f"Generated in {time.time()-start:.1f}s, {len(response.text)} chars")
    return response.text


async def merge_summaries(
    summaries: list[str],
    merge_prompt: str,
    slide_count: int = 0,
    full_transcript: str = "",
    api_key: Optional[str] = None,
) -> str:
    """Merge multiple part summaries into one, with slides and transcript context"""
    from google.genai import types
    
    client = get_client(api_key)
    
    # Build context with part summaries
    parts_text = ""
    for i, summary in enumerate(summaries, 1):
        parts_text += f"\n**PHẦN {i}:**\n{summary}\n"
    
    # Truncate transcript if too long (keep first 50k chars)
    if len(full_transcript) > 50000:
        full_transcript = full_transcript[:50000] + "\n...(truncated)"
    
    # Generate slide instructions based on count
    if slide_count > 0:
        slide_instructions = f"""Có {slide_count} trang slide
- Chèn `[-PAGE:X-]` để minh họa slide trang X (X là số trang 1-indexed)
- Chỉ chèn slide QUAN TRỌNG: diagram, công thức, bảng so sánh, code, hình minh họa
- Tối đa 5-10 slides tùy độ phức tạp bài giảng
- **QUY TẮC QUAN TRỌNG:**
  - CHỈ chèn slide khi nội dung slide TRỰC TIẾP liên quan đến đoạn văn bản ngay trước đó
  - Caption mô tả slide (trong ngoặc đơn sau slide) phải MÔ TẢ CHÍNH XÁC nội dung THỰC SỰ trong slide
  - KHÔNG viết caption dựa trên nội dung văn bản xung quanh - hãy nhìn vào slide và mô tả những gì BẠN THẤY"""
    else:
        slide_instructions = "(Không có slide - KHÔNG tạo [-PAGE:X-] markers)"
    
    # Build prompt
    full_prompt = merge_prompt.format(
        parts_summary=parts_text,
        slide_count=slide_count,
        slide_instructions=slide_instructions,
        full_transcript=full_transcript if full_transcript else "(Không có transcript)",
    )
    
    logger.info(f"Merging {len(summaries)} summaries (slides={slide_count}, transcript={len(full_transcript)} chars)...")
    start = time.time()
    
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="high")
        ),
    )
    
    logger.info(f"Merged in {time.time()-start:.1f}s")
    return response.text


def format_video_timestamps(text: str, video_url: str) -> str:
    """
    Convert [-SECONDSs-] markers to clickable timestamp links.
    Example: [-930s-] -> [[15:30]](<video_url&t=930>)
    """
    import re
    
    def seconds_to_mmss(seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    def replace_timestamp(match):
        seconds = int(match.group(1))
        mmss = seconds_to_mmss(seconds)
        return f"[[{mmss}]](<{video_url}&t={seconds}>)"
    
    # Pattern: [-123s-] or [-1234s-]
    pattern = r'\[-(\d+)s-\]'
    return re.sub(pattern, replace_timestamp, text)


def format_toc_hyperlinks(text: str, video_url: str) -> str:
    """
    Convert table of contents format [-"TOPIC"- | -SECONDSs-] to clickable hyperlinks.
    Example: [-"Tổng quan mô hình"- | -504s-] -> [08:24 - Tổng quan mô hình](<video_url&t=504>)
    """
    import re
    
    def seconds_to_mmss(seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    def replace_toc_entry(match):
        topic = match.group(1).strip()
        seconds = int(match.group(2))
        mmss = seconds_to_mmss(seconds)
        return f"[{mmss} - {topic}](<{video_url}&t={seconds}>)"
    
    # Pattern: [-"TOPIC"- | -SECONDSs-]
    pattern = r'\[-"([^"]+)"-\s*\|\s*-(\d+)s-\]'
    return re.sub(pattern, replace_toc_entry, text)


def parse_frames_and_text(text: str) -> list[tuple[str, int | None]]:
    """
    Parse text and split at [-FRAME:XXs-] markers.
    
    Returns list of tuples: (text_chunk, frame_seconds or None)
    Example: "Hello [-FRAME:100s-] World" -> [("Hello ", 100), (" World", None)]
    """
    import re
    
    pattern = r'\[-FRAME:(\d+)s-\]'
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Text before this frame marker
        text_before = text[last_end:match.start()]
        frame_seconds = int(match.group(1))
        
        if text_before.strip():
            parts.append((text_before, frame_seconds))
        else:
            parts.append(("", frame_seconds))
        
        last_end = match.end()
    
    # Remaining text after last marker
    remaining = text[last_end:]
    if remaining.strip():
        parts.append((remaining, None))
    
    # If no frames found, return original text
    if not parts:
        parts.append((text, None))
    
    return parts


def parse_pages_and_text(text: str) -> list[tuple[str, int | None]]:
    """
    Parse text and split at [-PAGE:X-] markers.
    
    Returns list of tuples: (text_chunk, page_number or None)
    Example: "Hello [-PAGE:5-] World" -> [("Hello ", 5), (" World", None)]
    """
    import re
    
    pattern = r'\[-PAGE:(\d+)-\]'
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Text before this page marker
        text_before = text[last_end:match.start()]
        page_num = int(match.group(1))
        
        if text_before.strip():
            parts.append((text_before, page_num))
        else:
            parts.append(("", page_num))
        
        last_end = match.end()
    
    # Remaining text after last marker
    remaining = text[last_end:]
    if remaining.strip():
        parts.append((remaining, None))
    
    # If no pages found, return original text
    if not parts:
        parts.append((text, None))
    
    return parts


def strip_page_markers(text: str) -> str:
    """
    Remove [-PAGE:X-] markers and their captions from text.
    Used when no slides are available.
    
    Example: 
        "Text [-PAGE:1-] (Caption here) more text" -> "Text more text"
    """
    import re
    
    # Pattern: [-PAGE:X-] optionally followed by (caption)
    pattern = r'\[-PAGE:\d+-\]\s*(?:\([^)]*\))?'
    return re.sub(pattern, '', text)


def cleanup_file(file, api_key: Optional[str] = None) -> None:
    """Delete uploaded file from Gemini"""
    try:
        client = get_client(api_key)
        client.files.delete(name=file.name)
        logger.info(f"Deleted Gemini file: {file.name}")
    except Exception as e:
        logger.warning(f"Failed to delete Gemini file: {e}")


async def summarize_pdfs(
    pdf_paths: list[str],
    prompt: str,
    api_key: Optional[str] = None,
    thinking_level: str = "high",
) -> str:
    """
    Summarize multiple PDF files using Gemini API.
    
    Args:
        pdf_paths: List of paths to PDF files
        prompt: The prompt to use for summarization
        api_key: Optional Gemini API key
        thinking_level: Thinking level for Gemini (minimal/low/medium/high)
    
    Returns:
        Generated summary text
    """
    from google.genai import types
    
    client = get_client(api_key)
    
    # Upload all PDFs
    uploaded_files = []
    try:
        for pdf_path in pdf_paths:
            uploaded = client.files.upload(file=pdf_path)
            uploaded_files.append(uploaded)
            logger.info(f"Uploaded PDF: {pdf_path} -> {uploaded.name}")
        
        # Build content with all files + prompt
        contents = uploaded_files + [prompt]
        
        # Generate with thinking
        logger.info(f"Calling Gemini with {len(pdf_paths)} PDFs, thinking={thinking_level}")
        start = time.time()
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=contents,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
            ),
        )
        
        logger.info(f"Generated in {time.time()-start:.1f}s, {len(response.text)} chars")
        return response.text
        
    finally:
        # Always cleanup uploaded files
        for f in uploaded_files:
            try:
                client.files.delete(name=f.name)
            except Exception as e:
                logger.warning(f"Failed to cleanup Gemini file {f.name}: {e}")


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL"""
    import re
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def make_youtube_timestamp_url(youtube_url: str, seconds: int) -> str:
    """Create YouTube URL with timestamp"""
    video_id = extract_youtube_id(youtube_url)
    if video_id:
        return f"https://youtube.com/watch?v={video_id}&t={seconds}"
    return youtube_url

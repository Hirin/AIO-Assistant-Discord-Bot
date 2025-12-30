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


# Default model and thinking level for all Gemini calls
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_THINKING = "high"


def _call_gemini_sync(
    client,
    contents: list,
    thinking_level: str = DEFAULT_THINKING,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Base helper for Gemini API calls.
    All Gemini generate_content calls should use this for consistency.
    
    Args:
        client: Gemini client instance
        contents: Content parts (video, text, images, etc.)
        thinking_level: minimal/low/medium/high (default: high)
        model: Model name (default: gemini-3-flash-preview)
    
    Returns:
        Response text
    """
    from google.genai import types
    
    start = time.time()
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
        ),
    )
    logger.info(f"Gemini call completed in {time.time()-start:.1f}s, {len(response.text)} chars")
    return response.text


async def _call_gemini(
    client,
    contents: list,
    thinking_level: str = DEFAULT_THINKING,
    model: str = DEFAULT_MODEL,
) -> str:
    """Async wrapper for _call_gemini_sync - runs in thread pool."""
    return await asyncio.to_thread(
        _call_gemini_sync, client, contents, thinking_level, model
    )


async def test_api(api_key: str) -> str:
    """
    Quick test if API key works.
    Uses minimal thinking for fast response.
    
    Args:
        api_key: Gemini API key to test
    
    Returns:
        Response text (should be short)
    
    Raises:
        Exception on API failure
    """
    client = get_client(api_key)
    return await _call_gemini(
        client,
        contents=["Say 'API OK' in 2 words"],
        thinking_level="minimal",
    )


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
    client = get_client(api_key)
    
    logger.info("Generating lecture summary...")
    return await _call_gemini(client, [video_file, prompt])


async def merge_summaries(
    summaries: list[str],
    merge_prompt: str,
    full_transcript: str = "",
    extra_context: str = "",
    chat_links: str = "",
    api_key: Optional[str] = None,
) -> str:
    """Merge multiple part summaries into one cohesive summary."""
    
    client = get_client(api_key)
    
    # Build context with part summaries
    parts_text = ""
    for i, summary in enumerate(summaries, 1):
        parts_text += f"\n**PHẦN {i}:**\n{summary}\n"
    
    # Truncate transcript if too long (keep first 50k chars)
    if len(full_transcript) > 50000:
        full_transcript = full_transcript[:50000] + "\n...(truncated)"
    
    # Format extra context section
    extra_context_section = ""
    if extra_context and extra_context.strip():
        extra_context_section = f"{extra_context}"
    
    # Build prompt
    full_prompt = merge_prompt.format(
        parts_summary=parts_text,
        full_transcript=full_transcript if full_transcript else "(Không có transcript)",
        extra_context=extra_context_section,
        chat_links=chat_links,
    )
    
    logger.info(f"Merging {len(summaries)} summaries (transcript={len(full_transcript)} chars, extra_context={len(extra_context)} chars, links={len(chat_links)} chars)...")
    
    return await _call_gemini(client, full_prompt)



async def summarize_meeting(
    transcript: str,
    pdf_path: str | None = None,
    prompt: str = "",
    api_key: str | None = None,
    pdf_links: str = "",
    retries: int = 3,
) -> str:
    """
    Unified meeting summary with Gemini multimodal.
    Handles both slides (PDF) and transcript in one call.
    
    Args:
        transcript: Meeting transcript text
        pdf_path: Optional path to PDF slides file
        prompt: Summary prompt
        api_key: Gemini API key
        pdf_links: Formatted links extracted from PDF for References section
        retries: Number of retry attempts
        
    Returns:
        Meeting summary
    """
    from google.genai import types
    
    client = get_client(api_key)
    
    logger.info(f"Generating meeting summary (Gemini multimodal, slides={'yes' if pdf_path else 'no'})...")
    
    # Upload PDF if provided
    pdf_file = None
    if pdf_path:
        logger.info(f"Uploading PDF: {pdf_path}")
        start_upload = time.time()
        pdf_file = client.files.upload(file=pdf_path)
        logger.info(f"PDF uploaded in {time.time()-start_upload:.1f}s, name={pdf_file.name}")
        
        # Wait for processing
        while pdf_file.state.name == "PROCESSING":
            await asyncio.sleep(5)
            pdf_file = client.files.get(name=pdf_file.name)
            logger.info(f"  PDF state: {pdf_file.state.name}")
        
        if pdf_file.state.name == "FAILED":
            raise ValueError(f"PDF processing failed: {pdf_path}")
    
    # Build prompt with pdf_links injected
    full_prompt = prompt
    if pdf_links:
        full_prompt = f"{prompt}\n\n**Links từ slides (dùng cho section 📚 Tài liệu & Links):**\n{pdf_links}"
    
    # Build content
    content = []
    if pdf_file:
        content.append(pdf_file)
    content.append(f"{full_prompt}\n\n**TRANSCRIPT:**\n{transcript}")
    
    start = time.time()
    
    def _generate():
        return client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=content,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="high")
            ),
        )
    
    # Retry loop
    last_error = None
    for attempt in range(retries):
        try:
            response = await asyncio.to_thread(_generate)
            summary = response.text
            
            logger.info(f"Meeting summary generated in {time.time()-start:.1f}s ({len(summary)} chars)")
            
            # Cleanup PDF file
            if pdf_file:
                try:
                    client.files.delete(name=pdf_file.name)
                    logger.info(f"Deleted PDF file: {pdf_file.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete PDF: {e}")
            
            return summary
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"Meeting summary attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 5 * (attempt + 1)
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
    
    # Cleanup on failure
    if pdf_file:
        try:
            client.files.delete(name=pdf_file.name)
        except Exception:
            pass
    
    raise Exception(f"Meeting summary failed after {retries} attempts: {last_error}")


async def summarize_transcript(
    transcript: str,
    system_prompt: str,
    slide_content: Optional[str] = None,
    api_key: Optional[str] = None,
    retries: int = 3,
) -> str:
    """
    Summarize transcript using Gemini API with thinking mode.
    
    Args:
        transcript: Meeting/lecture transcript text
        system_prompt: System prompt for summarization style
        slide_content: Optional slide content for context
        api_key: Gemini API key
        retries: Number of retry attempts
    
    Returns:
        Summary text or raises exception on failure
    """
    from google.genai import types
    
    client = get_client(api_key)
    
    # Inject slide content if provided
    full_prompt = system_prompt
    if slide_content:
        full_prompt += f"\n\n## Nội dung từ Slides:\n{slide_content}"
    
    # Build content - system prompt + transcript
    user_content = f"Tóm tắt cuộc họp sau:\n\n{transcript[:50000]}"  # Limit to 50k chars
    
    last_error = None
    for attempt in range(retries):
        try:
            logger.info(f"Gemini summarizing transcript (attempt {attempt + 1})...")
            start = time.time()
            
            # Run sync Gemini call in thread pool
            def _summarize():
                return client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=[
                        {"role": "user", "parts": [{"text": full_prompt + "\n\n" + user_content}]}
                    ],
                    config=types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(thinking_level="high")
                    ),
                )
            
            response = await asyncio.to_thread(_summarize)
            
            summary = response.text
            if summary and summary.strip():
                logger.info(f"Gemini summary generated in {time.time()-start:.1f}s, {len(summary)} chars")
                return summary
            else:
                logger.warning(f"Gemini returned empty summary (attempt {attempt + 1})")
                last_error = "Empty response"
                
        except Exception as e:
            last_error = str(e)
            logger.error(f"Gemini attempt {attempt + 1} failed: {e}")
        
        # Backoff before retry
        if attempt < retries - 1:
            backoff = 5 * (attempt + 1)
            logger.info(f"Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
    
    # All retries failed
    raise Exception(f"Gemini summarize failed after {retries} attempts: {last_error}")


def format_video_timestamps(text: str, video_url: str) -> str:
    """
    Convert [-SECONDSs-] markers to clickable timestamp links.
    Example: [-930s-] -> [15:30](<video_url&t=930>)
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
        # Format: [text](<url>) - angle brackets suppress Discord embeds
        return f"[{mmss}](<{video_url}&t={seconds}>)"
    
    # Pattern: [-123s-] or [-1234s-]
    pattern = r'\[-(\d+)s-\]'
    return re.sub(pattern, replace_timestamp, text)


def format_external_links(text: str) -> str:
    """
    Wrap external URLs with <> to hide Discord embed previews.
    Skips URLs that are already wrapped, already in markdown format, or are video timestamps.
    
    Example: "Check https://example.com for more" -> "Check <https://example.com> for more"
    """
    import re
    
    # Pattern to find URLs NOT in markdown links [text](url) or already wrapped
    # Negative lookbehind: not preceded by (< or ](
    # Negative lookahead: not followed by )> or just >
    url_pattern = r'(?<!](<)(?<!<)(https?://[^\s\)<>]+)(?!>)'
    
    def wrap_url(match):
        url = match.group(1)
        return f"<{url}>"
    
    return re.sub(url_pattern, wrap_url, text)


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
        # Format: [text](<url>) - angle brackets suppress Discord embeds
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


def parse_pages_and_text(text: str) -> list[tuple[str, int | None, str | None]]:
    """
    Parse text and split at [-PAGE:X-] or [-PAGE:X:"description"-] markers.
    
    Returns list of tuples: (text_chunk, page_number or None, description or None)
    Example: 
        "Hello [-PAGE:5:"CNN diagram"-] World" -> [("Hello ", 5, "CNN diagram"), (" World", None, None)]
    """
    import re
    
    # Pattern matches: [-PAGE:X-], [-PAGE:X:"description"-], [-PAGE:X:"description"]
    # The trailing dash before ] is optional since LLM sometimes omits it
    pattern = r'\[-PAGE:(\d+)(?::"([^"]+)")?-?\]'
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Text before this page marker
        text_before = text[last_end:match.start()]
        page_num = int(match.group(1))
        description = match.group(2)  # May be None
        
        if text_before.strip():
            parts.append((text_before, page_num, description))
        else:
            parts.append(("", page_num, description))
        
        last_end = match.end()
        
        # Skip orphan dots/whitespace right after the marker
        while last_end < len(text) and text[last_end] in ' \t\n.':
            if text[last_end] == '.':
                last_end += 1
                break  # Only skip one orphan dot
            last_end += 1
    
    # Remaining text after last marker
    remaining = text[last_end:]
    if remaining.strip():
        parts.append((remaining, None, None))
    
    # If no pages found, return original text
    if not parts:
        parts.append((text, None, None))
    
    return parts


def strip_page_markers(text: str) -> str:
    """
    Remove [-PAGE:X-] and [-PAGE:X:"description"-] markers from text.
    Used when no slides are available.
    
    Example: 
        "Text [-PAGE:1:"CNN diagram"-] more text" -> "Text more text"
    """
    import re
    
    # Pattern: [-PAGE:X-] or [-PAGE:X:"description"-] or [-PAGE:X:"description"] optionally followed by (caption)
    pattern = r'\[-PAGE:\d+(?::"[^"]+")?\-?\]\s*(?:\([^)]*\))?'
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
    pdf_links: str = "",
    api_key: Optional[str] = None,
    thinking_level: str = "high",
) -> str:
    """
    Summarize multiple PDF files using Gemini API.
    
    Args:
        pdf_paths: List of paths to PDF files
        prompt: The prompt to use for summarization
        pdf_links: Formatted string of links extracted from PDFs
        api_key: Optional Gemini API key
        thinking_level: Thinking level for Gemini (minimal/low/medium/high)
    
    Returns:
        Generated summary text
    """
    from google.genai import types
    
    client = get_client(api_key)
    
    # Format prompt with pdf_links
    formatted_prompt = prompt.format(pdf_links=pdf_links if pdf_links else "(Không có links)")
    
    # Run sync operations in thread pool to avoid blocking event loop
    def _upload_and_generate():
        uploaded_files = []
        try:
            for pdf_path in pdf_paths:
                uploaded = client.files.upload(file=pdf_path)
                uploaded_files.append(uploaded)
                logger.info(f"Uploaded PDF: {pdf_path} -> {uploaded.name}")
            
            # Build content with all files + prompt
            contents = uploaded_files + [formatted_prompt]
            
            # Generate with thinking
            logger.info(f"Calling Gemini with {len(pdf_paths)} PDFs, thinking={thinking_level}, links={len(pdf_links)} chars")
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
    
    return await asyncio.to_thread(_upload_and_generate)


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


async def match_slides_to_summary(
    summary: str,
    slide_images_b64: list[str],
    pdf_links: str = "",
    api_key: Optional[str] = None,
    max_slides: int = 60,
) -> str:
    """
    Use Gemini VLM to match slides to summary content.
    
    Args:
        summary: The merged summary text (without slide markers)
        slide_images_b64: List of base64 encoded slide images
        pdf_links: Formatted string of links extracted from PDF
        api_key: Optional Gemini API key
        max_slides: Maximum number of slides to process
        
    Returns:
        Summary with [-PAGE:X:"description"-] markers inserted
    """
    from google.genai import types
    from services.prompts import SLIDE_MATCHING_PROMPT
    
    if not slide_images_b64:
        logger.info("No slide images provided, skipping slide matching")
        return summary
    
    client = get_client(api_key)
    
    # Use all slides
    slides_to_use = slide_images_b64
    logger.info(f"Matching {len(slides_to_use)} slides to summary (links={len(pdf_links)} chars)")
    
    # Format the prompt with pdf_links
    prompt_with_links = SLIDE_MATCHING_PROMPT.format(pdf_links=pdf_links if pdf_links else "(Không có links)")
    
    def _call_gemini():
        # Build content with slides + prompt
        content_parts = []
        
        for img_b64 in slides_to_use:
            content_parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_b64
                }
            })
        
        content_parts.append({"text": prompt_with_links + summary})
        
        start = time.time()
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[{"role": "user", "parts": content_parts}],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="high")
            ),
        )
        logger.info(f"Slide matching completed in {time.time()-start:.1f}s")
        return response.text
    
    return await asyncio.to_thread(_call_gemini)


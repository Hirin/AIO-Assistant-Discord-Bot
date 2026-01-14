"""
Fireflies Web Scraper
Extract audio URL from Fireflies.ai page using Playwright.
Bypasses the need for paid API access.
"""
import asyncio
import logging
import os
import re
import tempfile
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


async def scrape_audio_url(transcript_id: str) -> Optional[str]:
    """
    Scrape audio URL from Fireflies page using Playwright.
    
    Args:
        transcript_id: Fireflies transcript ID
        
    Returns:
        Signed CDN URL for audio file, or None if not found
    """
    from playwright.async_api import async_playwright
    
    url = f"https://app.fireflies.ai/view/{transcript_id}"
    logger.info(f"Scraping audio URL from: {url}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Navigate to page
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait for content to load (longer for audio player)
            await asyncio.sleep(5)
            
            # Close login modal if present
            try:
                close_btn = page.locator('[aria-label="close"]').first
                if await close_btn.is_visible(timeout=2000):
                    await close_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            
            # Scroll to trigger lazy loading
            await page.evaluate("window.scrollTo(0, 500)")
            await asyncio.sleep(2)
            
            # Extract audio URL from page source
            html_content = await page.content()
            
            # Use transcript_id directly in pattern for exact match
            # URL format: https://cdn.fireflies.ai/{transcript_id}/audio.mp3?...
            pattern = rf'https://cdn\.fireflies\.ai/{re.escape(transcript_id)}/audio\.mp3\?[^"<>\s]+'
            matches = re.findall(pattern, html_content)
            
            await browser.close()
            
            if matches:
                audio_url = matches[0].replace('\\u0026', '&').replace('&amp;', '&')
                logger.info(f"Found audio URL: {audio_url[:100]}...")
                return audio_url
            else:
                logger.warning(f"No audio URL found for transcript {transcript_id}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to scrape audio URL: {e}")
        return None


async def download_audio(url: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Download audio file from signed CDN URL.
    
    Args:
        url: Signed CDN URL
        output_path: Optional output path (default: temp file)
        
    Returns:
        Path to downloaded file, or None on failure
    """
    if not output_path:
        output_path = os.path.join(tempfile.gettempdir(), "fireflies_audio.mp3")
    
    logger.info(f"Downloading audio to: {output_path}")
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            file_size = os.path.getsize(output_path)
            logger.info(f"Downloaded audio: {file_size / 1024 / 1024:.1f} MB")
            return output_path
            
    except Exception as e:
        logger.error(f"Failed to download audio: {e}")
        return None


async def get_transcript_audio(transcript_id: str) -> Optional[str]:
    """
    Complete flow: scrape URL and download audio.
    
    Args:
        transcript_id: Fireflies transcript ID
        
    Returns:
        Path to downloaded audio file, or None on failure
    """
    # Scrape URL
    audio_url = await scrape_audio_url(transcript_id)
    if not audio_url:
        return None
    
    # Download
    output_path = os.path.join(tempfile.gettempdir(), f"fireflies_{transcript_id}.mp3")
    return await download_audio(audio_url, output_path)


async def get_meeting_transcript(
    transcript_id: str,
    guild_id: int,
) -> Optional[list[dict]]:
    """
    Full flow: scrape audio from Fireflies, transcribe with AssemblyAI.
    Returns transcript in same format as fireflies_api.get_transcript_by_id().
    
    Args:
        transcript_id: Fireflies transcript ID
        guild_id: Guild ID for AssemblyAI API key lookup
        
    Returns:
        List of dicts with name, time, content (same format as scraper)
        None on failure
    """
    from services import config as config_service
    from services import assemblyai_transcript
    
    # Get AssemblyAI API key
    api_key = config_service.get_global_assemblyai_api(guild_id)
    if not api_key:
        logger.error("No AssemblyAI API key configured for meetings")
        return None
    
    # Step 1: Scrape and download audio from Fireflies
    logger.info(f"Getting audio for transcript {transcript_id}")
    audio_path = await get_transcript_audio(transcript_id)
    if not audio_path:
        logger.error(f"Failed to get audio for transcript {transcript_id}")
        return None
    
    try:
        # Step 2: Transcribe with AssemblyAI
        logger.info("Transcribing audio with AssemblyAI")
        transcript = await assemblyai_transcript.transcribe_file(
            audio_path,
            api_key=api_key,
            title=f"Meeting {transcript_id}",
            language_code="vi"
        )
        
        # Step 3: Convert to same format as fireflies_api.get_transcript_by_id()
        result = []
        for p in transcript.paragraphs:
            time_sec = int(p.start_time)
            mins, secs = divmod(time_sec, 60)
            result.append({
                "name": "Speaker",  # AssemblyAI free tier doesn't have speaker diarization
                "time": f"{mins:02d}:{secs:02d}",
                "content": p.text,
            })
        
        logger.info(f"Transcribed with {len(result)} paragraphs")
        return result
        
    except Exception as e:
        logger.error(f"Failed to transcribe: {e}")
        return None
    finally:
        # Cleanup temp audio file
        try:
            os.remove(audio_path)
        except Exception:
            pass

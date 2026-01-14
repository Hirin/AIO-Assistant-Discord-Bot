"""
Fireflies Scraper Service
Scrape transcripts from Fireflies.ai shared links
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def clean_title(title: str) -> str:
    """Clean meaningless titles like 'email@gmail.com - date - Untitled' to 'No Title'"""
    if not title:
        return "No Title"
    
    # Check for meaningless patterns
    title_lower = title.lower()
    if any(x in title_lower for x in ["@gmail.com", "@yahoo.com", "@outlook.com", "untitled"]):
        # Check if it's just email - date - Untitled pattern
        if re.match(r'^[\w.-]+@[\w.-]+\s*-.*-\s*untitled$', title_lower, re.IGNORECASE):
            return "No Title"
    
    # Remove leading email if present
    if "@" in title:
        # Pattern: email - date - actual_title
        parts = title.split(" - ")
        if len(parts) >= 3 and "@" in parts[0]:
            # Use last part as title if it's meaningful
            last_part = parts[-1].strip()
            if last_part.lower() not in ["untitled", ""]:
                return last_part
            return "No Title"
    
    return title.strip() or "No Title"

async def scrape_fireflies(
    url: str, timeout: int = 60, retries: int = 3
) -> Optional[tuple[str, list[dict]]]:
    """
    Scrape transcript from Fireflies.ai shared link.

    Args:
        url: Fireflies shared meeting URL
        timeout: Timeout in seconds
        retries: Number of retry attempts

    Returns:
        Tuple of (title, transcript_data) or None if failed
    """
    from playwright.async_api import async_playwright

    for attempt in range(retries):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                logger.info(
                    f"Scraping Fireflies (attempt {attempt + 1}): {url[:50]}..."
                )

                await page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout * 1000
                )
                await page.wait_for_timeout(5000)

                # Close login modal if present
                try:
                    close_btn = page.locator("button.x, button.lciBA-d")
                    if await close_btn.count() > 0:
                        await close_btn.first.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Extract transcript from __NEXT_DATA__
                transcript_data = await page.evaluate("""
                    () => {
                        const pageProps = window.__NEXT_DATA__?.props?.pageProps || {};
                        const note = pageProps.initialMeetingNote;
                        
                        // Get title from TitleText span or from note data
                        let title = '';
                        const titleEl = document.querySelector('[data-sentry-element="TitleText"]');
                        if (titleEl) {
                            title = titleEl.innerText || '';
                        } else if (note && note.title) {
                            title = note.title;
                        }
                        
                        if (note && note.sentences) {
                            function formatTime(seconds) {
                                if (!seconds) return '00:00';
                                const mins = Math.floor(seconds / 60);
                                const secs = Math.floor(seconds % 60);
                                return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                            }
                            
                            return {
                                source: 'next_data',
                                title: title,
                                data: note.sentences.map(s => ({
                                    name: s.speaker_name || 'Unknown',
                                    time: formatTime(s.start_time),
                                    content: s.text || ''
                                }))
                            };
                        }
                        
                        // Fallback: scrape from DOM
                        const containers = document.querySelectorAll('.sc-e4f1b385-1');
                        const container = containers[2] || containers[1] || containers[0];
                        if (container) {
                            const entries = [];
                            const text = container.innerText;
                            const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                            const tsRegex = /^\\d{1,2}:\\d{2}(:\\d{2})?$/;
                            
                            for (let i = 0; i < lines.length; i++) {
                                if (tsRegex.test(lines[i])) {
                                    const time = lines[i];
                                    let name = i > 0 ? lines[i-1] : 'Unknown';
                                    
                                    let content = '';
                                    let j = i + 1;
                                    while (j < lines.length) {
                                        if (tsRegex.test(lines[j])) break;
                                        if (j + 1 < lines.length && tsRegex.test(lines[j+1])) break;
                                        content += lines[j] + ' ';
                                        j++;
                                    }
                                    
                                    if (content.trim()) {
                                        entries.push({ name, time, content: content.trim() });
                                    }
                                }
                            }
                            
                            if (entries.length > 0) {
                                return { source: 'dom', title: title, data: entries };
                            }
                        }
                        
                        // Debug: return what we found
                        return { 
                            source: 'none', 
                            debug: {
                                hasNextData: !!window.__NEXT_DATA__,
                                hasPageProps: !!pageProps,
                                pagePropsKeys: Object.keys(pageProps),
                                hasInitialMeetingNote: !!note,
                                noteKeys: note ? Object.keys(note) : [],
                                hasSentences: !!(note && note.sentences),
                                sentencesLength: note && note.sentences ? note.sentences.length : 0
                            }
                        };
                    }
                """)

                await browser.close()

                if transcript_data and transcript_data.get("source") != "none":
                    logger.info(f"Transcript source: {transcript_data.get('source')}")
                    data = transcript_data.get("data", [])

                    # Clean trailing avatar initials
                    for entry in data:
                        content = entry["content"]
                        content = re.sub(r"[.!?,]? [A-Za-z]$", "", content)
                        entry["content"] = content.strip()

                    logger.info(f"Scraped {len(data)} entries")
                    
                    # Get title from scraped data
                    title = transcript_data.get("title", "") or ""
                    title = clean_title(title)
                    
                    return (title, data)

                # No data found - will retry
                debug_info = transcript_data.get("debug", {}) if transcript_data else {}
                logger.warning(
                    f"No transcript (attempt {attempt + 1}). Debug: {debug_info}"
                )

                if attempt < retries - 1:
                    backoff = 2**attempt
                    logger.info(f"Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)
                    continue

        except Exception as e:
            logger.error(f"Scrape attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 2**attempt
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    return None


def format_transcript(entries: list[dict]) -> str:
    """Format transcript entries into readable text"""
    lines = []
    for entry in entries:
        lines.append(f"[{entry['time']}] {entry['name']}: {entry['content']}")
    return "\n".join(lines)


def format_transcript_for_llm(entries: list[dict]) -> str:
    """
    Format transcript for LLM with seconds in timestamps.
    Example: [117s] John: Hello
    """
    lines = []
    for entry in entries:
        time_str = entry.get("time", "00:00")
        try:
            # Parse HH:MM:SS or MM:SS to seconds
            parts = [int(p) for p in time_str.split(":")]
            if len(parts) == 3:
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                seconds = parts[0] * 60 + parts[1]
            else:
                seconds = 0
                
            lines.append(f"[{seconds}s] {entry['name']}: {entry['content']}")
        except ValueError:
            # Fallback if parse fails
            lines.append(f"[{time_str}] {entry['name']}: {entry['content']}")
            
    return "\n".join(lines)


def process_summary_timestamps(summary: str, fireflies_id_or_url: str) -> str:
    """
    Process LLM summary to convert [-123s-] to [MM:SS](link).
    
    Args:
        summary: Raw summary from LLM
        fireflies_id_or_url: Fireflies ID (01K...) or full URL
        
    Returns:
        Summary with hyperlinked timestamps
    """
    if "https://" in fireflies_id_or_url:
        base_url = fireflies_id_or_url
        # Remove existing query params if any
        if "?" in base_url:
            base_url = base_url.split("?")[0]
    else:
        base_url = f"https://app.fireflies.ai/view/{fireflies_id_or_url}"
    
    # Pre-process: normalize multi-timestamp patterns
    # [-3101s-, -4134s-] -> [-3101s-] (take first timestamp)
    # [-3101s-,-4134s-] -> [-3101s-]
    summary = re.sub(r'\[(-\d+s-),\s*-\d+s-\]', r'[\1]', summary)
    
    # Also handle variants like [-3101s- - -4134s-] or [-3101s-~-4134s-]
    summary = re.sub(r'\[(-\d+s-)\s*[-~]\s*-\d+s-\]', r'[\1]', summary)
        
    def replace_ts(match):
        try:
            seconds = int(match.group(1))
            
            # Convert to MM:SS or HH:MM:SS
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            
            if h > 0:
                time_str = f"{h:02d}:{m:02d}:{s:02d}"
            else:
                time_str = f"{m:02d}:{s:02d}"
                
            return f"[{time_str}](<{base_url}?t={seconds}>)"
        except ValueError:
            return match.group(0)
            
    # Regex for [-123s-]
    return re.sub(r"\[-(\d+)s-\]", replace_ts, summary)

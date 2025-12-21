#!/usr/bin/env python3
"""
Fireflies.ai Transcript Scraper
Sử dụng Playwright để cào transcript từ các shared meeting links
Run: uv run scrape_fireflies.py <url>
"""
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
# ]
# ///

import asyncio
import csv
import json
import re
import sys
from pathlib import Path


async def scrape_fireflies(url: str, output_file: str = "transcript.csv") -> None:
    """Scrape transcript from Fireflies.ai shared link"""
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print(f"🌐 Opening: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Wait for page to fully load and JS to render
        await page.wait_for_timeout(5000)
        
        # Close login modal if present
        try:
            close_btn = page.locator("button.x, button.lciBA-d")
            if await close_btn.count() > 0:
                await close_btn.first.click()
                print("✅ Closed login modal")
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        # Try to get transcript from __NEXT_DATA__ first (most reliable)
        print("📝 Extracting transcript...")
        transcript_data = await page.evaluate("""
            () => {
                const pageProps = window.__NEXT_DATA__?.props?.pageProps || {};
                const note = pageProps.initialMeetingNote;
                
                if (note && note.sentences) {
                    return note.sentences.map(s => ({
                        name: s.speaker_name || 'Unknown',
                        time: formatTime(s.start_time),
                        content: s.text || ''
                    }));
                }
                
                function formatTime(seconds) {
                    if (!seconds) return '00:00';
                    const mins = Math.floor(seconds / 60);
                    const secs = Math.floor(seconds % 60);
                    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                }
                
                // Fallback: scrape from DOM
                const containers = document.querySelectorAll('.sc-e4f1b385-1');
                const container = containers[2] || containers[0];
                if (!container) return [];
                
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
                
                return entries;
            }
        """)
        
        await browser.close()
        
        if not transcript_data:
            print("❌ Không tìm thấy transcript!")
            return
        
        # Clean trailing avatar initials from content
        # Pattern: punctuation + space + single letter at end (e.g., ". Z", "? H")
        for entry in transcript_data:
            content = entry['content']
            # Remove patterns like ". Z", "? H", " Z" at end
            content = re.sub(r'[.!?,]? [A-Za-z]$', '', content)
            entry['content'] = content.strip()
        
        # Save to CSV
        output_path = Path(output_file)
        with output_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'time', 'content'])
            writer.writeheader()
            writer.writerows(transcript_data)
        
        print(f"✅ Saved {len(transcript_data)} entries to {output_file}")
        
        # Preview first 5 entries
        print("\n📋 Preview:")
        for entry in transcript_data[:5]:
            print(f"  [{entry['time']}] {entry['name']}: {entry['content'][:60]}...")


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run scrape_fireflies.py <fireflies_url> [output.csv]")
        print("Example: uv run scrape_fireflies.py 'https://app.fireflies.ai/view/...'")
        sys.exit(1)
    
    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "transcript.csv"
    
    # Install playwright browsers on first run
    import subprocess
    subprocess.run(["playwright", "install", "chromium"], capture_output=True)
    
    await scrape_fireflies(url, output)


if __name__ == "__main__":
    asyncio.run(main())

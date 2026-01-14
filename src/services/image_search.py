"""
Google Image Search Service
Scrape Google Images for illustrations
"""

import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Google Images search via scraping
GOOGLE_IMAGES_URL = "https://www.google.com/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def search_images_google(query: str, num_results: int = 10) -> list[str]:
    """
    Search Google Images and return list of image URLs.
    
    Args:
        query: Search query
        num_results: Max number of URLs to return
        
    Returns:
        List of direct image URLs
    """
    params = {
        "q": query,
        "tbm": "isch",
        "hl": "en",
    }
    
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(GOOGLE_IMAGES_URL, params=params, headers=HEADERS)
            
            if resp.status_code != 200:
                logger.warning(f"Google Images returned {resp.status_code}")
                return []
            
            # Extract image URLs from response
            results = []
            patterns = [
                r'"(https?://[^"]+\.(?:jpg|jpeg|png|gif|webp)[^"]*)"',
                r'\["(https?://[^"]+\.(?:jpg|jpeg|png|gif|webp)[^"]*)"',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, resp.text, re.IGNORECASE)
                for match in matches:
                    # Filter out Google's own URLs
                    if "google" not in match.lower() and "gstatic" not in match.lower():
                        if match not in results:
                            results.append(match)
                            if len(results) >= num_results:
                                break
                if len(results) >= num_results:
                    break
            
            logger.info(f"Found {len(results)} image URLs for '{query[:30]}...'")
            return results[:num_results]
            
    except Exception as e:
        logger.error(f"Google Images search failed: {e}")
        return []


async def download_first_valid(
    urls: list[str], 
    max_tries: int = 5,
    min_size: int = 5000,
) -> tuple[Optional[bytes], Optional[str]]:
    """
    Try downloading images until one succeeds.
    
    Args:
        urls: List of image URLs to try
        max_tries: Max number of URLs to attempt
        min_size: Minimum image size in bytes
        
    Returns:
        Tuple of (image_bytes, content_type) or (None, None)
    """
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in urls[:max_tries]:
            try:
                resp = await client.get(url, headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Accept": "image/*,*/*;q=0.8",
                })
                
                content_type = resp.headers.get("content-type", "")
                
                if resp.status_code == 200 and "image" in content_type:
                    if len(resp.content) >= min_size:
                        logger.info(f"Downloaded image: {len(resp.content)} bytes")
                        return resp.content, content_type
                    else:
                        logger.debug(f"Image too small: {len(resp.content)} bytes")
                        
            except Exception as e:
                logger.debug(f"Failed to download {url[:50]}: {e}")
                continue
    
    logger.warning("No valid images could be downloaded")
    return None, None


async def search_and_download(query: str, max_tries: int = 5) -> Optional[bytes]:
    """
    Search Google Images and download first valid result.
    
    Args:
        query: Search query
        max_tries: Max download attempts
        
    Returns:
        Image bytes or None
    """
    urls = await search_images_google(query)
    if not urls:
        return None
    
    data, _ = await download_first_valid(urls, max_tries)
    return data

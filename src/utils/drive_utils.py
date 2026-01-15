"""
Drive File Validation Utilities
Check file types from Google Drive using magic bytes (first 1KB)
"""
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

# Magic bytes signatures for common file types
MAGIC_BYTES = {
    "pdf": [b"%PDF-"],
    "video": [
        b"\x00\x00\x00\x18ftyp",  # MP4
        b"\x00\x00\x00\x1cftyp",  # MP4 variant
        b"\x00\x00\x00\x20ftyp",  # MP4 variant
        b"\x1aE\xdf\xa3",         # MKV/WebM
        b"RIFF",                   # AVI
        b"\x00\x00\x01\xba",       # MPEG
        b"\x00\x00\x01\xb3",       # MPEG
    ],
    "image": [
        b"\x89PNG",                # PNG
        b"\xff\xd8\xff",           # JPEG
        b"GIF8",                   # GIF
        b"RIFF",                   # WebP (RIFF container)
    ],
    "html": [
        b"<!DOCTYPE",
        b"<html",
        b"<HTML",
    ],
}


def detect_file_type(data: bytes) -> str:
    """
    Detect file type from magic bytes.
    
    Args:
        data: First bytes of the file (at least 20 bytes recommended)
        
    Returns:
        File type: "pdf", "video", "image", "html", or "unknown"
    """
    for file_type, signatures in MAGIC_BYTES.items():
        for sig in signatures:
            if data.startswith(sig):
                return file_type
    return "unknown"


def extract_drive_file_id(url: str) -> Optional[str]:
    """Extract Google Drive file ID from various URL formats"""
    import re
    
    patterns = [
        r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/.*?/d/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/uc\?.*?id=([a-zA-Z0-9_-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def validate_drive_file(
    url: str, 
    expected_type: str = None,
    timeout: int = 15,
) -> tuple[bool, str, str]:
    """
    Validate a Google Drive file by checking magic bytes (first 1KB).
    
    Handles Google Drive virus scan confirmation for large files.
    
    Args:
        url: Google Drive share link or download URL
        expected_type: Expected file type ("pdf", "video", "image") or None for auto-detect
        timeout: Request timeout in seconds
        
    Returns:
        Tuple of (is_valid, detected_type, download_url)
        - is_valid: True if file matches expected type (or any valid type if expected_type=None)
        - detected_type: Detected file type ("pdf", "video", "image", "html", "unknown")
        - download_url: Direct download URL to use (may be confirmed URL for large files)
    """
    
    # Extract file ID if it's a share link
    file_id = extract_drive_file_id(url)
    if not file_id:
        return False, "invalid_url", url
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            # Download first 1KB using Range header
            resp = await client.get(
                download_url,
                headers={"Range": "bytes=0-1023"}
            )
            
            if resp.status_code not in (200, 206):
                logger.warning(f"Drive file check failed: status {resp.status_code}")
                return False, "error", download_url
            
            first_bytes = resp.content
            detected_type = detect_file_type(first_bytes)
            
            # If HTML, check if it's virus scan confirmation or access denied
            if detected_type == "html":
                html_text = first_bytes.decode('utf-8', errors='ignore')
                
                # Check for virus scan confirmation form
                if 'confirm=' in html_text or 'download' in html_text.lower():
                    # Try the confirmed download URL
                    confirmed_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
                    
                    # Re-check with confirmed URL
                    resp2 = await client.get(
                        confirmed_url,
                        headers={"Range": "bytes=0-1023"}
                    )
                    
                    if resp2.status_code in (200, 206):
                        first_bytes = resp2.content
                        detected_type = detect_file_type(first_bytes)
                        download_url = confirmed_url
                        logger.info(f"Used confirmed URL, detected: {detected_type}")
                
                # Still HTML = access denied or invalid link
                if detected_type == "html":
                    logger.warning("Drive file returned HTML - access denied or invalid")
                    return False, "access_denied", download_url
            
            logger.info(f"Drive file validation: {detected_type} (first bytes: {first_bytes[:10]})")
            
            # Check against expected type
            if expected_type:
                is_valid = detected_type == expected_type
            else:
                # Any recognized type except html is valid
                is_valid = detected_type not in ("html", "unknown", "access_denied")
            
            return is_valid, detected_type, download_url
            
    except Exception as e:
        logger.warning(f"Drive file validation failed: {e}")
        return False, "error", download_url


async def check_drive_pdf(url: str) -> tuple[bool, str]:
    """
    Quick check if a Drive link points to a PDF file.
    
    Args:
        url: Google Drive share link
        
    Returns:
        Tuple of (is_pdf, download_url or error_message)
    """
    is_valid, file_type, download_url = await validate_drive_file(url, expected_type="pdf")
    
    if is_valid:
        return True, download_url
    elif file_type in ("html", "access_denied"):
        return False, "File không thể tải (access denied hoặc không chia sẻ public)"
    elif file_type == "invalid_url":
        return False, "Link Drive không hợp lệ"
    else:
        return False, f"File không phải PDF (detected: {file_type})"


async def check_drive_video(url: str) -> tuple[bool, str]:
    """
    Quick check if a Drive link points to a video file.
    
    Args:
        url: Google Drive share link
        
    Returns:
        Tuple of (is_video, download_url or error_message)
    """
    is_valid, file_type, download_url = await validate_drive_file(url, expected_type="video")
    
    if is_valid:
        return True, download_url
    elif file_type in ("html", "access_denied"):
        return False, "File không thể tải (access denied hoặc không chia sẻ public)"
    elif file_type == "invalid_url":
        return False, "Link Drive không hợp lệ"
    else:
        return False, f"File không phải video (detected: {file_type})"

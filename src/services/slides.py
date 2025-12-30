"""
Slides Service

Convert PDF slides to images for embedding in Discord.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread pool for CPU-intensive PDF operations
_executor = ThreadPoolExecutor(max_workers=2)


class SlidesError(Exception):
    """Error when processing slides/PDF"""
    pass


def pdf_to_images(pdf_path: str, output_dir: str = "/tmp") -> list[str]:
    """
    Convert PDF to images (one per page).
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save images
        
    Returns:
        List of image paths
        
    Raises:
        SlidesError: If PDF is invalid or conversion fails
    """
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
    except ImportError:
        raise SlidesError("pdf2image not installed. Run: pip install pdf2image")
    
    # Validate PDF file exists and has content
    if not os.path.exists(pdf_path):
        raise SlidesError(f"File không tồn tại: {pdf_path}")
    
    file_size = os.path.getsize(pdf_path)
    file_ext = Path(pdf_path).suffix.lower()
    size_str = f"{file_size / 1024:.1f}KB" if file_size < 1024*1024 else f"{file_size / 1024 / 1024:.1f}MB"
    
    if file_size < 1000:  # Less than 1KB is likely not a valid PDF
        raise SlidesError(f"File quá nhỏ ({size_str}) - có thể link sai hoặc tải thất bại")
    
    # Check magic bytes (PDF should start with %PDF)
    with open(pdf_path, 'rb') as f:
        header = f.read(20)
        
        # Detect actual file type
        if header.startswith(b'%PDF'):
            detected_type = "PDF"
        elif header.startswith(b'<!DOCTYPE') or header.startswith(b'<html') or header.startswith(b'<HTML'):
            detected_type = "HTML (trang web/lỗi)"
        elif header.startswith(b'PK'):
            detected_type = "ZIP/PPTX/DOCX"
        elif header.startswith(b'\x89PNG'):
            detected_type = "Hình PNG"
        elif header.startswith(b'\xff\xd8\xff'):
            detected_type = "Hình JPEG"
        else:
            detected_type = "Không xác định"
        
        if not header.startswith(b'%PDF'):
            raise SlidesError(
                f"❌ **File không phải PDF hợp lệ**\n"
                f"📊 Dung lượng: {size_str}\n"
                f"📁 Đuôi file: `{file_ext}`\n"
                f"🔍 Loại thực tế: **{detected_type}**\n\n"
                f"Vui lòng kiểm tra lại link slides."
            )
    
    logger.info(f"Converting PDF to images: {pdf_path}")
    
    # Create output directory
    pdf_name = Path(pdf_path).stem
    images_dir = os.path.join(output_dir, f"slides_{pdf_name}")
    os.makedirs(images_dir, exist_ok=True)
    
    try:
        # Convert PDF to images
        images = convert_from_path(
            pdf_path, 
            dpi=150,
            fmt="jpeg"
        )
        
        if not images:
            raise SlidesError("PDF không có nội dung hoặc bị hỏng.")
        
        image_paths = []
        for i, image in enumerate(images, 1):
            image_path = os.path.join(images_dir, f"page_{i:03d}.jpg")
            image.save(image_path, "JPEG", quality=85)
            image_paths.append(image_path)
        
        logger.info(f"Converted {len(image_paths)} pages to images")
        return image_paths
        
    except (PDFPageCountError, PDFSyntaxError) as e:
        raise SlidesError(f"PDF bị hỏng hoặc không thể đọc: {e}")
    except Exception as e:
        logger.error(f"Failed to convert PDF: {e}")
        raise SlidesError(f"Không thể convert PDF: {e}")


async def pdf_to_images_async(pdf_path: str, output_dir: str = "/tmp") -> list[str]:
    """
    Async wrapper for pdf_to_images - runs in thread pool to avoid blocking event loop.
    
    This prevents Discord heartbeat blocked warnings when processing large PDFs.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, pdf_to_images, pdf_path, output_dir)


def get_page_image(image_paths: list[str], page_num: int) -> str | None:
    """
    Get image path for a specific page number.
    
    Args:
        image_paths: List of image paths from pdf_to_images
        page_num: Page number (1-indexed)
        
    Returns:
        Image path or None if not found
    """
    if not image_paths:
        return None
    
    # Convert to 0-indexed
    idx = page_num - 1
    
    if 0 <= idx < len(image_paths):
        return image_paths[idx]
    
    logger.warning(f"Page {page_num} not found (only {len(image_paths)} pages)")
    return None


def cleanup_slide_images(image_paths: list[str]):
    """
    Clean up slide images and their directory.
    
    Args:
        image_paths: List of image paths to delete
    """
    if not image_paths:
        return
    
    # Delete individual images
    for path in image_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Failed to delete {path}: {e}")
    
    # Try to remove directory if empty
    if image_paths:
        try:
            images_dir = os.path.dirname(image_paths[0])
            if os.path.exists(images_dir) and not os.listdir(images_dir):
                os.rmdir(images_dir)
        except Exception as e:
            logger.warning(f"Failed to remove directory: {e}")


def extract_links_from_pdf(pdf_path: str) -> list[tuple[int, str]]:
    """
    Extract all hyperlinks from a PDF file.
    Filters out quiz/form links (Kahoot, Google Forms, etc.)
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        List of tuples (page_number, url) with 1-indexed page numbers
    """
    import re
    
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not installed. Run: pip install pymupdf")
        return []
    
    if not os.path.exists(pdf_path):
        logger.warning(f"PDF file not found: {pdf_path}")
        return []
    
    # Patterns to exclude (quiz, forms, check-in links)
    exclude_patterns = [
        r'kahoot\.it',
        r'kahoot\.com',
        r'forms\.gle',
        r'docs\.google\.com/forms',
        r'bit\.ly',  # Often used for check-in/quiz
        r'discord\.com',
        r'discord\.gg',
    ]
    exclude_regex = [re.compile(p, re.IGNORECASE) for p in exclude_patterns]
    
    links = []
    seen = set()  # Dedupe
    
    try:
        doc = fitz.open(pdf_path)
        
        for page_num, page in enumerate(doc, 1):
            for link in page.get_links():
                uri = link.get("uri")
                if uri and uri.startswith(("http://", "https://")):
                    # Skip if already seen
                    if uri in seen:
                        continue
                    
                    # Skip if matches exclude pattern
                    if any(regex.search(uri) for regex in exclude_regex):
                        logger.debug(f"Filtered out quiz/form link: {uri}")
                        continue
                    
                    seen.add(uri)
                    links.append((page_num, uri))
        
        doc.close()
        logger.info(f"Extracted {len(links)} links from PDF (after filtering)")
        
    except Exception as e:
        logger.error(f"Failed to extract links from PDF: {e}")
    
    return links


def format_pdf_links_for_prompt(links: list[tuple[int, str]]) -> str:
    """
    Format PDF links for injection into prompt.
    
    Args:
        links: List of (page_number, url) tuples
        
    Returns:
        Formatted string for prompt
    """
    if not links:
        return ""
    
    lines = ["**Links từ slides:**"]
    for page_num, url in links:
        lines.append(f"- Page {page_num}: <{url}>")
    
    return "\n".join(lines)


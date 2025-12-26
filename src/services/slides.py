"""
Slides Service

Convert PDF slides to images for embedding in Discord.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str, output_dir: str = "/tmp") -> list[str]:
    """
    Convert PDF to images (one per page).
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save images
        
    Returns:
        List of image paths
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logger.error("pdf2image not installed. Run: pip install pdf2image")
        return []
    
    logger.info(f"Converting PDF to images: {pdf_path}")
    
    # Create output directory
    pdf_name = Path(pdf_path).stem
    images_dir = os.path.join(output_dir, f"slides_{pdf_name}")
    os.makedirs(images_dir, exist_ok=True)
    
    try:
        # Convert PDF to images
        # Using lower DPI for smaller files (Discord limits)
        images = convert_from_path(
            pdf_path, 
            dpi=150,  # Balance quality vs file size
            fmt="jpeg"
        )
        
        image_paths = []
        for i, image in enumerate(images, 1):
            image_path = os.path.join(images_dir, f"page_{i:03d}.jpg")
            image.save(image_path, "JPEG", quality=85)
            image_paths.append(image_path)
        
        logger.info(f"Converted {len(image_paths)} pages to images")
        return image_paths
        
    except Exception as e:
        logger.error(f"Failed to convert PDF: {e}")
        return []


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

"""
Table Utils Service

Convert Markdown tables to images for Discord display.
Discord doesn't render Markdown tables, so we render them as images.
"""

import logging
import os
import re
import hashlib
import textwrap
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

logger = logging.getLogger(__name__)


def wrap_text(text: str, width: int = 35) -> str:
    """Wrap text to specified character width."""
    return '\n'.join(textwrap.wrap(text, width=width))


def calculate_column_widths(headers: list[str], rows: list[list[str]], wrap_width: int = 35) -> list[float]:
    """Calculate column widths based on content length."""
    n_cols = len(headers)
    col_lengths = []
    
    for col_idx in range(n_cols):
        # Header length
        max_len = len(headers[col_idx])
        # Content length
        for row in rows:
            wrapped = wrap_text(row[col_idx], wrap_width)
            for line in wrapped.split('\n'):
                max_len = max(max_len, len(line))
        col_lengths.append(max_len)
    
    # Normalize to proportions (sum = 1)
    total = sum(col_lengths)
    col_widths = [length / total for length in col_lengths]
    
    return col_widths


def render_table_to_image(
    headers: list[str], 
    rows: list[list[str]], 
    output_path: str,
    wrap_width: int = 35,
    transparent: bool = True
) -> bool:
    """
    Render a table to an image file.
    
    Args:
        headers: List of column headers
        rows: List of rows, each row is a list of cell values
        output_path: Path to save the output image
        wrap_width: Character width for text wrapping
        transparent: Whether to use transparent background
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Wrap text in cells
        wrapped_rows = []
        max_lines_per_row = []
        
        for row in rows:
            wrapped_row = [wrap_text(cell, wrap_width) for cell in row]
            wrapped_rows.append(wrapped_row)
            max_lines = max(cell.count('\n') + 1 for cell in wrapped_row)
            max_lines_per_row.append(max_lines)
        
        # Dynamic figure size
        base_height = 1.5
        row_height_factor = 0.35
        total_height = base_height + sum(lines * row_height_factor for lines in max_lines_per_row)
        fig_width = max(12, len(headers) * 4)
        
        fig, ax = plt.subplots(figsize=(fig_width, total_height))
        ax.axis('off')
        
        # Dynamic column widths
        col_widths = calculate_column_widths(headers, rows, wrap_width)
        
        table = ax.table(
            cellText=wrapped_rows,
            colLabels=headers,
            cellLoc='center',
            loc='center',
            colWidths=col_widths,
        )
        
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        
        # Adjust row heights
        for i, max_lines in enumerate(max_lines_per_row):
            for j in range(len(headers)):
                cell = table[(i + 1, j)]
                cell.set_height(max_lines * 0.08)
        
        for j in range(len(headers)):
            table[(0, j)].set_height(0.08)
        
        # Discord-like dark theme
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor('#4f545c')
            cell.set_linewidth(1.5)
            if row == 0:  # Header
                cell.set_facecolor('#202225')
                cell.set_text_props(color='#ffffff', fontweight='bold', fontsize=8)
            else:
                cell.set_facecolor('#2f3136')
                cell.set_text_props(color='#dcddde', fontsize=8)
        
        if transparent:
            fig.patch.set_alpha(0)
            ax.patch.set_alpha(0)
            plt.savefig(output_path, bbox_inches='tight', dpi=150, transparent=True, pad_inches=0.1)
        else:
            fig.patch.set_facecolor('#2f3136')
            plt.savefig(output_path, bbox_inches='tight', dpi=150, facecolor='#2f3136', pad_inches=0.1)
        
        plt.close()
        logger.info(f"Rendered table to {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to render table: {e}")
        return False


def parse_markdown_table(text: str) -> Optional[tuple[list[str], list[list[str]]]]:
    """
    Parse a Markdown table from text.
    
    Args:
        text: Markdown table text
        
    Returns:
        Tuple of (headers, rows) or None if parsing fails
    """
    lines = text.strip().split('\n')
    if len(lines) < 3:
        return None
    
    # Parse header
    header_line = lines[0].strip()
    if not header_line.startswith('|') or not header_line.endswith('|'):
        return None
    
    headers = [cell.strip() for cell in header_line.strip('|').split('|')]
    
    # Skip separator line (line with ---)
    if not re.match(r'^[\s|:-]+$', lines[1]):
        return None
    
    # Parse rows
    rows = []
    for line in lines[2:]:
        line = line.strip()
        if not line.startswith('|') or not line.endswith('|'):
            continue
        row = [cell.strip() for cell in line.strip('|').split('|')]
        if len(row) == len(headers):
            rows.append(row)
    
    if not rows:
        return None
    
    return headers, rows


def process_markdown_tables(text: str, output_dir: str = "/tmp") -> tuple[str, list[tuple[str, str]]]:
    """
    Process Markdown tables in text:
    - Find tables (lines starting with |...)
    - Render to image
    - Replace with placeholder
    
    Args:
        text: Text containing Markdown tables
        output_dir: Directory to save rendered images
        
    Returns:
        Tuple of (processed_text, [(placeholder, image_path), ...])
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Pattern to match markdown tables
    # Table: starts with |, has separator line with ---, multiple rows
    table_pattern = r'(\|[^\n]+\|\n\|[\s:-]+\|\n(?:\|[^\n]+\|\n?)+)'
    
    images = []
    
    def process_table(match):
        table_text = match.group(1)
        parsed = parse_markdown_table(table_text)
        
        if not parsed:
            return table_text  # Return original if can't parse
        
        headers, rows = parsed
        
        # Generate unique filename
        table_hash = hashlib.md5(table_text.encode()).hexdigest()[:8]
        image_path = os.path.join(output_dir, f"table_{table_hash}.png")
        placeholder = f"[-TABLE_IMG:{table_hash}-]"
        
        if render_table_to_image(headers, rows, image_path):
            images.append((placeholder, image_path))
            return placeholder
        else:
            return table_text  # Return original on failure
    
    processed = re.sub(table_pattern, process_table, text)
    
    return processed, images


def cleanup_table_images(images: list[tuple[str, str]]):
    """
    Clean up rendered table images.
    
    Args:
        images: List of (placeholder, image_path) tuples
    """
    for _, image_path in images:
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
                logger.debug(f"Cleaned up table image: {image_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {image_path}: {e}")

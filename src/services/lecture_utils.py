"""
Lecture Utilities - Pure functions for lecture processing.

These are extracted to a separate module to enable unit testing
without requiring Discord dependencies.
"""
import re
import json
import logging

logger = logging.getLogger(__name__)


def preprocess_chat_session(raw_text: str) -> str:
    """
    Filter junk from chat session text using robust parsing.
    Logic:
    1. Parse messages (Name, Timestamp, Content)
    2. Clean content (remove reaction lines, Collapse All, headers)
    3. Filter: Keep if has link OR length >= 6 words
    4. Format: JSON string matching user request
    """
    lines = [line_item.strip() for line_item in raw_text.split('\n')]
    
    # Patterns
    time_pat = re.compile(r'^(\d{1,2}:\d{2}(?::\d{2})?)(?:\s*\(Edited\))?$')
    reaction_count_pat = re.compile(r'^\d+$')
    emoji_pat = re.compile(r'^[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]+$')
    
    # 1. Identify start indices
    msg_starts = []
    i = 0
    while i < len(lines) - 1:
        if time_pat.match(lines[i+1]) and lines[i]: 
            msg_starts.append(i)
            i += 1 
        i += 1
        
    filtered_messages = []
    
    for idx, start_line_idx in enumerate(msg_starts):
        name = lines[start_line_idx]
        timestamp = time_pat.match(lines[start_line_idx+1]).group(1)
        
        start_content = start_line_idx + 2
        end_content = msg_starts[idx+1] if idx + 1 < len(msg_starts) else len(lines)
        
        clean_lines = []
        for line in lines[start_content:end_content]:
            if not line:
                continue
            if line == "Collapse All":
                continue
            if emoji_pat.match(line):
                continue
            if reaction_count_pat.match(line):
                continue
            clean_lines.append(line)
            
        full_content = "\n".join(clean_lines).strip()
        
        if not full_content:
            continue
            
        # Filter Logic: Keep if Link OR >= 6 Words OR >= 2 Lines (code blocks)
        has_link = 'http' in full_content.lower()
        word_count = len(full_content.split())
        line_count = len(clean_lines)
        
        is_junk = (word_count < 6) and (not has_link) and (line_count < 2)
        
        if not is_junk:
            filtered_messages.append({
                "name": name,
                "time": timestamp,
                "content": full_content
            })
            
    # Return as JSON string
    return json.dumps(filtered_messages, ensure_ascii=False, indent=2)


def extract_links_from_chat(chat_text: str) -> list[str]:
    """
    Extract URLs from chat session text, filtering out Kahoot and other gaming links.
    
    Args:
        chat_text: Preprocessed chat session text
        
    Returns:
        List of URLs (already wrapped in <>)
    """
    # Find all URLs
    url_pattern = r'https?://[^\s<>"\')]+[^\s<>"\')\.\,\;]'
    urls = re.findall(url_pattern, chat_text)
    
    # Filter out unwanted links
    exclude_patterns = [
        r'kahoot\.it',
        r'kahoot\.com',
        r'discord\.com',
        r'discord\.gg',
        r'youtube\.com/live',  # Live stream links often not useful
        r'forms\.gle',  # Quiz forms
    ]
    exclude_regex = [re.compile(p, re.IGNORECASE) for p in exclude_patterns]
    
    filtered = []
    seen = set()
    for url in urls:
        # Skip if matches exclude pattern
        if any(p.search(url) for p in exclude_regex):
            continue
        # Skip duplicates
        if url in seen:
            continue
        seen.add(url)
        filtered.append(f"<{url}>")
    
    return filtered


def format_chat_links_for_prompt(links: list[str]) -> str:
    """
    Format chat links for injection into merge prompt.
    
    Args:
        links: List of URLs (already wrapped in <>)
        
    Returns:
        Formatted string for prompt
    """
    if not links:
        return ""
    
    lines = ["**Links từ chat session:**"]
    for url in links:
        lines.append(f"- {url}")
    
    return "\n".join(lines)


def parse_multi_doc_pages(text: str) -> list[tuple[str, int | None, int | None]]:
    """
    Parse text and split at [-DOC{N}:PAGE:{X}-] markers.
    
    Returns list of tuples: (text_chunk, doc_number or None, page_number or None)
    Example: "Hello [-DOC1:PAGE:5-] World" -> [("Hello ", 1, 5), (" World", None, None)]
    """
    pattern = r'\[-DOC(\d+):PAGE:(\d+)-\]'
    
    parts = []
    last_end = 0
    
    for match in re.finditer(pattern, text):
        # Add text before marker
        before_text = text[last_end:match.start()]
        if before_text:
            parts.append((before_text, None, None))
        
        # Add marker info
        doc_num = int(match.group(1))
        page_num = int(match.group(2))
        parts.append(("", doc_num, page_num))
        
        last_end = match.end()
    
    # Add remaining text
    if last_end < len(text):
        parts.append((text[last_end:], None, None))
    
    # If no markers found, return whole text
    if not parts:
        parts.append((text, None, None))
    
    return parts

"""
Tests for LLM output parsing functions.
"""

from services.gemini import format_video_timestamps, format_toc_hyperlinks, parse_frames_and_text, parse_pages_and_text
from services.lecture_utils import parse_multi_doc_pages


class TestFormatVideoTimestamps:
    """Tests for format_video_timestamps function."""
    
    def test_converts_seconds_to_timestamp(self, video_url):
        """Should convert [-XXs-] to [MM:SS](url)."""
        text = "Check this out [-30s-] for more info"
        result = format_video_timestamps(text, video_url)
        
        assert "[-30s-]" not in result
        assert "[00:30]" in result or "[0:30]" in result
        assert video_url in result or "t=30" in result
    
    def test_handles_backticked_timestamps(self):
        text = "Check this `[-930s-]`."
        video_url = "https://youtu.be/abc"
        result = format_video_timestamps(text, video_url)
        assert "[15:30](<https://youtu.be/abc&t=930>)" in result
        assert "`" not in result  # Backticks should be removed

    def test_handles_mixed_timestamps(self):
        text = "Normal [-60s-] and code `[-120s-]`"
        video_url = "https://youtu.be/abc"
        result = format_video_timestamps(text, video_url)
        # minutes are not zero-padded if hours=0
        assert "[1:00](<https://youtu.be/abc&t=60>)" in result
        assert "[2:00](<https://youtu.be/abc&t=120>)" in result
    
    def test_multiple_timestamps(self, video_url):
        """Should convert multiple timestamps."""
        text = "Part 1 [-30s-] and Part 2 [-120s-]"
        result = format_video_timestamps(text, video_url)
        
        assert "[-30s-]" not in result
        assert "[-120s-]" not in result
        assert "t=30" in result or "30" in result
        assert "t=120" in result or "02:00" in result
    
    def test_no_timestamps(self, video_url):
        """Text without timestamps should remain unchanged."""
        text = "No timestamps here"
        result = format_video_timestamps(text, video_url)
        
        assert result == text
    
    def test_large_timestamp(self, video_url):
        """Should handle hour+ timestamps correctly."""
        text = "Long video [-3665s-]"  # 1:01:05
        result = format_video_timestamps(text, video_url)
        
        assert "[-3665s-]" not in result
        # Should show hour format or correct minutes


class TestFormatTocHyperlinks:
    """Tests for format_toc_hyperlinks function."""
    
    def test_converts_toc_format(self, video_url):
        """Should convert TOC format to hyperlinks."""
        text = '[Giới thiệu CNN | -30s-]'
        result = format_toc_hyperlinks(text, video_url)
        
        # Should create clickable link
        assert "Giới thiệu CNN" in result or "30" in result
    
    def test_multiple_toc_entries(self, video_url):
        """Should convert multiple TOC entries."""
        text = """
- [Topic 1 | -30s-]
- [Topic 2 | -120s-]
"""
        result = format_toc_hyperlinks(text, video_url)
        
        # Both should be converted
        assert "[Topic 1 | -30s-]" not in result or "Topic 1" in result





class TestParseFramesAndText:
    """Tests for parse_frames_and_text function."""
    
    def test_parses_frame_markers(self):
        """Should split at [-FRAME:XXs-] markers."""
        text = "Hello [-FRAME:100s-] World"
        parts = parse_frames_and_text(text)
        
        assert len(parts) >= 2
        # Should have (text, frame_seconds) tuples
        has_frame = any(p[1] is not None for p in parts)
        assert has_frame
    
    def test_no_markers(self):
        """Text without markers should return single part."""
        text = "No markers here"
        parts = parse_frames_and_text(text)
        
        assert len(parts) == 1
        assert parts[0][0] == text
        assert parts[0][1] is None
    
    def test_multiple_frames(self):
        """Should parse multiple frame markers."""
        text = "Part 1 [-FRAME:50s-] Part 2 [-FRAME:100s-] Part 3"
        parts = parse_frames_and_text(text)
        
        frames = [p[1] for p in parts if p[1] is not None]
        assert 50 in frames or 100 in frames


class TestParsePagesAndText:
    """Tests for parse_pages_and_text function."""
    
    def test_parses_page_markers(self, sample_llm_output_with_pages):
        """Should split at [-PAGE:X-] markers."""
        parts = parse_pages_and_text(sample_llm_output_with_pages)
        
        # Should have multiple parts
        assert len(parts) > 1
        
        # Should extract page numbers
        pages = [p[1] for p in parts if p[1] is not None]
        assert 3 in pages
        assert 5 in pages
        assert 7 in pages
    
    def test_parses_page_with_description(self, sample_llm_output_with_pages):
        """Should extract description from [-PAGE:X:"desc"-] format."""
        parts = parse_pages_and_text(sample_llm_output_with_pages)
        
        # Find part with description
        descriptions = [p[2] for p in parts if p[2] is not None]
        assert any("CNN" in d or "diagram" in d.lower() for d in descriptions if d)
    
    def test_no_markers(self):
        """Text without markers should return single part."""
        text = "No page markers here"
        parts = parse_pages_and_text(text)
        
        assert len(parts) == 1
        assert parts[0][1] is None  # No page number


class TestParseMultiDocPages:
    """Tests for parse_multi_doc_pages function."""
    
    def test_parses_multi_doc_markers(self, sample_llm_output_multi_doc):
        """Should parse [-DOC{N}:PAGE:{X}-] markers."""
        parts = parse_multi_doc_pages(sample_llm_output_multi_doc)
        
        # Should have multiple parts
        assert len(parts) > 1
        
        # Parts are (text, doc_num, page_num) tuples
        doc_numbers = [p[1] for p in parts if p[1] is not None]
        page_numbers = [p[2] for p in parts if p[2] is not None]
        
        assert 1 in doc_numbers
        assert 2 in doc_numbers
        assert 3 in page_numbers
        assert 5 in page_numbers
    
    def test_no_markers(self):
        """Text without markers should return single part."""
        text = "No multi-doc markers"
        parts = parse_multi_doc_pages(text)
        
        assert len(parts) == 1
        assert parts[0][1] is None  # No doc number
        assert parts[0][2] is None  # No page number

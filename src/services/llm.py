"""
LLM Service - GLM API Client
Uses OpenAI-compatible client with Z.AI base URL
"""

import asyncio
import logging
import os
from typing import Optional

from openai import OpenAI

from services import config as config_service

logger = logging.getLogger(__name__)


def get_client(guild_id: Optional[int] = None) -> OpenAI:
    """Get configured OpenAI client for GLM API"""
    # Try guild-specific key first, then fallback to env
    if guild_id:
        api_key = config_service.get_api_key(guild_id, "glm")
    else:
        api_key = os.getenv("GLM_API_KEY")

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4/"),
    )


async def summarize_transcript(
    transcript: str,
    guild_id: Optional[int] = None,
    timeout: int = 60,
    retries: int = 3,
) -> Optional[str]:
    """
    Summarize a meeting transcript using GLM API.

    Args:
        transcript: Full transcript text
        guild_id: Guild ID for guild-specific API key
        timeout: Timeout in seconds
        retries: Number of retry attempts

    Returns:
        Summary text or None if failed
    """
    model = os.getenv("GLM_MODEL", "glm-4.6")
    client = get_client(guild_id)

    system_prompt = """Bạn là trợ lý tóm tắt cuộc họp chuyên nghiệp. 
Hãy tóm tắt cuộc họp theo cấu trúc:
## 📋 Tóm tắt tổng quan
(2-3 câu về nội dung chính)
## 🎯 Các điểm chính
- Điểm 1
- Điểm 2
...
## ✅ Quyết định & Action Items
- [Người] - Việc cần làm
## 📌 Ghi chú quan trọng
(Nếu có)
Hãy tóm tắt ngắn gọn, súc tích, bằng tiếng Việt."""

    for attempt in range(retries):
        try:
            logger.info(f"Summarizing transcript (attempt {attempt + 1})...")

            # Run sync client in thread pool
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"Tóm tắt cuộc họp sau:\n\n{transcript[:15000]}",
                        },  # Limit context
                    ],
                    timeout=timeout,
                ),
            )

            summary = completion.choices[0].message.content
            logger.info(f"Summary generated: {len(summary)} chars")
            return summary

        except Exception as e:
            logger.error(f"LLM attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 2**attempt
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    return None


def get_fallback_template() -> str:
    """Return fallback template when LLM fails"""
    return """⚠️ **Lỗi gọi API LLM**"""

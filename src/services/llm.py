"""
LLM Service - GLM API Client
Uses OpenAI-compatible client with Z.AI base URL
GLM is OPTIONAL - only used if GLM_API_KEY is configured
"""

import asyncio
import logging
import os
from typing import Optional

from openai import OpenAI

from services import config as config_service

logger = logging.getLogger(__name__)


def is_glm_available(guild_id: Optional[int] = None) -> bool:
    """Check if GLM API is available (key configured)."""
    if guild_id:
        key = config_service.get_api_key(guild_id, "glm")
        if key:
            return True
    return bool(os.getenv("GLM_API_KEY"))


def get_client(guild_id: Optional[int] = None) -> Optional[OpenAI]:
    """
    Get configured OpenAI client for GLM API.
    Returns None if no API key available.
    """
    # Try guild-specific key first, then fallback to env
    api_key = None
    if guild_id:
        api_key = config_service.get_api_key(guild_id, "glm")
    if not api_key:
        api_key = os.getenv("GLM_API_KEY")
    
    if not api_key:
        return None

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4/"),
    )


async def extract_slide_content(
    image_base64_list: list[str],
    guild_id: Optional[int] = None,
    timeout: int = 120,
    retries: int = 3,
    mode: str = "meeting",
) -> Optional[str]:
    """
    Extract comprehensive content from slides (not just glossary).
    
    With 128k token budget, we can extract FULL slide content including:
    - Definitions, formulas, code blocks
    - Diagrams and visual explanations
    - Examples and use cases
    - All relevant information for context injection

    Args:
        image_base64_list: List of base64 encoded PNG images
        guild_id: Guild ID for guild-specific API key
        timeout: Timeout in seconds
        retries: Number of retry attempts
        mode: "meeting" or "lecture" - determines extraction focus

    Returns:
        Extracted slide content or None if failed
    """
    if not image_base64_list:
        return None
    
    # Check if GLM is available
    client = get_client(guild_id)
    if not client:
        logger.warning("GLM not configured, skipping slide extraction")
        return None
    
    from services import config as config_service
    
    model = os.getenv("GLM_VISION_MODEL", "glm-4.6v-flash")
    
    # Get VLM prompt from config (allows per-guild customization)
    vlm_prompt = config_service.get_prompt(
        guild_id, 
        mode=mode, 
        prompt_type="vlm"
    )

    # Build content with images
    content = []
    for img_b64 in image_base64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    
    # Append prompt at the end
    content.append({"type": "text", "text": vlm_prompt})

    for attempt in range(retries):
        try:
            logger.info(f"Extracting slide content ({mode} mode) from {len(image_base64_list)} pages (attempt {attempt + 1})...")

            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    timeout=timeout,
                    extra_body={"thinking": {"type": "enabled"}},
                ),
            )

            slide_content = completion.choices[0].message.content
            logger.info(f"Slide content extracted ({mode} mode): {len(slide_content)} chars")
            return slide_content

        except Exception as e:
            last_error = str(e)
            logger.error(f"Vision attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 5 * (attempt + 1)  # 5s, 10s, 15s
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    # Return error message instead of None
    return f"⚠️ VLM Error: {last_error[:200]}"


async def summarize_transcript(
    transcript: str,
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
    slide_content: Optional[str] = None,
    timeout: int = 60,
    retries: int = 3,
    mode: str = "meeting",
) -> Optional[str]:
    """
    Summarize transcript with optional slide content context.
    
    Priority: Gemini (if user has API key) -> GLM fallback
    
    Args:
        transcript: Meeting/lecture transcript text
        guild_id: Guild ID for guild-specific config
        user_id: User ID for per-user Gemini API key
        slide_content: Full extracted content from slides (comprehensive extraction)
                      Thanks to 128k token budget, we can include everything relevant
        timeout: Timeout in seconds
        retries: Number of retry attempts
        mode: "meeting" or "lecture" - determines summarization style
    
    Returns:
        Summary text or error message
    """
    from services import config as config_service
    
    # Get summary prompt from config
    system_prompt = config_service.get_prompt(
        guild_id,
        mode=mode,
        prompt_type="summary"
    )
    
    # ========================================
    # TRY GEMINI FIRST (if user has API keys)
    # ========================================
    user_gemini_keys = []
    if user_id:
        user_gemini_keys = config_service.get_user_gemini_apis(user_id)
    
    if user_gemini_keys:
        from services import gemini
        from services.gemini_keys import GeminiKeyPool
        
        pool = GeminiKeyPool(user_id, user_gemini_keys)
        last_error = None
        
        for attempt in range(len(user_gemini_keys)):
            current_key = pool.get_available_key()
            if not current_key:
                break  # All keys exhausted, fall through to GLM
            
            try:
                logger.info(f"Using Gemini for transcript summary (user {user_id}, attempt {attempt + 1})")
                summary = await gemini.summarize_transcript(
                    transcript=transcript,
                    system_prompt=system_prompt,
                    slide_content=slide_content,
                    api_key=current_key,
                    retries=retries,
                )
                pool.increment_count(current_key)
                return summary
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                # Check for rate limit (429)
                if "429" in error_str or "rate" in error_str or "quota" in error_str:
                    pool.mark_rate_limited(current_key)
                    logger.warning(f"Key rate limited, rotating... (attempt {attempt + 1})")
                    continue
                else:
                    logger.warning(f"Gemini failed, falling back to GLM: {e}")
                    break  # Other error, fall through to GLM
        
        if last_error:
            logger.warning(f"All Gemini keys exhausted or failed: {last_error}")
    
    # ========================================
    # FALLBACK TO GLM (only if configured)
    # ========================================
    client = get_client(guild_id)
    if not client:
        # No GLM configured - return error
        if user_gemini_key:
            return "⚠️ Gemini API failed and GLM not configured as fallback"
        else:
            return "⚠️ No API keys configured. Please set Gemini API key or configure GLM."
    
    model = os.getenv("GLM_MODEL", "glm-4.6")
    
    # Inject slide content context if provided
    full_prompt = system_prompt
    if slide_content:
        full_prompt += f"\n\n## Nội dung từ Slides:\n{slide_content}"

    last_error = "Unknown error"
    for attempt in range(retries):
        try:
            logger.info(f"GLM summarizing transcript ({mode} mode) (attempt {attempt + 1})...")

            # Run sync client in thread pool
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": full_prompt},
                        {
                            "role": "user",
                            "content": f"Tóm tắt cuộc họp sau:\n\n{transcript[:15000]}",
                        },  # Limit context
                    ],
                    timeout=timeout,
                    extra_body={"thinking": {"type": "enabled"}},
                ),
            )

            summary = completion.choices[0].message.content
            
            # Check for empty response and retry
            if not summary or not summary.strip():
                logger.warning(f"GLM returned empty summary (attempt {attempt + 1})")
                if attempt < retries - 1:
                    backoff = 5 * (attempt + 1)
                    logger.info(f"Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)
                    continue
                return "⚠️ LLM trả về summary rỗng sau nhiều lần thử"
            
            logger.info(f"GLM summary generated: {len(summary)} chars")
            return summary

        except Exception as e:
            last_error = str(e)
            logger.error(f"GLM attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 5 * (attempt + 1)  # 5s, 10s, 15s
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    # Return error message instead of None
    return f"⚠️ LLM Error: {last_error[:200]}"

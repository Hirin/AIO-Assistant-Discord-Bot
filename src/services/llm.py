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
    pdf_path: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Optional[str]:
    """
    Extract comprehensive content from slides.
    
    Priority:
    1. Gemini (if user has personal keys or global key available) - uses PDF directly
    2. GLM VLM fallback (if Gemini not available) - uses converted images

    Args:
        image_base64_list: List of base64 encoded PNG images (for GLM fallback)
        guild_id: Guild ID for guild-specific API key
        timeout: Timeout in seconds
        retries: Number of retry attempts
        mode: "meeting" or "lecture" - determines extraction focus
        pdf_path: Path to PDF file (for Gemini direct upload)
        user_id: User ID for personal Gemini keys

    Returns:
        Extracted slide content or error message if failed
    """
    from services.gemini_keys import GeminiKeyPool
    
    vlm_prompt = config_service.get_prompt(guild_id, mode=mode, prompt_type="vlm")
    
    # === Try Gemini first (priority) ===
    user_gemini_keys = []
    if user_id:
        user_gemini_keys = config_service.get_user_gemini_apis(user_id) or []
    
    # Also check for global Gemini key
    global_gemini_key = config_service.get_guild_gemini_api(guild_id) if guild_id else None
    
    has_gemini = bool(user_gemini_keys) or bool(global_gemini_key)
    
    if has_gemini and pdf_path:
        logger.info(f"Trying Gemini for slide extraction ({mode} mode)...")
        
        # Build key pool
        if user_gemini_keys:
            gemini_key_pool = GeminiKeyPool(user_id, user_gemini_keys)
        else:
            # For global key, use guild_id as pseudo-user
            gemini_key_pool = GeminiKeyPool(guild_id or 0, [global_gemini_key]) if global_gemini_key else None
        
        if gemini_key_pool:
            max_key_retries = len(user_gemini_keys) if user_gemini_keys else 1
            
            for key_attempt in range(max_key_retries):
                current_key = gemini_key_pool.get_available_key()
                if not current_key:
                    break
                
                try:
                    from services import gemini
                    from google.genai import types
                    
                    client = gemini.get_client(current_key)
                    
                    def _upload_and_extract():
                        uploaded = None
                        try:
                            uploaded = client.files.upload(file=pdf_path)
                            logger.info(f"Uploaded PDF to Gemini: {uploaded.name}")
                            
                            import time
                            start = time.time()
                            response = client.models.generate_content(
                                model="gemini-3-flash-preview",
                                contents=[uploaded, vlm_prompt],
                                config=types.GenerateContentConfig(
                                    thinking_config=types.ThinkingConfig(thinking_level="medium")
                                ),
                            )
                            logger.info(f"Gemini extracted in {time.time()-start:.1f}s")
                            return response.text
                        finally:
                            if uploaded:
                                try:
                                    client.files.delete(name=uploaded.name)
                                except Exception:
                                    pass
                    
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, _upload_and_extract)
                    
                    if gemini_key_pool:
                        gemini_key_pool.increment_count(current_key)
                    
                    logger.info(f"Gemini slide extraction success ({mode} mode): {len(result)} chars")
                    return result
                    
                except Exception as e:
                    error_str = str(e).lower()
                    logger.warning(f"Gemini extraction failed (key attempt {key_attempt + 1}): {e}")
                    
                    if "429" in error_str or "rate" in error_str or "quota" in error_str:
                        if gemini_key_pool:
                            gemini_key_pool.mark_rate_limited(current_key)
                        continue  # Try next key
                    else:
                        break  # Non-rate-limit error, try GLM
    
    # === Fallback to GLM VLM ===
    if not image_base64_list:
        return "⚠️ No slides to extract (no images and Gemini unavailable)"
    
    client = get_client(guild_id)
    if not client:
        return "⚠️ VLM Error: No API keys configured (Gemini or GLM)"
    
    model = os.getenv("GLM_VISION_MODEL", "glm-4.6v-flash")
    logger.info(f"Falling back to GLM VLM for slide extraction ({mode} mode)...")
    
    # Build content with images
    content = []
    for img_b64 in image_base64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    content.append({"type": "text", "text": vlm_prompt})

    last_error = ""
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
            logger.info(f"GLM slide content extracted ({mode} mode): {len(slide_content)} chars")
            return slide_content

        except Exception as e:
            last_error = str(e)
            logger.error(f"GLM Vision attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                backoff = 5 * (attempt + 1)
                logger.info(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)

    return f"⚠️ VLM Error: {last_error[:200]}"


async def summarize_transcript(
    transcript: str,
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
    slide_content: Optional[str] = None,
    glossary: Optional[str] = None,
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
        glossary: Optional glossary/terminology context for domain-specific terms
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
    
    # Append glossary context if provided
    if glossary:
        system_prompt += f"\n\n## Thuật ngữ chuyên ngành (Glossary):\n{glossary}"
    
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
        if user_gemini_keys:
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

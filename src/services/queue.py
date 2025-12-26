"""
Video Processing Queue Service
Limits concurrent video processing to prevent RAM exhaustion
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Global semaphore - only 1 video processing at a time
_video_semaphore = asyncio.Semaphore(1)
_queue_position = 0
_current_position = 0


async def acquire_video_slot() -> int:
    """
    Acquire slot for video processing.
    Blocks if another video is being processed.
    Returns the queue position for logging.
    """
    global _queue_position, _current_position
    _queue_position += 1
    my_position = _queue_position
    
    if _video_semaphore.locked():
        wait_count = my_position - _current_position
        logger.info(f"Video processing queued at position {wait_count}")
    
    await _video_semaphore.acquire()
    _current_position = my_position
    logger.info(f"Video processing slot acquired (position {my_position})")
    return my_position


def release_video_slot():
    """Release video processing slot"""
    _video_semaphore.release()
    logger.info("Video processing slot released")


def get_queue_length() -> int:
    """Get number of waiting requests (not including current)"""
    if not _video_semaphore.locked():
        return 0
    return _queue_position - _current_position


def is_slot_available() -> bool:
    """Check if video processing slot is available"""
    return not _video_semaphore.locked()

"""
Discord Logger Service
Send logs to dedicated Discord channels for tracking and analytics.
"""
import discord
import logging
import os
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Log server and channels
LOG_SERVER_ID = 1452341542420484127
CHANNEL_LOGS = 1455727346232332458      # API usage, rate limits (junk)
CHANNEL_FEEDBACKS = 1455728430166446263  # User feedback only
CHANNEL_PROCESS = 1455729178178486442    # Process logs with attachments


async def _get_channel(bot, channel_id: int) -> Optional[discord.TextChannel]:
    """Get channel by ID, return None if not found."""
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        return channel
    except Exception as e:
        logger.warning(f"Failed to get log channel {channel_id}: {e}")
        return None


def _format_names(
    guild: Optional[discord.Guild], 
    user: Optional[Union[discord.User, discord.Member]]
) -> tuple[str, str]:
    """Format server name and user name for logs."""
    server_name = guild.name if guild else "DM"
    user_name = user.display_name if user else "Unknown"
    return server_name, user_name


async def log_api_usage(
    bot,
    guild: Optional[discord.Guild],
    user: Optional[Union[discord.User, discord.Member]],
    key_index: int,
    feature: str,
    success: bool,
):
    """
    Log API usage to #logs channel.
    
    Args:
        bot: Discord bot instance
        guild: Guild where request was made
        user: User who made request
        key_index: Which API key was used (1-indexed)
        feature: Feature name (lecture, preview, meeting)
        success: Whether request was successful
    """
    channel = await _get_channel(bot, CHANNEL_LOGS)
    if not channel:
        return
    
    server_name, user_name = _format_names(guild, user)
    status = "✅" if success else "❌"
    
    try:
        await channel.send(
            f"🔑 API | Server: **{server_name}** | User: **{user_name}** | "
            f"Feature: {feature} | Key #{key_index} | {status}"
        )
    except Exception as e:
        logger.warning(f"Failed to send API usage log: {e}")


async def log_rate_limit(
    bot,
    guild: Optional[discord.Guild],
    user: Optional[Union[discord.User, discord.Member]],
    from_key: int,
    to_key: int,
):
    """
    Log rate limit event to #logs channel.
    
    Args:
        bot: Discord bot instance
        guild: Guild where request was made
        user: User who made request
        from_key: Key that hit rate limit (1-indexed)
        to_key: Key switching to (1-indexed), 0 if no more keys
    """
    channel = await _get_channel(bot, CHANNEL_LOGS)
    if not channel:
        return
    
    server_name, user_name = _format_names(guild, user)
    
    if to_key > 0:
        msg = f"⚠️ Rate Limit | Server: **{server_name}** | User: **{user_name}** | Key #{from_key} → #{to_key}"
    else:
        msg = f"🚫 Rate Limit | Server: **{server_name}** | User: **{user_name}** | Key #{from_key} → ❌ No more keys"
    
    try:
        await channel.send(msg)
    except Exception as e:
        logger.warning(f"Failed to send rate limit log: {e}")


async def log_feedback(
    bot,
    guild: Optional[discord.Guild],
    user: Optional[Union[discord.User, discord.Member]],
    feature: str,
    satisfied: bool,
    reason: Optional[str] = None,
):
    """
    Log user feedback to #feedbacks channel.
    
    Args:
        bot: Discord bot instance
        guild: Guild where feedback was given
        user: User who gave feedback
        feature: Feature name (lecture, preview, meeting)
        satisfied: Whether user was satisfied
        reason: Optional reason (usually for unsatisfied)
    """
    channel = await _get_channel(bot, CHANNEL_FEEDBACKS)
    if not channel:
        return
    
    server_name, user_name = _format_names(guild, user)
    status = "✅ Hài lòng" if satisfied else "❌ Không hài lòng"
    
    msg = f"📊 Feedback | Server: **{server_name}** | User: **{user_name}** | {feature} | {status}"
    if reason:
        msg += f'\n> "{reason}"'
    
    try:
        await channel.send(msg)
    except Exception as e:
        logger.warning(f"Failed to send feedback log: {e}")


async def log_process(
    bot,
    guild: Optional[discord.Guild],
    user: Optional[Union[discord.User, discord.Member]],
    process: str,
    status: str,
    success: bool,
    video_url: Optional[str] = None,
    attachment_path: Optional[str] = None,
    attachment_url: Optional[str] = None,
):
    """
    Log process result to #process channel with optional attachment.
    
    Args:
        bot: Discord bot instance
        guild: Guild where process ran
        user: User who started process
        process: Process name (Preview Slides, Lecture Summary, etc.)
        status: Status message (Success or error reason)
        success: Whether process was successful
        video_url: Optional video URL for lecture
        attachment_path: Optional local file path to upload
        attachment_url: Optional URL for large files (>30MB)
    """
    channel = await _get_channel(bot, CHANNEL_PROCESS)
    if not channel:
        return
    
    server_name, user_name = _format_names(guild, user)
    
    # Build message
    emoji = "🎥" if "Lecture" in process else "📄"
    status_emoji = "✅" if success else "❌"
    
    lines = [
        f"{emoji} **{process}** | Server: **{server_name}** | User: **{user_name}**"
    ]
    
    if video_url:
        lines.append(f"🔗 Video: <{video_url}>")
    
    # Handle attachment
    file = None
    if attachment_path and os.path.exists(attachment_path):
        file_size = os.path.getsize(attachment_path)
        file_size_mb = file_size / (1024 * 1024)
        
        if file_size_mb <= 10:
            # Upload directly
            try:
                file = discord.File(attachment_path)
                lines.append("📎 Attachment: (file đính kèm)")
            except Exception as e:
                lines.append(f"📎 Attachment: ❌ Failed to load ({e})")
        elif file_size_mb <= 30:
            # Split would be needed - just note for now
            lines.append(f"📎 Attachment: {os.path.basename(attachment_path)} ({file_size_mb:.1f}MB - cần split)")
        else:
            # Too large
            lines.append(f"📎 Attachment: {os.path.basename(attachment_path)} ({file_size_mb:.1f}MB - quá lớn)")
    elif attachment_url:
        lines.append(f"📎 Attachment: <{attachment_url}>")
    
    lines.append(f"Status: {status_emoji} {status}")
    
    try:
        await channel.send("\n".join(lines), file=file)
    except Exception as e:
        logger.warning(f"Failed to send process log: {e}")

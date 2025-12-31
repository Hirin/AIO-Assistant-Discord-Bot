"""
Shared FeedbackView - Collect user satisfaction after LLM output.
Used by both /lecture and /meeting commands.
"""

import asyncio
import logging
import discord

logger = logging.getLogger(__name__)


class FeedbackView(discord.ui.View):
    """View for user to rate/delete the generated summary."""
    
    def __init__(
        self, 
        message_ids: list[int], 
        user_id: int, 
        title: str = "",
        feature: str = "unknown"  # "lecture", "meeting", "preview"
    ):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.message_ids = message_ids
        self.user_id = user_id
        self.title = title
        self.feature = feature

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Chỉ người yêu cầu mới được thao tác!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Hài lòng (Giữ kết quả)", style=discord.ButtonStyle.green, emoji="✅")
    async def satisfied(self, interaction: discord.Interaction, button: discord.ui.Button):
        from services import feedback_log
        
        # Log satisfied feedback
        feedback_log.log_feedback(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            feature=self.feature,
            title=self.title,
            satisfied=True,
            reason=None
        )
        logger.info(f"FEEDBACK_SATISFIED: feature={self.feature} user={interaction.user.id}")
        
        # Delete the feedback message to keep channel clean
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except Exception:
            pass
        self.stop()

    @discord.ui.button(label="Xóa kết quả", style=discord.ButtonStyle.red, emoji="🗑️")
    async def delete_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show review modal to collect feedback reason
        modal = FeedbackReviewModal(
            message_ids=self.message_ids,
            title=self.title,
            feature=self.feature,
            feedback_message=interaction.message
        )
        await interaction.response.send_modal(modal)
        self.stop()


class FeedbackReviewModal(discord.ui.Modal, title="Lý do xóa kết quả"):
    """Modal to collect reason for deleting summary."""
    
    reason = discord.ui.TextInput(
        label="Tại sao bạn không hài lòng?",
        placeholder="VD: Tóm tắt thiếu nội dung, sai thông tin, format khó đọc...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=5,
        max_length=500,
    )
    
    def __init__(
        self, 
        message_ids: list[int], 
        title: str, 
        feature: str,
        feedback_message: discord.Message
    ):
        super().__init__()
        self.message_ids = message_ids
        self.content_title = title
        self.feature = feature
        self.feedback_message = feedback_message
    
    async def on_submit(self, interaction: discord.Interaction):
        from services import feedback_log
        
        reason_text = self.reason.value.strip()
        
        # Log unsatisfied feedback with reason
        feedback_log.log_feedback(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            feature=self.feature,
            title=self.content_title,
            satisfied=False,
            reason=reason_text
        )
        logger.info(f"FEEDBACK_DELETE: feature={self.feature} user={interaction.user.id} reason={reason_text[:50]}...")
        
        # Acknowledge and delete
        await interaction.response.defer()
        
        # Delete summary messages
        channel = interaction.channel
        target_ids = set(self.message_ids)
        
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                deleted = await channel.purge(
                    limit=100, 
                    check=lambda m: m.id in target_ids,
                    bulk=True
                )
                logger.info(f"Bulk deleted {len(deleted)} messages via purge")
            except Exception as e:
                logger.warning(f"Purge failed, falling back to concurrent delete: {e}")
                tasks = [channel.get_partial_message(mid).delete() for mid in self.message_ids]
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            tasks = [channel.get_partial_message(mid).delete() for mid in self.message_ids]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Delete the feedback message
        try:
            await self.feedback_message.delete()
        except Exception:
            pass

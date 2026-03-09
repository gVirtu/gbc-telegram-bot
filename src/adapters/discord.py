"""Discord platform adapter.

Implements BotAdapter for Discord using discord.py.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from src.adapters.base import BotAdapter
from src.i18n import translation_manager
from src.models.game_state import BUTTON_LAYOUT, GameButton

if TYPE_CHECKING:
    from src.models.game_state import ChatConfig, ModifierButtonSpec

logger = logging.getLogger(__name__)

# Lazy import to avoid forcing discord.py at import time
def _discord():
    import discord
    return discord


class DiscordGameView:
    """discord.ui.View subclass for game input keyboard."""

    @staticmethod
    def build(
        chat_config: Optional["ChatConfig"] = None,
        modifier_specs: Optional[list["ModifierButtonSpec"]] = None,
    ) -> Any:
        """Build a discord.ui.View with game input buttons."""
        import discord

        chat_id = chat_config.chat_id if chat_config else 0
        modifier_states = chat_config.modifier_states if chat_config else {}

        view = discord.ui.View(timeout=None)

        for row_idx, row in enumerate(BUTTON_LAYOUT):
            for button in row:
                btn = discord.ui.Button(
                    label=button.emoji_alt,
                    custom_id=button.value,
                    row=row_idx,
                    style=discord.ButtonStyle.secondary,
                )
                view.add_item(btn)

        if modifier_specs:
            mod_row = len(BUTTON_LAYOUT)
            for spec in modifier_specs:
                is_active = modifier_states.get(spec.key, False)
                label_key = spec.active_label_key if is_active else spec.inactive_label_key
                label = translation_manager.get(label_key, chat_id)
                style = discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary
                btn = discord.ui.Button(
                    label=label,
                    custom_id=f"modifier_{spec.key}",
                    row=mod_row,
                    style=style,
                )
                view.add_item(btn)

        return view

    @staticmethod
    def build_save_slots(chat_id: int, save_slots: int) -> Any:
        """Build a discord.ui.View with save slot buttons."""
        import discord

        view = discord.ui.View(timeout=60)

        row = 0
        count = 0
        for slot in range(save_slots):
            btn = discord.ui.Button(
                label=f"Slot {slot}",
                custom_id=f"load_slot_{slot}",
                row=row,
                style=discord.ButtonStyle.primary,
            )
            view.add_item(btn)
            count += 1
            if count % 3 == 0:
                row += 1

        cancel_btn = discord.ui.Button(
            label="❌ Cancel",
            custom_id="cancel_load",
            row=row + 1,
            style=discord.ButtonStyle.danger,
        )
        view.add_item(cancel_btn)

        return view


class DiscordAdapter(BotAdapter):
    """BotAdapter implementation for Discord using discord.py."""

    def __init__(self, bot: Any):
        """Initialize with a discord.py Bot instance.

        Args:
            bot: discord.ext.commands.Bot instance
        """
        self._bot = bot

    @property
    def platform(self) -> str:
        return "discord"

    @property
    def preferred_animation_format(self) -> str:
        return "avif"

    def _get_channel(self, chat_id: int) -> Optional[Any]:
        """Get a Discord channel by ID."""
        channel = self._bot.get_channel(chat_id)
        if channel is None:
            logger.warning(f"Channel {chat_id} not found in bot cache")
        return channel

    async def send_game_message(
        self,
        chat_id: int,
        text: str,
        keyboard: Any,
        image_bytes: Any,
    ) -> int:
        channel = self._get_channel(chat_id)
        if channel is None:
            raise ValueError(f"Discord channel {chat_id} not found")

        import discord

        if hasattr(image_bytes, "read"):
            image_bytes.seek(0)
            file = discord.File(image_bytes, filename="frame.png")
        else:
            file = discord.File(io.BytesIO(image_bytes), filename="frame.png")

        msg = await channel.send(content=text, file=file, view=keyboard)
        return msg.id

    async def edit_game_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: Any,
        media_bytes: Any,
        media_type: str = "photo",
    ) -> Optional[str]:
        channel = self._get_channel(chat_id)
        if channel is None:
            return None

        import discord

        try:
            message = await channel.fetch_message(message_id)
        except Exception as e:
            logger.warning(f"Failed to fetch Discord message {message_id}: {e}")
            return None

        if hasattr(media_bytes, "read"):
            media_bytes.seek(0)
            data = media_bytes.read()
        else:
            data = media_bytes

        if media_type == "animation":
            ext = "mp4"
        elif media_type == "avif":
            ext = "avif"
        else:
            ext = "png"
        filename = f"frame.{ext}"
        file = discord.File(io.BytesIO(data), filename=filename)

        try:
            await message.edit(content=text, attachments=[file], view=keyboard)
        except Exception as e:
            logger.warning(f"Failed to edit Discord message {message_id}: {e}")

        # Discord does not provide file_id caching like Telegram
        return None

    async def edit_game_keyboard(
        self,
        chat_id: int,
        message_id: int,
        keyboard: Any,
    ) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(message_id)
            if keyboard is None:
                import discord
                await message.edit(view=discord.ui.View())
            else:
                await message.edit(view=keyboard)
        except Exception as e:
            logger.warning(f"Failed to edit Discord keyboard for message {message_id}: {e}")

    async def send_screenshot(
        self,
        chat_id: int,
        image_bytes: Any,
        caption: str = "",
    ) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            return

        import discord

        if hasattr(image_bytes, "read"):
            image_bytes.seek(0)
            file = discord.File(image_bytes, filename="screenshot.png")
        else:
            file = discord.File(io.BytesIO(image_bytes), filename="screenshot.png")

        await channel.send(content=caption or None, file=file)

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_to: Optional[int] = None,
        parse_mode: Optional[str] = None,
    ) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            return

        await channel.send(content=text)

    async def send_video(
        self,
        chat_id: int,
        video: Any,
        caption: str = "",
    ) -> Optional[str]:
        channel = self._get_channel(chat_id)
        if channel is None:
            return None

        import discord

        if isinstance(video, str):
            # file_id string from Telegram - Discord doesn't support this
            # Re-upload is needed (handled by caller)
            logger.error("Discord does not support file_id caching, caller should provide bytes")
            return None

        if hasattr(video, "read"):
            file = discord.File(video, filename="video.mp4")
        else:
            file = discord.File(io.BytesIO(video), filename="video.mp4")

        await channel.send(content=caption or None, file=file)
        # Discord does not provide file_id for caching
        return None

    async def send_animation(
        self,
        chat_id: int,
        animation: Any,
        caption: str = "",
    ) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            return

        import discord

        if isinstance(animation, str):
            # file_id string - Discord cannot use Telegram file_ids
            logger.error("Discord cannot re-send file_ids, skipping animation")
            return

        if hasattr(animation, "read"):
            file = discord.File(animation, filename="animation.mp4")
        else:
            file = discord.File(io.BytesIO(animation), filename="animation.mp4")

        await channel.send(content=caption or None, file=file)

    async def delete_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except Exception as e:
            logger.error(f"Failed to delete Discord message {message_id}: {e}")

    def build_game_keyboard(
        self,
        chat_config: Optional["ChatConfig"],
        modifier_specs: Optional[list["ModifierButtonSpec"]] = None,
    ) -> Any:
        return DiscordGameView.build(chat_config=chat_config, modifier_specs=modifier_specs)

    def build_save_slot_keyboard(
        self,
        chat_id: int,
        save_slots: int,
    ) -> Any:
        return DiscordGameView.build_save_slots(chat_id=chat_id, save_slots=save_slots)

    async def is_admin(
        self,
        chat_id: int,
        user_id: int,
        raw: Any = None,
    ) -> bool:
        """Check admin status via guild permissions.

        For Discord, admin means: Administrator or Manage Guild permission.
        No API call needed - uses cached member permissions.
        """
        import discord

        # Try to get permissions from the interaction or message
        if raw is not None and isinstance(raw, discord.Interaction):
            member = raw.user
            if isinstance(member, discord.Member):
                return (
                    member.guild_permissions.administrator
                    or member.guild_permissions.manage_guild
                )
            # DM interaction: always allow
            return True

        # Fallback: try to fetch from guild
        channel = self._get_channel(chat_id)
        if channel is None:
            return False

        guild = getattr(channel, "guild", None)
        if guild is None:
            # DM channel: always allow
            return True

        try:
            member = guild.get_member(user_id)
            if member is None:
                member = await guild.fetch_member(user_id)
            return (
                member.guild_permissions.administrator
                or member.guild_permissions.manage_guild
            )
        except Exception as e:
            logger.error(f"Failed to check Discord admin for user {user_id}: {e}")
            return False

    async def update_chat_photo(self, chat_id: int, image_bytes: bytes) -> None:
        channel = self._get_channel(chat_id)
        if channel is None:
            raise ValueError(f"Discord channel {chat_id} not found")
        guild = getattr(channel, "guild", None)
        if guild is None:
            raise ValueError(f"Channel {chat_id} is not a guild channel")
        await guild.edit(icon=image_bytes)

    async def answer_interaction(
        self,
        raw: Any,
        text: str = "",
    ) -> None:
        """Acknowledge a Discord interaction."""
        import discord

        if raw is None:
            return

        if isinstance(raw, discord.Interaction):
            try:
                if not raw.response.is_done():
                    await raw.response.send_message(text, ephemeral=True, delete_after=3) if text else await raw.response.defer(ephemeral=True)
                elif text:
                    await raw.followup.send(text, ephemeral=True)
            except Exception as e:
                logger.warning(f"Failed to answer Discord interaction: {e}")

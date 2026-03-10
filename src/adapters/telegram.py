"""Telegram platform adapter.

Wraps the existing telegram_client.py and keyboard.py to implement
the BotAdapter interface for Telegram.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from io import BytesIO

from telegram import Bot, InputFile, InputMediaAnimation, InputMediaPhoto
from telegram.error import TelegramError

from src.adapters.base import BotAdapter
from src.i18n import translation_manager
from src.keyboard import (
    create_input_keyboard,
    create_save_slot_keyboard,
)

if TYPE_CHECKING:
    from src.models.game_state import ChatConfig, ModifierButtonSpec

logger = logging.getLogger(__name__)

# Admin cache: (chat_id, user_id) -> (is_admin: bool, timestamp: float)
_admin_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_CACHE_TTL = 30  # seconds


class TelegramAdapter(BotAdapter):
    """BotAdapter implementation for Telegram using python-telegram-bot."""

    def __init__(self, bot: Bot):
        self._bot = bot

    @property
    def platform(self) -> str:
        return "telegram"

    async def send_game_message(
        self,
        chat_id: int,
        text: str,
        keyboard: Any,
        image_bytes: Any,
    ) -> int:
        message = await self._bot.send_photo(
            chat_id=chat_id,
            photo=image_bytes,
            caption=text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return message.message_id

    async def edit_game_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: Any,
        media_bytes: Any,
        media_type: str = "photo",
    ) -> Optional[str]:
        file_id = None
        try:
            if media_type == "animation":
                media_bytes.name = f"animation_{int(time.time())}.mp4"
                media = InputMediaAnimation(
                    media=media_bytes,
                    caption=text,
                    parse_mode="Markdown",
                )
            else:
                media = InputMediaPhoto(
                    media=media_bytes,
                    caption=text,
                    parse_mode="Markdown",
                )

            message = await self._bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=keyboard,
            )

            if media_type == "animation" and message and message.animation:
                file_id = message.animation.file_id
        except TelegramError as e:
            logger.warning(f"Failed to edit media for chat {chat_id}: {e}")
        return file_id

    async def edit_game_keyboard(
        self,
        chat_id: int,
        message_id: int,
        keyboard: Any,
    ) -> None:
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
        except TelegramError as e:
            logger.warning(f"Failed to edit keyboard for chat {chat_id}: {e}")

    async def send_screenshot(
        self,
        chat_id: int,
        image_bytes: Any,
        caption: str = "",
    ) -> None:
        await self._bot.send_photo(
            chat_id=chat_id,
            photo=image_bytes,
            caption=caption,
        )

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_to: Optional[int] = None,
        parse_mode: Optional[str] = None,
    ) -> None:
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        await self._bot.send_message(**kwargs)

    async def send_video(
        self,
        chat_id: int,
        video: Any,
        caption: str = "",
    ) -> Optional[str]:
        message = await self._bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
        )
        if message.video:
            return message.video.file_id
        return None

    async def send_animation(
        self,
        chat_id: int,
        animation: Any,
        caption: str = "",
    ) -> None:
        await self._bot.send_animation(
            chat_id=chat_id,
            animation=animation,
            filename="animation.mp4",
            caption=caption,
        )

    async def delete_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> None:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramError as e:
            logger.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

    def build_game_keyboard(
        self,
        chat_config: Optional["ChatConfig"],
        modifier_specs: Optional[list["ModifierButtonSpec"]] = None,
    ) -> Any:
        return create_input_keyboard(
            chat_config=chat_config,
            modifier_specs=modifier_specs,
        )

    def build_save_slot_keyboard(
        self,
        chat_id: int,
        save_slots: int,
    ) -> Any:
        return create_save_slot_keyboard(chat_id=chat_id, save_slots=save_slots)

    async def is_admin(
        self,
        chat_id: int,
        user_id: int,
        raw: Any = None,
    ) -> bool:
        # Private chats: always allow
        from telegram import Update
        if raw is not None and isinstance(raw, Update):
            if raw.effective_chat and raw.effective_chat.type == "private":
                return True
            if raw.effective_chat and raw.effective_chat.type not in ("group", "supergroup"):
                # Channel or unknown type: deny
                return False

        # Check cache
        key = (chat_id, user_id)
        if key in _admin_cache:
            cached_result, timestamp = _admin_cache[key]
            if time.time() - timestamp < _CACHE_TTL:
                return cached_result
            else:
                del _admin_cache[key]

        try:
            chat_member = await self._bot.get_chat_member(chat_id, user_id)
            is_admin_result = chat_member.status in ("creator", "administrator")
            _admin_cache[key] = (is_admin_result, time.time())
            return is_admin_result
        except Exception as e:
            logger.warning(f"Failed to check admin status for user {user_id} in chat {chat_id}: {e}")
            return False

    async def update_chat_photo(self, chat_id: int, image_bytes: bytes) -> None:
        sentinel_text = translation_manager.get("game.avatar_updating", chat_id)
        sentinel = await self._bot.send_message(
            chat_id=chat_id,
            text=sentinel_text,
            disable_notification=True,
        )
        reference_message_id = sentinel.message_id

        await self._bot.set_chat_photo(chat_id, photo=InputFile(BytesIO(image_bytes)))

        for msg_id in (reference_message_id, reference_message_id + 1):
            try:
                await self._bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except TelegramError as e:
                logger.warning(
                    f"Failed to delete message {msg_id} in chat {chat_id} "
                    f"after photo update: {e}"
                )

    async def answer_interaction(
        self,
        raw: Any,
        text: str = "",
    ) -> None:
        if raw is not None and hasattr(raw, "answer"):
            try:
                await raw.answer(text)
            except Exception as e:
                logger.warning(f"Failed to answer interaction: {e}")

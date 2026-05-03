"""Base adapter abstraction for multi-platform bot support.

Defines the BotAdapter ABC and CommandContext dataclass that allow
platform-agnostic business logic to interact with Telegram or Discord.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.game_state import ChatConfig, ModifierButtonSpec

logger = logging.getLogger(__name__)


@dataclass
class CommandContext:
    """Platform-agnostic context for command handlers.

    Attributes:
        chat_id: Platform chat/channel ID
        user_id: Platform user ID
        user_name: Display name of the user
        args: Command arguments as a list of strings
        adapter: The platform adapter to use for sending messages
        raw: Platform-specific event (Update for Telegram, Interaction for Discord)
    """

    chat_id: int
    user_id: int
    user_name: str
    args: list[str]
    adapter: "BotAdapter"
    raw: Any = None


class BotAdapter(ABC):
    """Abstract base class for platform-specific bot adapters.

    Implement this for each supported platform (Telegram, Discord).
    All methods are async to support both HTTP-based and gateway-based platforms.
    """

    # --- Message operations ---

    @abstractmethod
    async def send_game_message(
        self,
        chat_id: int,
        text: str,
        keyboard: Any,
        image_bytes: Any,
    ) -> int:
        """Send the initial game message with image and keyboard.

        Args:
            chat_id: Platform chat ID
            text: Caption/message text
            keyboard: Platform-specific keyboard object
            image_bytes: BytesIO or bytes containing PNG image

        Returns:
            Platform-specific message ID
        """
        ...

    @abstractmethod
    async def edit_game_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: Any,
        media_bytes: Any,
        media_type: str = "photo",
    ) -> Optional[str]:
        """Edit an existing game message with new media.

        Args:
            chat_id: Platform chat ID
            message_id: ID of the message to edit
            text: New caption/message text
            keyboard: Platform-specific keyboard object
            media_bytes: BytesIO containing image or animation data
            media_type: "photo" / "mp4" / "avif"

        Returns:
            file_id string if available (Telegram caching), None otherwise
        """
        ...

    @abstractmethod
    async def edit_game_keyboard(
        self,
        chat_id: int,
        message_id: int,
        keyboard: Any,
    ) -> None:
        """Edit only the keyboard of an existing message.

        Args:
            chat_id: Platform chat ID
            message_id: ID of the message to edit
            keyboard: New platform-specific keyboard object (None to remove)
        """
        ...

    @abstractmethod
    async def send_screenshot(
        self,
        chat_id: int,
        image_bytes: Any,
        caption: str = "",
    ) -> None:
        """Send a standalone screenshot without keyboard.

        Args:
            chat_id: Platform chat ID
            image_bytes: BytesIO or bytes containing PNG image
            caption: Optional caption text
        """
        ...

    @abstractmethod
    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_to: Optional[int] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Any] = None,
    ) -> None:
        """Send a plain text message.

        Args:
            chat_id: Platform chat ID
            text: Message text
            reply_to: Optional message ID to reply to
            parse_mode: Optional parse mode ("Markdown", "HTML", etc.)
            reply_markup: Optional inline keyboard markup
        """
        ...

    @abstractmethod
    async def send_video(
        self,
        chat_id: int,
        video: Any,
        caption: str = "",
    ) -> Optional[str]:
        """Send a video file.

        Args:
            chat_id: Platform chat ID
            video: file_id string or BytesIO/file object
            caption: Optional caption text

        Returns:
            file_id string if available for caching, None otherwise
        """
        ...

    @abstractmethod
    async def send_animation(
        self,
        chat_id: int,
        animation: Any,
        caption: str = "",
    ) -> None:
        """Send an animation/GIF.

        Args:
            chat_id: Platform chat ID
            animation: file_id string or BytesIO
            caption: Optional caption text
        """
        ...

    @abstractmethod
    async def delete_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Delete a message.

        Args:
            chat_id: Platform chat ID
            message_id: ID of message to delete
        """
        ...

    # --- Keyboard builders ---

    @abstractmethod
    async def build_game_keyboard(
        self,
        chat_config: Optional["ChatConfig"],
        modifier_specs: Optional[list["ModifierButtonSpec"]] = None,
    ) -> Any:
        """Build the game input keyboard.

        Args:
            chat_config: Chat configuration (for modifier states)
            modifier_specs: Game-specific modifier button specs

        Returns:
            Platform-specific keyboard object
        """
        ...

    @abstractmethod
    def build_save_slot_keyboard(
        self,
        chat_id: int,
        save_slots: int,
    ) -> Any:
        """Build the save slot selection keyboard.

        Args:
            chat_id: Chat ID (for i18n)
            save_slots: Number of available save slots

        Returns:
            Platform-specific keyboard object
        """
        ...

    # --- Auth ---

    @abstractmethod
    async def is_admin(
        self,
        chat_id: int,
        user_id: int,
        raw: Any = None,
    ) -> bool:
        """Check if a user has admin permissions in a chat.

        Args:
            chat_id: Platform chat ID
            user_id: Platform user ID
            raw: Platform-specific event for additional context

        Returns:
            True if user is admin
        """
        ...

    # --- Interaction acknowledgement ---

    @abstractmethod
    async def answer_interaction(
        self,
        raw: Any,
        text: str = "",
    ) -> None:
        """Acknowledge an interaction (button press, slash command).

        Args:
            raw: Platform-specific interaction object
            text: Optional acknowledgement text
        """
        ...

    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform identifier string ('telegram' or 'discord')."""
        ...

    @abstractmethod
    async def update_chat_photo(self, chat_id: int, image_bytes: bytes) -> None:
        """Update the group/server avatar with the given PNG image bytes.

        Args:
            chat_id: Platform chat ID
            image_bytes: PNG image bytes for the new avatar
        """
        ...

    @property
    def preferred_animation_format(self) -> str:
        """Animation format for edit_game_message. Override per platform."""
        return "mp4"


# --- Adapter registry ---

_adapters: dict[str, BotAdapter] = {}


def register_adapter(platform: str, adapter: BotAdapter) -> None:
    """Register an adapter for a platform.

    Args:
        platform: Platform identifier ('telegram' or 'discord')
        adapter: BotAdapter instance
    """
    _adapters[platform] = adapter
    logger.info(f"Registered adapter for platform: {platform}")


def get_adapter(platform: str) -> Optional[BotAdapter]:
    """Get a registered adapter by platform name.

    Args:
        platform: Platform identifier ('telegram' or 'discord')

    Returns:
        BotAdapter if registered, None otherwise
    """
    return _adapters.get(platform)

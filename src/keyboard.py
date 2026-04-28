"""Keyboard layouts for Telegram inline keyboards.

This module provides functions to create inline keyboard layouts
for the game controls using python-telegram-bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.i18n import translation_manager
from src.models.game_state import BUTTON_LAYOUT, ChatConfig, GameButton, ModifierButtonSpec
from src.config import settings


def create_input_keyboard(
    chat_config: "ChatConfig | None" = None,
    modifier_specs: "list[ModifierButtonSpec] | None" = None,
    chat_username: str | None = None,
) -> InlineKeyboardMarkup:
    """Create the inline keyboard for game input.

    Creates a 3-row base layout (D-pad, A/B, Start/Select) plus an optional
    modifier button row derived from the loaded game's modifier specs.

    Args:
        chat_config: Chat configuration providing chat_id and modifier_states.
            If None, uses chat_id=0 and empty modifier_states.
        modifier_specs: Game-specific modifier button specs. If provided and
            non-empty, appends one row of modifier toggle buttons.

    Returns:
        InlineKeyboardMarkup with game control buttons

    Example:
        >>> keyboard = create_input_keyboard()
        >>> isinstance(keyboard, InlineKeyboardMarkup)
        True
    """
    chat_id = chat_config.chat_id if chat_config else 0
    modifier_states = chat_config.modifier_states if chat_config else {}

    keyboard = []

    for row in BUTTON_LAYOUT:
        keyboard_row = [
            InlineKeyboardButton(button.emoji, callback_data=button.value)
            for button in row
        ]
        keyboard.append(keyboard_row)

    if modifier_specs:
        modifier_row = []
        for spec in modifier_specs:
            is_active = modifier_states.get(spec.key, False)
            label_key = spec.active_label_key if is_active else spec.inactive_label_key
            label = translation_manager.get(label_key, chat_id)
            modifier_row.append(
                InlineKeyboardButton(label, callback_data=f"modifier_{spec.key}")
            )
        keyboard.append(modifier_row)

    import src.config as _cfg
    if chat_username and _cfg.telegram_bot_username:
        help_label = translation_manager.get("keyboard.buttons.help_button_label", chat_id)
        help_url = f"https://t.me/{_cfg.telegram_bot_username}?start=help-{chat_username}"
        keyboard.append([InlineKeyboardButton(help_label, url=help_url)])
    if _cfg.telegram_bot_username:
        shop_label = translation_manager.get("shop.button_label", chat_id)
        shop_url = f"https://t.me/{_cfg.telegram_bot_username}?start=shop_{chat_id}"
        keyboard.append([InlineKeyboardButton(shop_label, url=shop_url)])

    return InlineKeyboardMarkup(keyboard)


def create_game_message_text(
    status: str = "",
    recent_inputs: list[dict] | None = None,
    queue_length: int = 0,
    base_text_override: str | None = None,
    chat_id: int = 0,
) -> str:
    """Create the caption text for the game message.

    Args:
        status: Optional status message to display
        recent_inputs: List of recent input records (max 3) to display
        queue_length: Number of inputs in queue
        base_text_override: Custom base text to use instead of default "Sua vez!"
        chat_id: Telegram chat ID for translation (default 0 uses pt-BR)

    Returns:
        Formatted message text with game title, instructions, and recent inputs

    Example:
        >>> text = create_game_message_text("Processing: A...")
        >>> "Processing: A..." in text
        True
    """
    if queue_length == 0:
        if base_text_override is not None:
            base_text = base_text_override
        else:
            base_text = translation_manager.get("game.default_message", chat_id)
    else:
        plural = "s" if queue_length > 1 else ""
        base_text = translation_manager.get("game.queue_status", chat_id, count=queue_length, plural=plural)

    # Add recent inputs if available
    if recent_inputs:
        gameplay_tip = translation_manager.get("game.gameplay_tip", chat_id, sequence_length=settings.max_sequence_length)
        activity_header = translation_manager.get("game.recent_activity", chat_id)
        base_text += f"\n\n{gameplay_tip}\n\n{activity_header}"
        # Show most recent first (reversed)
        for inp in reversed(recent_inputs):
            user_name = inp["user_name"]

            # Handle both old format (single "button") and new format (list "buttons")
            if "buttons" in inp:
                # New format: list of buttons
                buttons = [GameButton(b) for b in inp["buttons"]]
                ellipsis="…" if len(buttons) > settings.max_sequence_length else ""

                if len(buttons) == 1:
                    button = buttons[0]
                    base_text += f"\n  {user_name}: {button.emoji} {translation_manager.get(f'keyboard.buttons.display_name.{button.value}', chat_id)}"
                else:
                    # Sequence: comma-separated emojis
                    emoji_sequence = ", ".join([b.emoji for b in buttons[-settings.max_sequence_length:]])
                    base_text += f"\n  {user_name}: {ellipsis}{emoji_sequence}"
            else:
                # Old format: single button (backward compatibility)
                button = GameButton(inp["button"])
                base_text += f"\n  {user_name}: {button.emoji} {translation_manager.get(f'keyboard.buttons.display_name.{button.value}', chat_id)}"

    if status:
        base_text += f"\n\n_{status}_"

    return base_text


def create_save_slot_keyboard(chat_id: int, save_slots: int = 5) -> InlineKeyboardMarkup:
    """Create keyboard for selecting save slots.
    
    Args:
        chat_id: The Telegram chat ID
        save_slots: Number of save slots available
    
    Returns:
        InlineKeyboardMarkup with save slot buttons
    """
    keyboard = []
    row = []
    
    for slot in range(save_slots):
        row.append(
            InlineKeyboardButton(
                f"Slot {slot}",
                callback_data=f"load_slot_{slot}",
            )
        )
        
        # 3 buttons per row
        if len(row) == 3:
            keyboard.append(row)
            row = []
    
    # Add any remaining buttons
    if row:
        keyboard.append(row)
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_load")])
    
    return InlineKeyboardMarkup(keyboard)


def get_button_from_callback(callback_data: str) -> GameButton | None:
    """Parse callback data and return the corresponding GameButton.
    
    Args:
        callback_data: The callback_data from Telegram
    
    Returns:
        GameButton if valid, None otherwise
    
    Example:
        >>> get_button_from_callback("a")
        <GameButton.A: 'a'>
        >>> get_button_from_callback("invalid")
        None
    """
    try:
        return GameButton(callback_data)
    except ValueError:
        return None


def is_valid_button_callback(callback_data: str) -> bool:
    """Check if callback data is a valid game button.
    
    Args:
        callback_data: The callback_data to check
    
    Returns:
        True if valid button callback, False otherwise
    
    Example:
        >>> is_valid_button_callback("start")
        True
        >>> is_valid_button_callback("invalid")
        False
    """
    return get_button_from_callback(callback_data) is not None or callback_data.startswith("modifier_")


# Button descriptions for help text

def create_help_text(chat_id: int) -> str:
    """Create help text describing all buttons.
    
    Returns:
        Formatted help text with button descriptions
    """
    text = translation_manager.get("help.intro", chat_id)

    text += translation_manager.get("help.controls_title", chat_id)
    
    text += translation_manager.get("help.directional", chat_id)
    # Skip deprecated buttons (SEQUENCE, ENVIAR) and directional buttons
    skip_buttons = [GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT, GameButton.SEQUENCE, GameButton.ENVIAR]
    for button in GameButton:
        if button in skip_buttons:
            continue

        text += f"{button.emoji} {translation_manager.get(f'keyboard.buttons.display_name.{button.value}', chat_id)}: {translation_manager.get(f'help.button_descriptions.{button.value}', chat_id)}\n"
    
    text += translation_manager.get("help.player_commands_title", chat_id)
    text += translation_manager.get("help.player_commands", chat_id)

    text += translation_manager.get("help.admin_commands_title", chat_id)
    text += translation_manager.get("help.admin_commands", chat_id)

    return text

"""Keyboard layouts for Telegram inline keyboards.

This module provides functions to create inline keyboard layouts
for the game controls using python-telegram-bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.models.game_state import BUTTON_LAYOUT, GameButton


def create_input_keyboard() -> InlineKeyboardMarkup:
    """Create the inline keyboard for game input.
    
    Creates a 3x3-style layout with D-pad, A/B buttons, and Start/Select.
    
    Layout:
        [⬆️]
        [⬅️] [➡️]
        [⬇️]
        [🅰️] [🅱️]
        [▶️] [🔘]
    
    Returns:
        InlineKeyboardMarkup with game control buttons
    
    Example:
        >>> keyboard = create_input_keyboard()
        >>> isinstance(keyboard, InlineKeyboardMarkup)
        True
    """
    keyboard = []
    
    for row in BUTTON_LAYOUT:
        keyboard_row = []
        for button in row:
            keyboard_row.append(
                InlineKeyboardButton(
                    button.emoji,
                    callback_data=button.value,
                )
            )
        keyboard.append(keyboard_row)
    
    return InlineKeyboardMarkup(keyboard)


def create_game_message_text(
    status: str = "",
    recent_inputs: list[dict] | None = None,
) -> str:
    """Create the caption text for the game message.

    Args:
        status: Optional status message to display
        recent_inputs: List of recent input records (max 3) to display

    Returns:
        Formatted message text with game title, instructions, and recent inputs

    Example:
        >>> text = create_game_message_text("Processing: A...")
        >>> "Processing: A..." in text
        True
    """
    base_text = "Hora de jogar!"

    # Add recent inputs if available
    if recent_inputs:
        base_text += "\n\n📖 *Atividade recente*:"
        # Show most recent first (reversed)
        for inp in reversed(recent_inputs):
            button = GameButton(inp["button"])
            user_name = inp["user_name"]
            base_text += f"\n  {user_name} pressionou {button.emoji} {button.display_name}"

    if status:
        base_text += f"\n\n_{status}_"

    return base_text


def create_disabled_keyboard() -> InlineKeyboardMarkup:
    """Create a disabled keyboard (shows buttons but they do nothing).
    
    This is used during input processing to prevent double-pressing.
    
    Returns:
        InlineKeyboardMarkup with disabled-style buttons
    """
    keyboard = []
    
    for row in BUTTON_LAYOUT:
        keyboard_row = []
        for button in row:
            # Use empty callback_data to make buttons do nothing
            keyboard_row.append(
                InlineKeyboardButton(
                    f"{button.emoji} ❌",
                    callback_data="disabled",
                )
            )
        keyboard.append(keyboard_row)
    
    return InlineKeyboardMarkup(keyboard)


def create_processing_keyboard(button: GameButton) -> InlineKeyboardMarkup:
    """Create a keyboard showing processing state.
    
    Args:
        button: The button being processed
    
    Returns:
        InlineKeyboardMarkup showing processing state
    """
    keyboard = [
        [InlineKeyboardButton(f"Processando: {button.display_name}...", callback_data="processing")]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def remove_keyboard() -> None:
    """Remove the keyboard entirely.
    
    Returns:
        None (pass to reply_markup to remove keyboard)
    """
    return None


def create_help_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard with help buttons.
    
    Returns:
        InlineKeyboardMarkup with help/refresh options
    """
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh Frame", callback_data="refresh"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


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


def create_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
    """Create a confirmation keyboard for destructive actions.
    
    Args:
        action: The action being confirmed (e.g., "reset", "delete")
    
    Returns:
        InlineKeyboardMarkup with Yes/No buttons
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm_{action}"),
            InlineKeyboardButton("❌ No", callback_data="cancel"),
        ]
    ]
    
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
    return get_button_from_callback(callback_data) is not None


# Button descriptions for help text
BUTTON_DESCRIPTIONS = {
    GameButton.UP: "Move up / Navigate up",
    GameButton.DOWN: "Move down / Navigate down",
    GameButton.LEFT: "Move left / Navigate left",
    GameButton.RIGHT: "Move right / Navigate right",
    GameButton.A: "Confirm / Interact / Select",
    GameButton.B: "Cancel / Back / Run",
    GameButton.START: "Open menu / Pause",
    GameButton.SELECT: "Select item / Switch",
    GameButton.WAIT: "Wait / Let game progress without input",
}


def create_help_text() -> str:
    """Create help text describing all buttons.
    
    Returns:
        Formatted help text with button descriptions
    """
    text = "🎮 *Game Controls*\n\n"
    text += "Press any button to control the game. "
    text += "The first button press wins!\n\n"
    text += "*Button Guide:*\n"
    
    for button in GameButton:
        text += f"{button.emoji} {button.display_name}: {BUTTON_DESCRIPTIONS[button]}\n"
    
    text += "\n*Commands:*\n"
    text += "/start\\_game - Start or restart the game\n"
    text += "/resume - Resume game in a new message\n"
    text += "/print - Capture screenshot without keyboard\n"
    text += "/save [slot] - Save game to slot\n"
    text += "/load [slot] - Load game from slot\n"
    text += "/status - Show game status\n"
    text += "/help - Show this help message"

    return text

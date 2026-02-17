"""Keyboard layouts for Telegram inline keyboards.

This module provides functions to create inline keyboard layouts
for the game controls using python-telegram-bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.models.game_state import BUTTON_LAYOUT, GameButton


def create_input_keyboard(running_mode: bool = False) -> InlineKeyboardMarkup:
    """Create the inline keyboard for game input.
    
    Creates a 3x3-style layout with D-pad, A/B buttons, and Start/Select.
    
    Args:
        running_mode: Whether running mode is enabled (affects RUN button emoji)
    
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
            # Special handling for RUN button based on running_mode
            if button == GameButton.RUN:
                emoji = "🏃 CORRENDO" if running_mode else "🚶 ANDANDO"
                keyboard_row.append(
                    InlineKeyboardButton(
                        emoji,
                        callback_data=button.value,
                    )
                )
            else:
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
    queue_length: int = 0,
    base_text_override: str | None = None,
) -> str:
    """Create the caption text for the game message.

    Args:
        status: Optional status message to display
        recent_inputs: List of recent input records (max 3) to display
        queue_length: Number of inputs in queue
        base_text_override: Custom base text to use instead of default "Sua vez!"

    Returns:
        Formatted message text with game title, instructions, and recent inputs

    Example:
        >>> text = create_game_message_text("Processing: A...")
        >>> "Processing: A..." in text
        True
    """
    if queue_length == 0:
        base_text = base_text_override if base_text_override is not None else "Sua vez!"
    else:
        base_text = f"{queue_length} input#{'s' if queue_length > 1 else ''} na fila."

    # Add recent inputs if available
    if recent_inputs:
        base_text += "\n\n📖 *Atividade recente*:"
        # Show most recent first (reversed)
        for inp in reversed(recent_inputs):
            user_name = inp["user_name"]

            # Handle both old format (single "button") and new format (list "buttons")
            if "buttons" in inp:
                # New format: list of buttons
                buttons = [GameButton(b) for b in inp["buttons"]]
                if len(buttons) == 1:
                    button = buttons[0]
                    base_text += f"\n  {user_name}: {button.emoji} {button.display_name}"
                else:
                    # Sequence: comma-separated emojis
                    emoji_sequence = ", ".join([b.emoji for b in buttons])
                    base_text += f"\n  {user_name}: {emoji_sequence}"
            else:
                # Old format: single button (backward compatibility)
                button = GameButton(inp["button"])
                base_text += f"\n  {user_name}: {button.emoji} {button.display_name}"

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


def remove_keyboard() -> None:
    """Remove the keyboard entirely.
    
    Returns:
        None (pass to reply_markup to remove keyboard)
    """
    return None


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
    GameButton.UP: "Mover para cima",
    GameButton.DOWN: "Mover para baixo",
    GameButton.LEFT: "Mover para a esquerda",
    GameButton.RIGHT: "Mover para a direita",
    GameButton.A: "Confirmar / Interagir / Selecionar",
    GameButton.B: "Cancelar / Voltar",
    GameButton.START: "Abrir menu / Pausar",
    GameButton.SELECT: "Selecionar item / Alternar",
    GameButton.WAIT: "Esperar / Deixar o jogo progredir sem input",
    GameButton.RUN: "Alternar modo corrida (segura B ao andar)",
}


def create_help_text() -> str:
    """Create help text describing all buttons.
    
    Returns:
        Formatted help text with button descriptions
    """
    text = "Como jogar:\n\n"
    text += "Pressione qualquer botão para controlar o jogo. Após cada comando, o jogo irá avançar alguns segundos e atualizar a imagem."
    text += "\n\n"
    text += "Você também pode construir uma sequência de comandos e enviar todos de uma vez."
    text += "\n\n"

    text += "*Controles*\n"
    
    text += "⬆️⬅️⬇️➡️ Direcionais: Mover\n"
    # Skip deprecated buttons (SEQUENCE, ENVIAR) and directional buttons
    skip_buttons = [GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT, GameButton.SEQUENCE, GameButton.ENVIAR]
    for button in GameButton:
        if button in skip_buttons:
            continue

        text += f"{button.emoji} {button.display_name}: {BUTTON_DESCRIPTIONS[button]}\n"
    
    text += "\n*Comandos do jogador:*\n"
    text += "/resume - Retoma o jogo em uma nova mensagem\n"
    text += "/print - Captura a tela atual e envia na conversa\n"
    text += "/recap - Envia o último trecho de animação novamente\n"
    text += "/status - Mostra algumas informações de status\n"
    text += "/help - Mostra esta mensagem de ajuda"

    text += "\n\n"
    text += "\n*Comandos do administrador:*\n"
    text += "/start\\_game - Inicia ou reinicia o jogo\n"
    text += "/save [slot] - Salva o jogo em um slot\n"
    text += "/load [slot] - Carrega o jogo de um slot\n"

    return text

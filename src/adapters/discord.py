"""Discord platform adapter.

Implements BotAdapter for Discord using discord.py.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

import discord

from src.adapters.base import BotAdapter
from src.i18n import translation_manager
from src.models.game_state import BUTTON_LAYOUT, GameButton
from src.utils.state_manager import state_manager

if TYPE_CHECKING:
    from src.models.game_state import ChatConfig, ModifierButtonSpec
    from src.shop.flow.screens import ShopScreen

logger = logging.getLogger(__name__)

# Lazy import to avoid forcing discord.py at import time
def _discord():
    import discord
    return discord


# ---------------------------------------------------------------------------
# Sequence input mappings (Discord-exclusive modal feature)
# ---------------------------------------------------------------------------

# Maps canonical mapping names to {UPPERCASE_CHAR: GameButton}.
# WAIT is intentionally not included — it is not supported in sequence input.
SEQUENCE_MAPPINGS: dict[str, dict[str, "GameButton"]] = {
    "ULDR AB ST": {
        "U": GameButton.UP,  "L": GameButton.LEFT,  "D": GameButton.DOWN, "R": GameButton.RIGHT,
        "A": GameButton.A,   "B": GameButton.B,     "S": GameButton.SELECT, "T": GameButton.START,
    },
    "WASD ZX CV": {
        "W": GameButton.UP,  "A": GameButton.LEFT,  "S": GameButton.DOWN, "D": GameButton.RIGHT,
        "Z": GameButton.A,   "X": GameButton.B,     "C": GameButton.SELECT, "V": GameButton.START,
    },
    "IJKL NM UO": {
        "I": GameButton.UP,  "J": GameButton.LEFT,  "K": GameButton.DOWN, "L": GameButton.RIGHT,
        "N": GameButton.A,   "M": GameButton.B,     "U": GameButton.SELECT, "O": GameButton.START,
    },
    "8426 13 79": {
        "8": GameButton.UP,  "4": GameButton.LEFT,  "2": GameButton.DOWN, "6": GameButton.RIGHT,
        "1": GameButton.A,   "3": GameButton.B,     "7": GameButton.SELECT, "9": GameButton.START,
    },
}

_DEFAULT_MAPPING = "ULDR AB ST"


def parse_sequence(
    sequence: str,
    mapping_key: str,
) -> tuple[list["GameButton"], list[str]]:
    """Parse a sequence string into GameButtons using the given mapping.

    Matching is case-insensitive: input is normalised with .upper() before lookup.
    Unknown mapping_key falls back to the default ("ULDR AB ST").

    Args:
        sequence: Raw character sequence from the user.
        mapping_key: One of the SEQUENCE_MAPPINGS keys.

    Returns:
        (buttons, invalid_chars) — invalid_chars contains deduplicated uppercase
        characters that were not found in the mapping.
    """
    mapping = SEQUENCE_MAPPINGS.get(mapping_key, SEQUENCE_MAPPINGS[_DEFAULT_MAPPING])
    buttons: list[GameButton] = []
    invalid: list[str] = []
    for char in sequence.upper():
        if char in mapping:
            buttons.append(mapping[char])
        elif char not in invalid:
            invalid.append(char)
    return buttons, invalid


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

        # Discord-exclusive: sequence input button on its own row.
        # seq_row is 3 (no modifiers) or 4 (modifiers on row 3).
        # Discord allows max 5 rows (0–4); safe with current BUTTON_LAYOUT (3 rows).
        seq_row = len(BUTTON_LAYOUT) + (1 if modifier_specs else 0)
        seq_btn = discord.ui.Button(
            label=translation_manager.get("discord.sequence_modal.button_label", chat_id),
            custom_id="open_sequence_modal",
            row=seq_row,
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(seq_btn)

        shop_btn = discord.ui.Button(
            label=translation_manager.get("shop.button_label", chat_id),
            custom_id="open_shop",
            row=seq_row,
            style=discord.ButtonStyle.secondary,
        )
        view.add_item(shop_btn)

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


def render_discord_shop_screen(screen: "ShopScreen") -> Any:
    """Build a discord.ui.View from any ShopScreen."""
    import discord
    from src.shop.flow.screens import CategoryListScreen, ItemListScreen, SelectionScreen
    from src.i18n import translation_manager

    view = discord.ui.View(timeout=None)
    chat_id = screen.chat_id

    if isinstance(screen, CategoryListScreen):
        for i, cat in enumerate(screen.categories):
            label = translation_manager.get(cat.label, chat_id)
            view.add_item(discord.ui.Button(
                label=label,
                custom_id=f"shop_cat_{cat.id}_0",
                row=i,
                style=discord.ButtonStyle.primary,
            ))
        nav_row = len(screen.categories)
        if screen.page > 0:
            view.add_item(discord.ui.Button(
                label=translation_manager.get("shop.prev", chat_id),
                custom_id=f"shop_page_{screen.page - 1}",
                row=nav_row,
                style=discord.ButtonStyle.secondary,
            ))
        if screen.page < screen.total_pages - 1:
            view.add_item(discord.ui.Button(
                label=translation_manager.get("shop.next", chat_id),
                custom_id=f"shop_page_{screen.page + 1}",
                row=nav_row,
                style=discord.ButtonStyle.secondary,
            ))
        return view

    if isinstance(screen, ItemListScreen):
        items_per_row = min(screen.category.items_per_row, 5)
        current_row = 0
        count_in_row = 0
        for item in screen.items:
            if current_row >= 4:
                break
            name = translation_manager.get(item.name_i18n_key, chat_id)
            is_owned = item.one_time_purchase and item.id in screen.owned_items
            display_name = f"✓ {name}" if is_owned else name
            if is_owned or item.cost == 0:
                cost_label = translation_manager.get("shop.free", chat_id)
            else:
                cost_label = f"{item.cost:,} pts"
            view.add_item(discord.ui.Button(
                label=f"{display_name} — {cost_label}",
                custom_id=f"shop_buy_{item.id}:{screen.category.id}:{screen.page}",
                row=current_row,
                style=discord.ButtonStyle.primary,
            ))
            count_in_row += 1
            if count_in_row >= items_per_row:
                count_in_row = 0
                current_row += 1
        # Nav row (row 4)
        if screen.page > 0:
            view.add_item(discord.ui.Button(
                label=translation_manager.get("shop.prev", chat_id),
                custom_id=f"shop_cat_{screen.category.id}_{screen.page - 1}",
                row=4,
                style=discord.ButtonStyle.secondary,
            ))
        view.add_item(discord.ui.Button(
            label=translation_manager.get("shop.back", chat_id),
            custom_id="shop_back",
            row=4,
            style=discord.ButtonStyle.secondary,
        ))
        if screen.page < screen.total_pages - 1:
            view.add_item(discord.ui.Button(
                label=translation_manager.get("shop.next", chat_id),
                custom_id=f"shop_cat_{screen.category.id}_{screen.page + 1}",
                row=4,
                style=discord.ButtonStyle.secondary,
            ))
        return view

    # SelectionScreen — rows 0-3 for options, row 4 for nav
    current_row = 0
    count_in_row = 0
    options_per_row = 3
    for option in screen.options:
        if current_row >= 4:
            break
        view.add_item(discord.ui.Button(
            label=option.label,
            custom_id=f"shop_select_{option.value}",
            row=current_row,
            style=discord.ButtonStyle.primary,
        ))
        count_in_row += 1
        if count_in_row >= options_per_row:
            count_in_row = 0
            current_row += 1
    if screen.page > 0:
        view.add_item(discord.ui.Button(
            label=translation_manager.get("shop.prev", chat_id),
            custom_id=f"shop_sel_page_{screen.page - 1}",
            row=4,
            style=discord.ButtonStyle.secondary,
        ))
    view.add_item(discord.ui.Button(
        label=translation_manager.get("shop.cancel", chat_id),
        custom_id="shop_cancel",
        row=4,
        style=discord.ButtonStyle.danger,
    ))
    if screen.page < screen.total_pages - 1:
        view.add_item(discord.ui.Button(
            label=translation_manager.get("shop.next", chat_id),
            custom_id=f"shop_sel_page_{screen.page + 1}",
            row=4,
            style=discord.ButtonStyle.secondary,
        ))
    return view


class DiscordSequenceModal(discord.ui.Modal):
    """Discord modal for entering a button sequence.

    Opens when the user clicks the '⌨️ Input Sequence' keyboard button.
    Contains a String Select (mapping choice) and a TextInput (the sequence),
    each wrapped in a discord.ui.Label for visible headers inside the modal.

    Must subclass discord.ui.Modal directly — monkey-patching on_submit onto
    a plain discord.ui.Modal instance does not work because discord.py dispatches
    on_submit through its class mechanism, not instance attribute lookup.
    """

    def __init__(
        self,
        title: str,
        preferred_mapping: str,
        chat_id: int,
        message_id: int,
        user_id: int,
        user_name: str,
        adapter: Any,
        handler: Any,
    ) -> None:
        super().__init__(title=title)

        self._chat_id = chat_id
        self._message_id = message_id
        self._user_id = user_id
        self._user_name = user_name
        self._adapter = adapter
        self._handler = handler

        from src.config import settings
        self.sequence_input = discord.ui.TextInput(
            placeholder=translation_manager.get(
                "discord.sequence_modal.sequence_placeholder",
                chat_id,
                max=settings.max_sequence_length,
            ),
            max_length=settings.max_sequence_length,
            min_length=1,
            required=True,
        )
        self.add_item(
            discord.ui.Label(
                text=translation_manager.get("discord.sequence_modal.sequence_label", chat_id),
                description=translation_manager.get("discord.sequence_modal.sequence_description", chat_id),
                component=self.sequence_input,
            )
        )
        
        # Mapping select — pre-select the user's preferred mapping
        options = [
            discord.SelectOption(
                label=key,
                value=key,
                default=(key == preferred_mapping),
            )
            for key in SEQUENCE_MAPPINGS
        ]
        self.mapping_select = discord.ui.Select(
            placeholder=translation_manager.get("discord.sequence_modal.mapping_placeholder", chat_id),
            options=options,
            min_values=1,
            max_values=1,
        )
        self.add_item(
            discord.ui.Label(
                text=translation_manager.get("discord.sequence_modal.mapping_label", chat_id),
                description=translation_manager.get("discord.sequence_modal.mapping_description", chat_id),
                component=self.mapping_select,
            )
        )


    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""

        try:
            mapping_key = self.mapping_select.values[0]
            raw_sequence = self.sequence_input.value

            buttons, invalid_chars = parse_sequence(raw_sequence, mapping_key)

            if invalid_chars:
                chars_str = ", ".join(invalid_chars)
                error_msg = translation_manager.get(
                    "discord.sequence_modal.invalid_chars",
                    self._chat_id,
                    chars=chars_str,
                )
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

            ok, error = await self._handler.handle_sequence_input(
                buttons=buttons,
                chat_id=self._chat_id,
                message_id=self._message_id,
                user_id=self._user_id,
                user_name=self._user_name,
                adapter=self._adapter,
            )

            if ok:
                state_manager.set_user_preference(
                    "discord", self._user_id, "sequence_mapping", mapping_key
                )
                buttons_str = "".join(b.emoji for b in buttons)
                confirm_msg = translation_manager.get(
                    "discord.sequence_modal.success",
                    self._chat_id,
                    buttons=buttons_str,
                )
                await interaction.response.send_message(confirm_msg, ephemeral=True, delete_after=2.0)
            else:
                await interaction.response.send_message(error, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in DiscordSequenceModal.on_submit: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An unexpected error occurred.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ An unexpected error occurred.", ephemeral=True
                    )
            except Exception:
                pass


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

        if media_type == "mp4":
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
        reply_markup: Optional[Any] = None,
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
            file = discord.File(animation, filename="animation.avif")
        else:
            file = discord.File(io.BytesIO(animation), filename="animation.avif")

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

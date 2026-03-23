"""Discord bot handler.

This module implements the Discord gateway bot using discord.py.
It registers slash commands and routes interactions to the shared
business logic in commands.py and input_handler.py.
"""

import logging
from typing import Any

from src.adapters.base import CommandContext, register_adapter
from src.handlers.commands import COMMAND_HANDLERS
from src.handlers.input_handler import get_input_handler
from src.keyboard import is_valid_button_callback
from src.utils.state_manager import state_manager
from src.config import settings
from src.i18n import translation_manager

try:
    from src.adapters.discord import DiscordAdapter
except ImportError:
    DiscordAdapter = None  # type: ignore[assignment,misc]

try:
    from src.adapters.discord import DiscordSequenceModal
except ImportError:
    DiscordSequenceModal = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


def _is_chat_allowed(channel_id: int) -> bool:
    """Return True if channel_id is in the allowed_chat_ids list, or if the list is empty."""
    if not settings.allowed_chat_ids:
        return True
    return channel_id in settings.allowed_chat_ids


def create_discord_bot() -> Any:
    """Create and configure the Discord bot instance.

    Returns:
        Configured discord.ext.commands.Bot instance
    """
    import discord
    from discord import app_commands
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info(f"Discord bot logged in as {bot.user}")
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} Discord slash command(s)")
        except Exception as e:
            logger.error(f"Failed to sync Discord slash commands: {e}")

        # Register adapter once bot is ready
        adapter = DiscordAdapter(bot)
        register_adapter("discord", adapter)
        logger.info("Discord adapter registered")

    def _get_discord_adapter() -> DiscordAdapter:
        from src.adapters.base import get_adapter
        adapter = get_adapter("discord")
        if adapter is None:
            # Fallback: create a new adapter (bot may not be ready yet)
            adapter = DiscordAdapter(bot)
        return adapter

    def _build_ctx(interaction: discord.Interaction, args: list[str]) -> CommandContext:
        """Build a CommandContext from a Discord Interaction."""
        adapter = _get_discord_adapter()
        chat_id = interaction.channel_id
        user = interaction.user
        user_id = user.id
        user_name = user.display_name or str(user)
        return CommandContext(
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            args=args,
            adapter=adapter,
            raw=interaction,
        )

    async def _run_command(
        interaction: discord.Interaction, handler_key: str, args: list[str]
    ) -> None:
        """Defer ephemerally, run command handler, then delete the deferred response."""
        if not _is_chat_allowed(interaction.channel_id):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ctx = _build_ctx(interaction, args)
        try:
            await COMMAND_HANDLERS[handler_key](ctx)
        finally:
            try:
                await interaction.delete_original_response()
            except Exception:
                pass

    # --- Slash Commands ---

    @bot.tree.command(name="start_game", description="Start or restart the game")
    async def slash_start_game(interaction: discord.Interaction):
        await _run_command(interaction, "start_game", [])

    @bot.tree.command(name="resume", description="Resume the game with a fresh message")
    async def slash_resume(interaction: discord.Interaction):
        await _run_command(interaction, "resume", [])

    @bot.tree.command(name="reboot", description="Reboot the game from initial state (admin only)")
    async def slash_reboot(interaction: discord.Interaction):
        await _run_command(interaction, "reboot", [])

    @bot.tree.command(name="save", description="Save the current game state")
    @app_commands.describe(slot="Save slot number (optional)")
    async def slash_save(interaction: discord.Interaction, slot: int = None):
        await _run_command(interaction, "save", [str(slot)] if slot is not None else [])

    @bot.tree.command(name="load", description="Load a game state from a slot")
    @app_commands.describe(slot="Save slot number or 'backup YYYYMMDD'")
    async def slash_load(interaction: discord.Interaction, slot: str = None):
        await _run_command(interaction, "load", slot.split() if slot else [])

    @bot.tree.command(name="status", description="Show current game status")
    async def slash_status(interaction: discord.Interaction):
        await _run_command(interaction, "status", [])

    @bot.tree.command(name="print", description="Send the current game frame as a screenshot")
    async def slash_print(interaction: discord.Interaction):
        await _run_command(interaction, "print", [])

    @bot.tree.command(name="help", description="Show help information")
    async def slash_help(interaction: discord.Interaction):
        await _run_command(interaction, "help", [])

    @bot.tree.command(name="gif", description="Resend the last animation")
    async def slash_gif(interaction: discord.Interaction):
        await _run_command(interaction, "gif", [])

    @bot.tree.command(name="recap", description="Show today's gameplay timelapse")
    @app_commands.describe(date="Date in YYYYMMDD format (optional, defaults to today)")
    async def slash_recap(interaction: discord.Interaction, date: str = None):
        await _run_command(interaction, "recap", [date] if date else [])

    @bot.tree.command(name="maintenance", description="Toggle maintenance mode (admin only)")
    @app_commands.describe(mode="on or off")
    async def slash_maintenance(interaction: discord.Interaction, mode: str = None):
        await _run_command(interaction, "maintenance", [mode] if mode else [])

    @bot.tree.command(name="m", description="Set or clear custom message text (admin only)")
    @app_commands.describe(text="Custom text (leave empty to clear)")
    async def slash_message(interaction: discord.Interaction, text: str = None):
        await _run_command(interaction, "m", text.split() if text else [])

    @bot.tree.command(name="language", description="Change bot language")
    @app_commands.describe(code="Language code (e.g. en-US, pt-BR)")
    async def slash_language(interaction: discord.Interaction, code: str = None):
        await _run_command(interaction, "language", [code] if code else [])

    @bot.tree.command(name="mirror", description="Configure chat mirroring (admin only)")
    @app_commands.describe(target="Leader chat ID, 'unset', or 'status'")
    async def slash_mirror(interaction: discord.Interaction, target: str = None):
        await _run_command(interaction, "mirror", [target] if target else [])

    @bot.tree.command(name="feature", description="Toggle a feature flag (admin only)")
    @app_commands.describe(flag="Feature flag name", value="true or false")
    async def slash_feature(interaction: discord.Interaction, flag: str = None, value: str = None):
        args = [a for a in [flag, value] if a is not None]
        await _run_command(interaction, "feature", args)

    # --- Component Interactions (Button Presses) ---

    @bot.listen("on_interaction")
    async def on_interaction(interaction: discord.Interaction):
        """Route Discord component interactions to the game input handler.

        Uses @bot.listen (not @bot.event) so the built-in on_interaction
        that dispatches slash commands via the CommandTree is preserved.
        We only handle component (button) interactions here.
        """
        if interaction.type != discord.InteractionType.component:
            return

        try:
            custom_id = interaction.data.get("custom_id", "")
            channel_id = interaction.channel_id

            if not _is_chat_allowed(channel_id):
                await interaction.response.send_message("Unauthorized.", ephemeral=True)
                return

            if is_valid_button_callback(custom_id):
                # Minimize response time from button inputs
                await interaction.response.defer()
            message_id = interaction.message.id if interaction.message else None
            user = interaction.user
            user_id = user.id
            user_name = user.display_name or str(user)

            adapter = _get_discord_adapter()

            config = state_manager.get_or_create_chat_config(channel_id)

            # Update platform if not set
            if config.platform != "discord":
                config.platform = "discord"
                state_manager.save_chat_config(config)

            handler = get_input_handler()

            # Handle load slot selections
            if custom_id.startswith("load_slot_"):
                try:
                    slot = int(custom_id.split("_")[-1])
                    ctx = _build_ctx(interaction, [str(slot)])
                    await interaction.response.defer(ephemeral=True)
                    await COMMAND_HANDLERS["load"](ctx)
                except (ValueError, IndexError):
                    logger.warning(f"Invalid load_slot custom_id: {custom_id}")
                return

            if custom_id == "cancel_load":
                await interaction.response.defer(ephemeral=True)
                return

            # ── NEW: Open sequence input modal ──
            if custom_id == "open_sequence_modal":
                # Maintenance mode check — use same hardcoded message as existing button handler
                if config.maintenance_mode:
                    is_admin = await adapter.is_admin(channel_id, user_id, interaction)
                    if not is_admin:
                        await interaction.response.send_message(
                            "No momento estamos em manutenção, apenas admins podem enviar comandos.",
                            ephemeral=True,
                        )
                        return
                # Load preferred mapping (default: "ULDR AB ST")
                preferred_mapping = state_manager.get_user_preference(
                    "discord", user_id, "sequence_mapping"
                ) or "ULDR AB ST"
                title = translation_manager.get("discord.sequence_modal.modal_title", channel_id)
                modal = DiscordSequenceModal(
                    title=title,
                    preferred_mapping=preferred_mapping,
                    chat_id=channel_id,
                    message_id=message_id,
                    user_id=user_id,
                    user_name=user_name,
                    adapter=adapter,
                    handler=handler,
                )
                await interaction.response.send_modal(modal)
                return
            # ── END: Open sequence input modal ──

            # ── Shop interactions ──
            if custom_id in ("open_shop", "shop_back") or custom_id.startswith(
                ("shop_page_", "shop_buy_", "shop_cat_")
            ):
                from src.shop.shop_manager import shop_manager, build_shop_text
                from src.adapters.discord import build_discord_shop_view

                if custom_id == "open_shop" or custom_id == "shop_back":
                    balance = shop_manager.get_balance("discord", user_id)
                    content = build_shop_text(balance, None, 0, 1, channel_id, platform="discord", user_id=user_id)
                    view = build_discord_shop_view(0, 1, [], channel_id, category=None)
                    if custom_id == "open_shop":
                        await interaction.response.send_message(content=content, view=view, ephemeral=True)
                    else:
                        await interaction.response.edit_message(content=content, view=view)
                    return

                if custom_id.startswith("shop_page_"):
                    try:
                        page = int(custom_id.removeprefix("shop_page_"))
                    except ValueError:
                        return
                    balance = shop_manager.get_balance("discord", user_id)
                    content = build_shop_text(balance, None, page, 1, channel_id, platform="discord", user_id=user_id)
                    view = build_discord_shop_view(page, 1, [], channel_id, category=None)
                    await interaction.response.edit_message(content=content, view=view)
                    return

                if custom_id.startswith("shop_cat_"):
                    # Format: shop_cat_{cat_id}_{page}
                    rest = custom_id.removeprefix("shop_cat_")
                    parts = rest.rsplit("_", 1)
                    if len(parts) != 2:
                        return
                    cat_id, page_str = parts
                    try:
                        page = int(page_str)
                    except ValueError:
                        return
                    category = shop_manager.get_category(cat_id)
                    if category is None:
                        return
                    items, total_pages = shop_manager.get_category_page(cat_id, page)
                    balance = shop_manager.get_balance("discord", user_id)
                    content = build_shop_text(balance, category, page, total_pages, channel_id, platform="discord", user_id=user_id)
                    view = build_discord_shop_view(page, total_pages, items, channel_id, category=category)
                    await interaction.response.edit_message(content=content, view=view)
                    return

                if custom_id.startswith("shop_buy_"):
                    item_id = custom_id.removeprefix("shop_buy_")
                    result = shop_manager.purchase("discord", user_id, item_id, chat_id=channel_id, user_name=user_name)
                    balance = shop_manager.get_balance("discord", user_id)
                    if result.success:
                        item_name = translation_manager.get(result.item.name_i18n_key, channel_id)
                        status = translation_manager.get(
                            "shop.purchase_success", channel_id, item_name=item_name
                        )
                    else:
                        cost = f"{result.item.cost:,}" if result.item else "?"
                        status = translation_manager.get(
                            "shop.insufficient_funds", channel_id,
                            cost=cost, balance=f"{balance:,}"
                        )
                    # Return to outer category listing after purchase
                    content = build_shop_text(balance, None, 0, 1, channel_id, status_message=status, platform="discord", user_id=user_id)
                    view = build_discord_shop_view(0, 1, [], channel_id, category=None)
                    await interaction.response.edit_message(content=content, view=view)
                    return
            # ── END: Shop interactions ──

            # Game button or modifier button
            if not is_valid_button_callback(custom_id):
                logger.debug(f"Unhandled Discord component: {custom_id}")
                return

            # Maintenance mode check
            if config.maintenance_mode and not custom_id.startswith("modifier_"):
                is_admin = await adapter.is_admin(channel_id, user_id, interaction)
                if not is_admin:
                    await interaction.response.send_message(
                        "No momento estamos em manutenção, apenas admins podem enviar comandos.",
                        ephemeral=True,
                    )
                    return

            await handler.handle_button_press(
                callback_data=custom_id,
                chat_id=channel_id,
                message_id=message_id,
                user_id=user_id,
                user_name=user_name,
                adapter=adapter,
                raw=interaction,
            )

        except Exception as e:
            logger.error(f"Error handling Discord interaction: {e}", exc_info=True)

    return bot

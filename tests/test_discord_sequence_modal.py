"""Tests for Discord sequence modal mapping and parsing."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

from src.models.game_state import GameButton


class TestSequenceMappings:

    def test_all_four_mapping_keys_present(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        assert "ULDR AB ST" in SEQUENCE_MAPPINGS
        assert "WASD ZX CV" in SEQUENCE_MAPPINGS
        assert "IJKL NM UO" in SEQUENCE_MAPPINGS
        assert "8426 13 79" in SEQUENCE_MAPPINGS

    def test_each_mapping_has_exactly_eight_entries(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        for key, mapping in SEQUENCE_MAPPINGS.items():
            assert len(mapping) == 8, f"{key} should map 8 characters"

    def test_each_mapping_covers_all_eight_buttons(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        required = {GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT,
                    GameButton.A, GameButton.B, GameButton.START, GameButton.SELECT}
        for key, mapping in SEQUENCE_MAPPINGS.items():
            assert set(mapping.values()) == required, f"{key} missing buttons"

    def test_uldr_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["ULDR AB ST"]
        assert m["U"] == GameButton.UP
        assert m["L"] == GameButton.LEFT
        assert m["D"] == GameButton.DOWN
        assert m["R"] == GameButton.RIGHT
        assert m["A"] == GameButton.A
        assert m["B"] == GameButton.B
        assert m["S"] == GameButton.SELECT
        assert m["T"] == GameButton.START

    def test_wasd_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["WASD ZX CV"]
        assert m["W"] == GameButton.UP
        assert m["A"] == GameButton.LEFT
        assert m["S"] == GameButton.DOWN
        assert m["D"] == GameButton.RIGHT
        assert m["Z"] == GameButton.A
        assert m["X"] == GameButton.B
        assert m["C"] == GameButton.SELECT
        assert m["V"] == GameButton.START

    def test_ijkl_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["IJKL NM UO"]
        assert m["I"] == GameButton.UP
        assert m["J"] == GameButton.LEFT
        assert m["K"] == GameButton.DOWN
        assert m["L"] == GameButton.RIGHT
        assert m["N"] == GameButton.A
        assert m["M"] == GameButton.B
        assert m["U"] == GameButton.SELECT
        assert m["O"] == GameButton.START

    def test_numpad_mapping_chars(self):
        from src.adapters.discord import SEQUENCE_MAPPINGS
        m = SEQUENCE_MAPPINGS["8426 13 79"]
        assert m["8"] == GameButton.UP
        assert m["4"] == GameButton.LEFT
        assert m["2"] == GameButton.DOWN
        assert m["6"] == GameButton.RIGHT
        assert m["1"] == GameButton.A
        assert m["3"] == GameButton.B
        assert m["7"] == GameButton.SELECT
        assert m["9"] == GameButton.START


class TestParseSequence:

    def test_valid_uppercase_sequence(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("ULDR", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_valid_lowercase_sequence_case_insensitive(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("uldr", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_mixed_case(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("uLdR", "ULDR AB ST")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_invalid_char_reported(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("UXY", "ULDR AB ST")
        assert buttons == [GameButton.UP]
        assert "X" in invalid
        assert "Y" in invalid

    def test_invalid_chars_deduplicated(self):
        from src.adapters.discord import parse_sequence
        _, invalid = parse_sequence("UXX", "ULDR AB ST")
        assert invalid.count("X") == 1

    def test_wasd_mapping(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("wasd", "WASD ZX CV")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_numpad_mapping(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("8426", "8426 13 79")
        assert buttons == [GameButton.UP, GameButton.LEFT, GameButton.DOWN, GameButton.RIGHT]
        assert invalid == []

    def test_unknown_mapping_key_falls_back_to_uldr(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("U", "UNKNOWN_KEY")
        assert buttons == [GameButton.UP]

    def test_empty_sequence(self):
        from src.adapters.discord import parse_sequence
        buttons, invalid = parse_sequence("", "ULDR AB ST")
        assert buttons == []
        assert invalid == []

    def test_custom_id_is_not_valid_button_callback(self):
        """open_sequence_modal must not match is_valid_button_callback."""
        from src.keyboard import is_valid_button_callback
        assert not is_valid_button_callback("open_sequence_modal"), (
            "open_sequence_modal must never match a GameButton value or modifier_ prefix"
        )


class TestDiscordGameViewSequenceButton:

    def test_sequence_button_present_in_view_without_modifiers(self):
        """View built without modifiers must contain an open_sequence_modal button."""
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        custom_ids = [item.custom_id for item in view.children]
        assert "open_sequence_modal" in custom_ids

    def test_sequence_button_present_in_view_with_modifiers(self):
        """View built with modifiers must still contain the sequence button."""
        from src.adapters.discord import DiscordGameView
        from src.models.game_state import ModifierButtonSpec, ChatConfig, GameButton
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
            inactive_label_key="keyboard.modifier.run.inactive",
            active_label_key="keyboard.modifier.run.active",
        )
        config = ChatConfig(chat_id=1)
        view = DiscordGameView.build(chat_config=config, modifier_specs=[spec])
        custom_ids = [item.custom_id for item in view.children]
        assert "open_sequence_modal" in custom_ids

    def test_sequence_button_on_correct_row_without_modifiers(self):
        """Without modifiers, sequence button must be on row 3 (after 3 game rows 0-2)."""
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.row == 3

    def test_sequence_button_on_correct_row_with_modifiers(self):
        """With modifiers on row 3, sequence button must be on row 4."""
        from src.adapters.discord import DiscordGameView
        from src.models.game_state import ModifierButtonSpec, ChatConfig, GameButton
        spec = ModifierButtonSpec(
            key="run",
            modifier_button=GameButton.B,
            applies_to=[GameButton.UP, GameButton.DOWN, GameButton.LEFT, GameButton.RIGHT],
            inactive_label_key="keyboard.modifier.run.inactive",
            active_label_key="keyboard.modifier.run.active",
        )
        config = ChatConfig(chat_id=1)
        view = DiscordGameView.build(chat_config=config, modifier_specs=[spec])
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.row == 4

    def test_sequence_button_style_is_secondary(self):
        """Sequence button must use secondary style."""
        import discord
        from src.adapters.discord import DiscordGameView
        view = DiscordGameView.build(chat_config=None, modifier_specs=None)
        seq_btn = next(item for item in view.children if item.custom_id == "open_sequence_modal")
        assert seq_btn.style == discord.ButtonStyle.secondary


class TestDiscordSequenceModalOnSubmit:

    def _make_modal(self, preferred_mapping="ULDR AB ST"):
        from src.adapters.discord import DiscordSequenceModal
        from src.handlers.input_handler import InputHandler
        handler = InputHandler()
        adapter = MagicMock()
        adapter.platform = "discord"
        return DiscordSequenceModal(
            title="Input Sequence",
            preferred_mapping=preferred_mapping,
            chat_id=100,
            message_id=42,
            user_id=999,
            user_name="Alice",
            adapter=adapter,
            handler=handler,
        )

    def _make_interaction(self):
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        return interaction

    @pytest.mark.asyncio
    async def test_invalid_chars_sends_ephemeral_error(self):
        """Invalid characters produce an ephemeral error; no buttons queued."""
        import os
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
        os.environ.setdefault("WEBHOOK_URL", "https://test.example.com")
        os.environ.setdefault("WEBHOOK_SECRET", "test_secret_1234567890")

        from src.adapters.discord import DiscordSequenceModal
        from src.handlers.input_handler import InputHandler

        modal = self._make_modal()
        # Simulate Select returning mapping key
        modal.mapping_select = MagicMock()
        modal.mapping_select.values = ["ULDR AB ST"]
        # Simulate TextInput returning sequence with invalid char
        modal.sequence_input = MagicMock()
        modal.sequence_input.value = "UXZ"

        interaction = self._make_interaction()

        with patch("src.adapters.discord.state_manager"):
            await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        call_kwargs = interaction.response.send_message.call_args
        assert call_kwargs.kwargs.get("ephemeral") is True
        msg = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("content", "")
        assert "X" in msg or "Z" in msg  # invalid chars reported

    @pytest.mark.asyncio
    async def test_valid_sequence_saves_preference_and_sends_confirmation(self):
        """Valid sequence: preference saved, confirmation sent."""
        from src.adapters.discord import DiscordSequenceModal
        from src.handlers.input_handler import InputHandler
        from src.models.game_state import GameSession, ChatGameState

        handler = InputHandler()
        session_state = ChatGameState(chat_id=100, message_id=42)
        handler._sessions[100] = GameSession(chat_id=100, state=session_state)

        adapter = MagicMock()
        adapter.platform = "discord"
        modal = DiscordSequenceModal(
            title="Input Sequence",
            preferred_mapping="ULDR AB ST",
            chat_id=100,
            message_id=42,
            user_id=999,
            user_name="Alice",
            adapter=adapter,
            handler=handler,
        )
        modal.mapping_select = MagicMock()
        modal.mapping_select.values = ["WASD ZX CV"]
        modal.sequence_input = MagicMock()
        modal.sequence_input.value = "wd"

        interaction = self._make_interaction()

        with patch("src.adapters.discord.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100), \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch.object(handler, "_is_processing", return_value=True):
            mock_sm.set_user_preference = MagicMock()
            mock_ih_sm.get_or_create_chat_config.return_value = MagicMock()
            await modal.on_submit(interaction)

        # Preference must be saved
        mock_sm.set_user_preference.assert_called_once_with(
            "discord", 999, "sequence_mapping", "WASD ZX CV"
        )
        # Confirmation sent as ephemeral
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_preference_not_saved_when_handler_fails(self):
        """Preference must NOT be saved when handle_sequence_input returns False."""
        from src.adapters.discord import DiscordSequenceModal
        from src.handlers.input_handler import InputHandler

        handler = InputHandler()
        # No session → handle_sequence_input returns False
        adapter = MagicMock()
        adapter.platform = "discord"
        modal = DiscordSequenceModal(
            title="Input Sequence",
            preferred_mapping="ULDR AB ST",
            chat_id=100,
            message_id=42,
            user_id=999,
            user_name="Alice",
            adapter=adapter,
            handler=handler,
        )
        modal.mapping_select = MagicMock()
        modal.mapping_select.values = ["ULDR AB ST"]
        modal.sequence_input = MagicMock()
        modal.sequence_input.value = "UU"

        interaction = self._make_interaction()

        with patch("src.adapters.discord.state_manager") as mock_sm, \
             patch("src.handlers.input_handler.state_manager") as mock_ih_sm, \
             patch("src.handlers.input_handler.is_media_only_mirror", return_value=False), \
             patch("src.handlers.input_handler.get_leader_chat_id", return_value=100):
            mock_sm.set_user_preference = MagicMock()
            mock_ih_sm.load_game_state.return_value = None
            await modal.on_submit(interaction)

        mock_sm.set_user_preference.assert_not_called()
        # But an error response must still be sent
        interaction.response.send_message.assert_awaited_once()

    def test_modal_items_are_labels_wrapping_select_and_textinput(self):
        """Both top-level items added to the modal are discord.ui.Label instances."""
        import discord
        modal = self._make_modal()
        labels = [item for item in modal.children if isinstance(item, discord.ui.Label)]
        assert len(labels) == 2, f"Expected 2 Label items, got {len(labels)}"
        components = [label.component for label in labels]
        assert any(isinstance(c, discord.ui.Select) for c in components), "No Select component found"
        assert any(isinstance(c, discord.ui.TextInput) for c in components), "No TextInput component found"
        # .mapping_select and .sequence_input attributes must be the inner components
        select_label = next(l for l in labels if isinstance(l.component, discord.ui.Select))
        textinput_label = next(l for l in labels if isinstance(l.component, discord.ui.TextInput))
        assert select_label.component is modal.mapping_select
        assert textinput_label.component is modal.sequence_input


def _make_sequence_button_interaction(channel_id: int = 100, user_id: int = 999) -> MagicMock:
    """Build a component interaction for the open_sequence_modal button."""
    import discord
    interaction = MagicMock()
    interaction.channel_id = channel_id
    interaction.type = discord.InteractionType.component
    interaction.data = {"custom_id": "open_sequence_modal"}
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    user = MagicMock()
    user.id = user_id
    user.display_name = "Alice"
    interaction.user = user
    message = MagicMock()
    message.id = 42
    interaction.message = message
    return interaction


class TestOnInteractionOpenSequenceModal:

    def _get_on_interaction(self, bot):
        listeners = bot.extra_events.get("on_interaction", [])
        assert listeners
        return listeners[0]

    @pytest.mark.asyncio
    async def test_send_modal_called_for_open_sequence_modal(self):
        """on_interaction calls send_modal when custom_id is open_sequence_modal."""
        from src.handlers.discord_handler import create_discord_bot

        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = False

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.DiscordAdapter"), \
             patch("src.handlers.discord_handler.DiscordSequenceModal") as mock_modal_cls:
            mock_settings.allowed_chat_ids = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_sm.get_user_preference = MagicMock(return_value=None)

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_sequence_button_interaction()

            await on_interaction(interaction)

        interaction.response.send_modal.assert_awaited_once_with(mock_modal_cls.return_value)

    @pytest.mark.asyncio
    async def test_maintenance_mode_blocks_sequence_modal(self):
        """Maintenance mode prevents modal from opening for non-admins."""
        from src.handlers.discord_handler import create_discord_bot

        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = True

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.DiscordAdapter") as mock_adapter_cls:
            mock_settings.allowed_chat_ids = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            # `_get_discord_adapter()` falls back to DiscordAdapter(bot) → mock_adapter_cls(bot)
            # so the returned adapter is mock_adapter_cls.return_value (not a separate mock_adapter)
            mock_adapter_cls.return_value.is_admin = AsyncMock(return_value=False)

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_sequence_button_interaction()

            await on_interaction(interaction)

        interaction.response.send_modal.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preferred_mapping_loaded_from_db(self):
        """Preferred mapping is fetched from state_manager and passed to modal."""
        from src.handlers.discord_handler import create_discord_bot

        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = False

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.DiscordAdapter"), \
             patch("src.handlers.discord_handler.DiscordSequenceModal") as mock_modal_cls:
            mock_settings.allowed_chat_ids = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_sm.get_user_preference = MagicMock(return_value="WASD ZX CV")

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_sequence_button_interaction(user_id=999)

            await on_interaction(interaction)

        _, kwargs = mock_modal_cls.call_args
        assert kwargs.get("preferred_mapping") == "WASD ZX CV"

    @pytest.mark.asyncio
    async def test_default_mapping_used_when_no_preference(self):
        """Falls back to 'ULDR AB ST' when no preference stored."""
        from src.handlers.discord_handler import create_discord_bot

        config = MagicMock()
        config.platform = "discord"
        config.maintenance_mode = False

        with patch("src.handlers.discord_handler.settings") as mock_settings, \
             patch("src.handlers.discord_handler.state_manager") as mock_sm, \
             patch("src.handlers.discord_handler.DiscordAdapter"), \
             patch("src.handlers.discord_handler.DiscordSequenceModal") as mock_modal_cls:
            mock_settings.allowed_chat_ids = []
            mock_sm.get_or_create_chat_config.return_value = config
            mock_sm.save_chat_config = MagicMock()
            mock_sm.get_user_preference = MagicMock(return_value=None)  # no preference

            bot = create_discord_bot()
            on_interaction = self._get_on_interaction(bot)
            interaction = _make_sequence_button_interaction()

            await on_interaction(interaction)

        _, kwargs = mock_modal_cls.call_args
        assert kwargs.get("preferred_mapping") == "ULDR AB ST"

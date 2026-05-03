"""Integration tests for i18n functionality."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variables before importing
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
os.environ["WEBHOOK_URL"] = "https://test.example.com"
os.environ["WEBHOOK_SECRET"] = "test_secret_1234567890"

from src.db.manager import DatabaseManager
from src.models.game_state import ChatConfig
from src.i18n.translation_manager import TranslationManager
from src.handlers.commands import language_command


@pytest.fixture
def db_manager(tmp_path):
    """Create a DatabaseManager with temporary database."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def translation_manager():
    """Create a fresh TranslationManager."""
    return TranslationManager()


class TestI18nEndToEnd:
    """End-to-end integration tests for i18n."""

    def test_translation_manager_with_database_integration(self, db_manager, translation_manager):
        """Test that TranslationManager correctly reads language from database."""
        # Save chat config with English
        config = ChatConfig(chat_id=123, language="en-US")
        db_manager.save_chat_config(config)

        # Mock state_manager to use our db_manager
        with patch('src.utils.state_manager.state_manager', db_manager):
            # Get translation - should use en-US
            result = translation_manager.get("commands.save.success", chat_id=123, slot=1)

            # Result should be in English
            assert "saved" in result.lower() or "slot" in result.lower()
            assert "1" in result

    def test_language_cache_invalidation_flow(self, db_manager, translation_manager):
        """Test complete cache invalidation flow."""
        # Setup: pt-BR initially
        config = ChatConfig(chat_id=456, language="pt-BR")
        db_manager.save_chat_config(config)

        with patch('src.utils.state_manager.state_manager', db_manager):
            # First call - caches pt-BR
            result1 = translation_manager.get("commands.save.success", chat_id=456, slot=1)
            assert translation_manager._language_cache[456] == "pt-BR"

            # Change language in database
            config.language = "en-US"
            db_manager.save_chat_config(config)

            # Without cache invalidation, should still return pt-BR
            result2 = translation_manager.get("commands.save.success", chat_id=456, slot=1)
            assert result1 == result2  # Same because of cache

            # Invalidate cache
            translation_manager.invalidate_cache(456)

            # Now should return en-US
            result3 = translation_manager.get("commands.save.success", chat_id=456, slot=1)
            assert translation_manager._language_cache[456] == "en-US"
            assert result1 != result3  # Different languages

    def test_language_fallback_chain(self, db_manager, translation_manager):
        """Test complete fallback chain: config -> settings -> hardcoded."""
        with patch('src.utils.state_manager.state_manager', db_manager):
            # No config in database
            assert db_manager.load_chat_config(999) is None

            with patch('src.config.settings') as mock_settings:
                mock_settings.default_language = "pt-BR"

                # Should fall back to settings default
                result = translation_manager.get("commands.save.success", chat_id=999, slot=1)
                assert translation_manager._language_cache[999] == "pt-BR"

    def test_multiple_chats_different_languages(self, db_manager, translation_manager):
        """Test that multiple chats can have different languages simultaneously."""
        # Chat 1: pt-BR
        config1 = ChatConfig(chat_id=111, language="pt-BR")
        db_manager.save_chat_config(config1)

        # Chat 2: en-US
        config2 = ChatConfig(chat_id=222, language="en-US")
        db_manager.save_chat_config(config2)

        # Chat 3: None (should use default)
        config3 = ChatConfig(chat_id=333, language=None)
        db_manager.save_chat_config(config3)

        with patch('src.utils.state_manager.state_manager', db_manager):
            with patch('src.config.settings') as mock_settings:
                mock_settings.default_language = "pt-BR"

                # Get same translation for all chats
                result1 = translation_manager.get("commands.save.success", chat_id=111, slot=1)
                result2 = translation_manager.get("commands.save.success", chat_id=222, slot=1)
                result3 = translation_manager.get("commands.save.success", chat_id=333, slot=1)

                # Chat 1 and 3 should be same (both pt-BR), chat 2 different
                assert result1 == result3
                assert result1 != result2

    @pytest.mark.asyncio
    async def test_language_command_changes_language_and_invalidates_cache(self, db_manager):
        """Test /language command end-to-end."""
        from src.adapters.base import CommandContext

        # Setup
        config = ChatConfig(chat_id=123, language="pt-BR")
        db_manager.save_chat_config(config)

        # Create mock adapter and CommandContext
        mock_adapter = MagicMock()
        mock_adapter.send_text = AsyncMock()
        mock_adapter.is_admin = AsyncMock(return_value=True)

        ctx = CommandContext(
            chat_id=123,
            user_id=456,
            user_name="TestUser",
            args=["en-US"],
            adapter=mock_adapter,
            raw=None,
        )

        # Patch dependencies
        with patch('src.handlers.commands.state_manager', db_manager):
            with patch('src.handlers.commands.settings') as mock_settings:
                mock_settings.allowed_chat_ids = []

                with patch('src.handlers.commands.translation_manager') as mock_tm:
                    mock_tm.get.return_value = "✅ Language changed to en-US!"

                    # Execute command
                    await language_command(ctx)

                    # Verify config was updated
                    loaded = db_manager.load_chat_config(123)
                    assert loaded.language == "en-US"

                    # Verify cache was invalidated
                    mock_tm.invalidate_cache.assert_called_once_with(123)

    def test_translation_persistence_across_manager_instances(self, db_manager):
        """Test that language preference persists across TranslationManager instances."""
        # Save config with language
        config = ChatConfig(chat_id=789, language="en-US")
        db_manager.save_chat_config(config)

        with patch('src.utils.state_manager.state_manager', db_manager):
            # First manager instance
            manager1 = TranslationManager()
            result1 = manager1.get("commands.save.success", chat_id=789, slot=1)

            # Second manager instance (simulates restart)
            manager2 = TranslationManager()
            result2 = manager2.get("commands.save.success", chat_id=789, slot=1)

            # Both should return same (en-US) translation
            assert result1 == result2
            assert "saved" in result1.lower()

    def test_keyboard_text_changes_with_language(self):
        """Test that keyboard button labels change based on language."""
        from src.keyboard import create_input_keyboard
        from src.i18n.translation_manager import translation_manager as tm_instance
        from src.models.game_state import ChatConfig
        from src.game_modifier_buttons.pkpcrystal import MODIFIER_BUTTONS

        # Create keyboard for pt-BR chat
        with patch.object(tm_instance, '_resolve_language') as mock_resolve:
            mock_resolve.return_value = "pt-BR"
            config_pt = ChatConfig(chat_id=111, modifier_states={"run": True})
            keyboard_pt = create_input_keyboard(chat_config=config_pt, modifier_specs=MODIFIER_BUTTONS)

        # Create keyboard for en-US chat
        with patch.object(tm_instance, '_resolve_language') as mock_resolve:
            mock_resolve.return_value = "en-US"
            config_en = ChatConfig(chat_id=222, modifier_states={"run": True})
            keyboard_en = create_input_keyboard(chat_config=config_en, modifier_specs=MODIFIER_BUTTONS)

        # Keyboards should have the same structure but different text
        assert len(keyboard_pt.inline_keyboard) == len(keyboard_en.inline_keyboard)

    def test_game_message_text_changes_with_language(self):
        """Test that game message text changes based on language."""
        from src.keyboard import create_game_message_text
        from src.i18n.translation_manager import translation_manager as tm_instance

        # Get message for pt-BR chat (no queue)
        with patch.object(tm_instance, '_resolve_language') as mock_resolve:
            mock_resolve.return_value = "pt-BR"
            msg_pt = create_game_message_text(chat_id=111)

        # Get message for en-US chat (no queue)
        with patch.object(tm_instance, '_resolve_language') as mock_resolve:
            mock_resolve.return_value = "en-US"
            msg_en = create_game_message_text(chat_id=222)

        # Messages should be different
        assert msg_pt != msg_en

    def test_error_messages_use_correct_language(self, db_manager):
        """Test that error messages respect chat language setting."""
        # Setup chat with en-US
        config = ChatConfig(chat_id=555, language="en-US")
        db_manager.save_chat_config(config)

        with patch('src.utils.state_manager.state_manager', db_manager):
            manager = TranslationManager()

            # Get error message
            error = manager.get("permissions.admin_only", chat_id=555)

            # Should be in English
            assert "administrator" in error.lower() or "admin" in error.lower()

    def test_command_messages_use_correct_language_after_switch(self, db_manager):
        """Test that command messages use correct language after language switch."""
        # Start with pt-BR
        config = ChatConfig(chat_id=666, language="pt-BR")
        db_manager.save_chat_config(config)

        with patch('src.utils.state_manager.state_manager', db_manager):
            manager = TranslationManager()

            # Get message in pt-BR
            msg_pt = manager.get("commands.save.success", chat_id=666, slot=1)

            # Switch to en-US
            config.language = "en-US"
            db_manager.save_chat_config(config)
            manager.invalidate_cache(666)

            # Get message in en-US
            msg_en = manager.get("commands.save.success", chat_id=666, slot=1)

            # Should be different
            assert msg_pt != msg_en

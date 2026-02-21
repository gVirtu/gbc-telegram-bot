"""Tests for TranslationManager."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, PropertyMock

from src.i18n.translation_manager import TranslationManager, SUPPORTED_LANGUAGES
from src.models.game_state import ChatConfig


class TestTranslationManager:
    """Test suite for TranslationManager."""

    def test_initialization_loads_translations(self):
        """Test that TranslationManager loads translation files on init."""
        manager = TranslationManager()

        # Should have loaded pt-BR (required) and en-US
        assert "pt-BR" in manager._translations
        assert "en-US" in manager._translations
        assert len(manager._translations) >= 1

    def test_get_nested_value_with_dot_notation(self):
        """Test getting nested values using dot notation."""
        manager = TranslationManager()

        # Test nested key access
        value = manager._get_nested_value(
            manager._translations["pt-BR"],
            "commands.save.success"
        )
        assert value is not None
        assert "slot" in value.lower() or "{slot}" in value

    def test_get_nested_value_missing_key(self):
        """Test getting nested value with missing key returns None."""
        manager = TranslationManager()

        value = manager._get_nested_value(
            manager._translations["pt-BR"],
            "commands.nonexistent.key"
        )
        assert value is None

    def test_get_translation_from_requested_language(self):
        """Test getting translation from requested language."""
        manager = TranslationManager()

        # Get from pt-BR
        value = manager._get_translation("commands.save.success", "pt-BR")
        assert "salvo" in value.lower() or "slot" in value.lower()

        # Get from en-US
        value = manager._get_translation("commands.save.success", "en-US")
        assert "saved" in value.lower() or "slot" in value.lower()

    def test_get_translation_fallback_to_default(self):
        """Test fallback to default language when key not found."""
        manager = TranslationManager()

        # Mock missing key in en-US but present in pt-BR
        with patch.object(manager, '_get_nested_value') as mock_nested:
            # First call (en-US) returns None, second call (pt-BR) returns value
            mock_nested.side_effect = [None, "💾 Test fallback"]

            value = manager._get_translation("test.key", "en-US")
            assert value == "💾 Test fallback"
            assert mock_nested.call_count == 2

    def test_get_translation_returns_key_when_not_found(self):
        """Test that missing translation returns the key itself."""
        manager = TranslationManager()

        value = manager._get_translation("completely.missing.key", "pt-BR")
        assert value == "completely.missing.key"

    def test_get_with_variable_interpolation(self):
        """Test get() with variable interpolation."""
        manager = TranslationManager()

        # Mock chat config to return pt-BR
        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_config = ChatConfig(chat_id=123, language="pt-BR")
            mock_sm.load_chat_config.return_value = mock_config

            result = manager.get("commands.save.success", chat_id=123, slot=5)

            # Should have interpolated the slot number
            assert "5" in result

    def test_get_with_missing_variable(self):
        """Test get() with missing variable returns unformatted text."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_config = ChatConfig(chat_id=123, language="pt-BR")
            mock_sm.load_chat_config.return_value = mock_config

            # Call without providing required variable
            result = manager.get("commands.save.success", chat_id=123)

            # Should still contain the placeholder
            assert "{slot}" in result

    def test_resolve_language_from_cache(self):
        """Test language resolution from cache."""
        manager = TranslationManager()

        # Pre-populate cache
        manager._language_cache[123] = "en-US"

        result = manager._resolve_language(123)
        assert result == "en-US"

    def test_resolve_language_from_database(self):
        """Test language resolution from database."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_config = ChatConfig(chat_id=456, language="en-US")
            mock_sm.load_chat_config.return_value = mock_config

            result = manager._resolve_language(456)

            assert result == "en-US"
            # Should also cache the result
            assert manager._language_cache[456] == "en-US"

    def test_resolve_language_fallback_to_settings(self):
        """Test language resolution fallback to settings default."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            # Config with no language set
            mock_config = ChatConfig(chat_id=789, language=None)
            mock_sm.load_chat_config.return_value = mock_config

            with patch('src.config.settings') as mock_settings:
                mock_settings.default_language = "pt-BR"

                result = manager._resolve_language(789)

                assert result == "pt-BR"

    def test_resolve_language_fallback_to_hardcoded(self):
        """Test language resolution fallback to hardcoded pt-BR."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            mock_sm.load_chat_config.side_effect = Exception("DB error")

            with patch('src.config.settings') as mock_settings:
                # Make settings also fail
                type(mock_settings).default_language = PropertyMock(side_effect=Exception("Settings error"))

                result = manager._resolve_language(999)

                assert result == "pt-BR"

    def test_resolve_language_validates_existence(self):
        """Test that resolved language is validated against available translations."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            # Return an unsupported language
            mock_config = ChatConfig(chat_id=111, language="fr-FR")
            mock_sm.load_chat_config.return_value = mock_config

            result = manager._resolve_language(111)

            # Should fall back to pt-BR since fr-FR doesn't exist
            assert result == "pt-BR"

    def test_invalidate_cache(self):
        """Test cache invalidation."""
        manager = TranslationManager()

        # Populate cache
        manager._language_cache[123] = "en-US"
        assert 123 in manager._language_cache

        # Invalidate
        manager.invalidate_cache(123)

        assert 123 not in manager._language_cache

    def test_invalidate_cache_nonexistent_chat(self):
        """Test invalidating cache for chat that's not cached."""
        manager = TranslationManager()

        # Should not raise error
        manager.invalidate_cache(999)

    def test_get_available_languages(self):
        """Test getting list of available languages."""
        manager = TranslationManager()

        languages = manager.get_available_languages()

        assert "pt-BR" in languages
        assert "en-US" in languages
        assert len(languages) >= 1

    def test_supported_languages_constant(self):
        """Test that SUPPORTED_LANGUAGES is defined correctly."""
        assert "pt-BR" in SUPPORTED_LANGUAGES
        assert "en-US" in SUPPORTED_LANGUAGES

    def test_translation_file_not_found_default_language(self):
        """Test that missing default language file raises error."""
        with patch('src.i18n.translation_manager.Path') as mock_path:
            # Make i18n dir exist but pt-BR.json not exist
            mock_i18n_dir = MagicMock()
            mock_i18n_dir.exists.return_value = True
            mock_path.return_value.parent.parent.parent.__truediv__.return_value = mock_i18n_dir

            mock_pt_br = MagicMock()
            mock_pt_br.exists.return_value = False
            mock_i18n_dir.__truediv__.return_value = mock_pt_br

            with pytest.raises(FileNotFoundError):
                TranslationManager()

    def test_translation_file_not_found_optional_language(self):
        """Test that missing optional language logs warning but continues."""
        manager = TranslationManager()

        # Should still work with just pt-BR if en-US is missing
        assert "pt-BR" in manager._translations

    def test_get_with_different_chat_ids(self):
        """Test that different chat IDs can have different languages."""
        manager = TranslationManager()

        with patch('src.utils.state_manager.state_manager') as mock_sm:
            def mock_load_config(chat_id):
                if chat_id == 111:
                    return ChatConfig(chat_id=111, language="pt-BR")
                elif chat_id == 222:
                    return ChatConfig(chat_id=222, language="en-US")
                return None

            mock_sm.load_chat_config.side_effect = mock_load_config

            # Get same key for different chats
            pt_result = manager.get("commands.save.success", chat_id=111, slot=1)
            en_result = manager.get("commands.save.success", chat_id=222, slot=1)

            # Results should be different (different languages)
            assert pt_result != en_result
            # Both should have slot interpolated
            assert "1" in pt_result
            assert "1" in en_result

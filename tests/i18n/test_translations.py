"""Tests for translation file validation."""

import json
import pytest
from pathlib import Path


class TestTranslationFiles:
    """Test suite for validating translation files."""

    @pytest.fixture
    def i18n_dir(self):
        """Get i18n directory path."""
        return Path(__file__).parent.parent.parent / "i18n"

    @pytest.fixture
    def pt_br_translations(self, i18n_dir):
        """Load pt-BR translations."""
        with open(i18n_dir / "pt-BR.json", "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def en_us_translations(self, i18n_dir):
        """Load en-US translations."""
        with open(i18n_dir / "en-US.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def test_translation_files_exist(self, i18n_dir):
        """Test that required translation files exist."""
        assert (i18n_dir / "pt-BR.json").exists()
        assert (i18n_dir / "en-US.json").exists()

    def test_translation_files_valid_json(self, pt_br_translations, en_us_translations):
        """Test that translation files are valid JSON."""
        # If we got here, JSON parsing succeeded
        assert isinstance(pt_br_translations, dict)
        assert isinstance(en_us_translations, dict)

    def test_translation_files_not_empty(self, pt_br_translations, en_us_translations):
        """Test that translation files are not empty."""
        assert len(pt_br_translations) > 0
        assert len(en_us_translations) > 0

    def _get_all_keys(self, obj, prefix=""):
        """Recursively get all keys from nested dict."""
        keys = []
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.extend(self._get_all_keys(value, full_key))
            else:
                keys.append(full_key)
        return keys

    def test_translation_files_have_same_keys(self, pt_br_translations, en_us_translations):
        """Test that both translation files have the same key structure."""
        pt_keys = set(self._get_all_keys(pt_br_translations))
        en_keys = set(self._get_all_keys(en_us_translations))

        missing_in_en = pt_keys - en_keys
        missing_in_pt = en_keys - pt_keys

        assert not missing_in_en, f"Keys in pt-BR but not in en-US: {missing_in_en}"
        assert not missing_in_pt, f"Keys in en-US but not in pt-BR: {missing_in_pt}"

    def _get_placeholders(self, text):
        """Extract placeholders from a format string."""
        import re
        return set(re.findall(r'\{(\w+)\}', text))

    def _get_all_text_with_keys(self, obj, prefix=""):
        """Get all text values with their keys."""
        items = []
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                items.extend(self._get_all_text_with_keys(value, full_key))
            else:
                items.append((full_key, value))
        return items

    def test_translation_placeholders_match(self, pt_br_translations, en_us_translations):
        """Test that placeholders in translated strings match."""
        pt_items = dict(self._get_all_text_with_keys(pt_br_translations))
        en_items = dict(self._get_all_text_with_keys(en_us_translations))

        mismatches = []
        for key in pt_items.keys():
            pt_placeholders = self._get_placeholders(pt_items[key])
            en_placeholders = self._get_placeholders(en_items[key])

            if pt_placeholders != en_placeholders:
                mismatches.append({
                    "key": key,
                    "pt_placeholders": pt_placeholders,
                    "en_placeholders": en_placeholders
                })

        assert not mismatches, f"Placeholder mismatches: {mismatches}"

    def test_required_keys_exist(self, pt_br_translations, en_us_translations):
        """Test that required translation keys exist."""
        required_keys = [
            "commands.save.success",
            "commands.load.success",
            "commands.language.current",
            "commands.language.changed",
            "commands.language.invalid",
            "permissions.admin_only",
            "permissions.chat_not_allowed",
            "game.no_active_game",
            "game.default_message",
        ]

        pt_all_keys = self._get_all_keys(pt_br_translations)
        en_all_keys = self._get_all_keys(en_us_translations)

        for key in required_keys:
            assert key in pt_all_keys, f"Missing required key in pt-BR: {key}"
            assert key in en_all_keys, f"Missing required key in en-US: {key}"

    def test_no_empty_strings(self, pt_br_translations, en_us_translations):
        """Test that no translation strings are empty."""
        pt_items = self._get_all_text_with_keys(pt_br_translations)
        en_items = self._get_all_text_with_keys(en_us_translations)

        empty_pt = [key for key, value in pt_items if not value or not value.strip()]
        empty_en = [key for key, value in en_items if not value or not value.strip()]

        assert not empty_pt, f"Empty strings in pt-BR: {empty_pt}"
        assert not empty_en, f"Empty strings in en-US: {empty_en}"

    def test_translation_structure_consistency(self, pt_br_translations, en_us_translations):
        """Test that translation files have consistent top-level structure."""
        assert set(pt_br_translations.keys()) == set(en_us_translations.keys())

        # Check that major sections exist
        expected_sections = ["commands", "permissions", "game", "keyboard"]
        for section in expected_sections:
            assert section in pt_br_translations
            assert section in en_us_translations

    def test_command_translations_exist(self, pt_br_translations, en_us_translations):
        """Test that all command translations exist."""
        commands = [
            "start_game",
            "resume",
            "reboot",
            "save",
            "load",
            "status",
            "print",
            "recap",
            "message",
            "language",
            "maintenance",
            "unknown"
        ]

        for cmd in commands:
            assert cmd in pt_br_translations["commands"], f"Missing command in pt-BR: {cmd}"
            assert cmd in en_us_translations["commands"], f"Missing command in en-US: {cmd}"

    def test_language_command_has_all_messages(self, pt_br_translations, en_us_translations):
        """Test that language command has all required messages."""
        required_messages = ["current", "available", "usage", "changed", "invalid", "admin_only"]

        for msg in required_messages:
            assert msg in pt_br_translations["commands"]["language"]
            assert msg in en_us_translations["commands"]["language"]

    def test_keyboard_section_exists(self, pt_br_translations, en_us_translations):
        """Test that keyboard section has required translations."""
        assert "buttons" in pt_br_translations["keyboard"]
        assert "buttons" in en_us_translations["keyboard"]

        # Check for running/walking button translations
        assert "running" in pt_br_translations["keyboard"]["buttons"]
        assert "walking" in pt_br_translations["keyboard"]["buttons"]
        assert "running" in en_us_translations["keyboard"]["buttons"]
        assert "walking" in en_us_translations["keyboard"]["buttons"]

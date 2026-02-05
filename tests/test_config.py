"""Tests for configuration module.

This module tests the Settings class including validation, defaults,
and helper methods.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings


class TestRequiredSettings:
    """Test required settings validation."""
    
    def test_telegram_bot_token_required(self):
        """Test that telegram_bot_token is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                webhook_url="https://example.com",
                webhook_secret="test_secret_1234567890",
            )
        assert "telegram_bot_token" in str(exc_info.value)
    
    def test_webhook_url_required(self):
        """Test that webhook_url is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token="test_token",
                webhook_secret="test_secret_1234567890",
            )
        assert "webhook_url" in str(exc_info.value)
    
    def test_webhook_secret_required(self):
        """Test that webhook_secret is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token="test_token",
                webhook_url="https://example.com",
            )
        assert "webhook_secret" in str(exc_info.value)
    
    def test_webhook_secret_minimum_length(self):
        """Test that webhook_secret must be at least 16 characters."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token="test_token",
                webhook_url="https://example.com",
                webhook_secret="short_secret",
            )
        assert "webhook_secret" in str(exc_info.value)


class TestOptionalSettingsDefaults:
    """Test optional settings have correct defaults."""
    
    @pytest.fixture
    def valid_settings(self, tmp_path):
        """Create valid settings with temporary paths."""
        # Create dummy ROM file
        rom_path = tmp_path / "pokemon_red.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        return Settings(
            telegram_bot_token="test_token",
            webhook_url="https://example.com",
            webhook_secret="test_secret_1234567890",
            rom_path=rom_path,
            data_dir=tmp_path / "data",
        )
    
    def test_port_default(self, valid_settings):
        """Test port defaults to 8000."""
        assert valid_settings.port == 8000
    
    def test_log_level_default(self, valid_settings):
        """Test log_level defaults to INFO."""
        assert valid_settings.log_level == "INFO"
    
    def test_input_hold_frames_default(self, valid_settings):
        """Test input_hold_frames defaults to 30."""
        assert valid_settings.input_hold_frames == 30
    
    def test_animation_duration_default(self, valid_settings):
        """Test animation_duration defaults to 10."""
        assert valid_settings.animation_duration == 10
    
    def test_animation_interval_default(self, valid_settings):
        """Test animation_interval defaults to 1.0."""
        assert valid_settings.animation_interval == 1.0
    
    def test_animation_tick_frames_default(self, valid_settings):
        """Test animation_tick_frames defaults to 60."""
        assert valid_settings.animation_tick_frames == 60
    
    def test_auto_save_interval_default(self, valid_settings):
        """Test auto_save_interval defaults to 300."""
        assert valid_settings.auto_save_interval == 300
    
    def test_save_slots_default(self, valid_settings):
        """Test save_slots defaults to 5."""
        assert valid_settings.save_slots == 5
    
    def test_max_retries_default(self, valid_settings):
        """Test max_retries defaults to 3."""
        assert valid_settings.max_retries == 3
    
    def test_retry_delay_default(self, valid_settings):
        """Test retry_delay defaults to 1.0."""
        assert valid_settings.retry_delay == 1.0


class TestSettingsValidation:
    """Test settings validation logic."""
    
    @pytest.fixture
    def base_settings(self, tmp_path):
        """Base settings dict with temporary paths."""
        rom_path = tmp_path / "pokemon_red.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        return {
            "telegram_bot_token": "test_token",
            "webhook_url": "https://example.com",
            "webhook_secret": "test_secret_1234567890",
            "rom_path": rom_path,
            "data_dir": tmp_path / "data",
        }
    
    def test_log_level_valid_values(self, base_settings):
        """Test that valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = Settings(**base_settings, log_level=level)
            assert settings.log_level == level
    
    def test_log_level_invalid_value(self, base_settings):
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, log_level="INVALID")
        assert "log_level" in str(exc_info.value)
    
    def test_port_validation(self, base_settings):
        """Test port must be between 1 and 65535."""
        # Valid port
        settings = Settings(**base_settings, port=8080)
        assert settings.port == 8080
        
        # Invalid port (too high)
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, port=70000)
        assert "port" in str(exc_info.value)
        
        # Invalid port (too low)
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, port=0)
        assert "port" in str(exc_info.value)
    
    def test_save_slots_validation(self, base_settings):
        """Test save_slots must be between 1 and 10."""
        # Valid
        settings = Settings(**base_settings, save_slots=3)
        assert settings.save_slots == 3
        
        # Too high
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, save_slots=15)
        assert "save_slots" in str(exc_info.value)
        
        # Too low
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, save_slots=0)
        assert "save_slots" in str(exc_info.value)
    
    def test_rom_path_must_exist(self, base_settings, tmp_path):
        """Test that ROM path must exist."""
        # Skip this test when running in test environment
        # The validation is skipped when PYTEST_CURRENT_TEST is set
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
            with pytest.raises(ValidationError) as exc_info:
                Settings(
                    **base_settings,
                    rom_path=tmp_path / "nonexistent.gbc",
                )
            assert "ROM file not found" in str(exc_info.value)
    
    def test_data_dir_created(self, base_settings, tmp_path):
        """Test that data directory is created if it doesn't exist."""
        data_dir = tmp_path / "new_data_dir"
        assert not data_dir.exists()
        
        settings = Settings(**base_settings, data_dir=data_dir)
        
        assert data_dir.exists()
        assert settings.data_dir == data_dir


class TestHelperMethods:
    """Test settings helper methods."""
    
    @pytest.fixture
    def settings(self, tmp_path):
        """Create settings with temporary paths."""
        rom_path = tmp_path / "pokemon_red.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        return Settings(
            telegram_bot_token="test_token",
            webhook_url="https://example.com",
            webhook_secret="my_secret_key_1234567890",
            data_dir=tmp_path / "data",
            rom_path=rom_path,
        )
    
    def test_get_webhook_path(self, settings):
        """Test webhook path generation."""
        webhook_path = settings.get_webhook_path()
        
        # Should start with /webhook/
        assert webhook_path.startswith("/webhook/")
        
        # Should contain a hash
        parts = webhook_path.split("/")
        assert len(parts) == 3
        assert len(parts[2]) == 16  # SHA256 hash truncated to 16 chars
    
    def test_get_webhook_path_consistency(self, settings):
        """Test webhook path is consistent for same secret."""
        path1 = settings.get_webhook_path()
        path2 = settings.get_webhook_path()
        assert path1 == path2
    
    def test_get_webhook_path_different_secrets(self, tmp_path):
        """Test different secrets produce different paths."""
        rom_path = tmp_path / "pokemon_red.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        settings1 = Settings(
            telegram_bot_token="test_token",
            webhook_url="https://example.com",
            webhook_secret="secret_one_12345678901",
            rom_path=rom_path,
        )
        settings2 = Settings(
            telegram_bot_token="test_token",
            webhook_url="https://example.com",
            webhook_secret="secret_two_12345678902",
            rom_path=rom_path,
        )
        
        assert settings1.get_webhook_path() != settings2.get_webhook_path()
    
    def test_get_chat_save_dir(self, settings):
        """Test chat save directory generation."""
        save_dir = settings.get_chat_save_dir(123456789)
        
        # Should be under data/saves/
        assert "saves" in str(save_dir)
        assert "123456789" in str(save_dir)
        
        # Should be created
        assert save_dir.exists()
    
    def test_get_chat_save_dir_different_chats(self, settings):
        """Test different chats get different directories."""
        dir1 = settings.get_chat_save_dir(111)
        dir2 = settings.get_chat_save_dir(222)
        
        assert dir1 != dir2
        assert "111" in str(dir1)
        assert "222" in str(dir2)
    
    def test_get_poll_file(self, settings):
        """Test poll file path generation."""
        poll_file = settings.get_poll_file(123456789)
        
        assert "polls" in str(poll_file)
        assert "123456789.json" in str(poll_file)
    
    def test_get_config_file(self, settings):
        """Test config file path generation."""
        config_file = settings.get_config_file(123456789)
        
        assert "config" in str(config_file)
        assert "123456789.json" in str(config_file)


class TestEnvironmentLoading:
    """Test loading settings from environment variables."""
    
    def test_load_from_environment(self, tmp_path, monkeypatch):
        """Test settings load from environment variables."""
        # Create dummy ROM
        rom_path = tmp_path / "pokemon.gbc"
        rom_path.write_bytes(b"rom")
        
        # Set environment variables
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://env.example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "env_secret_1234567890")
        monkeypatch.setenv("ROM_PATH", str(rom_path))
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "env_data"))
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        
        # Need to clear cache to get fresh instance
        get_settings.cache_clear()
        
        # Import fresh to avoid cached module
        import importlib
        from src import config
        importlib.reload(config)
        
        settings = config.Settings()  # Create directly to avoid cache
        
        assert settings.telegram_bot_token.get_secret_value() == "env_token"
        assert str(settings.webhook_url) == "https://env.example.com/"
        assert settings.port == 9000
        assert settings.log_level == "DEBUG"


class TestSingleton:
    """Test settings singleton behavior."""
    
    def test_get_settings_cached(self, tmp_path):
        """Test that get_settings returns cached instance."""
        # Clear cache first
        get_settings.cache_clear()
        
        rom_path = tmp_path / "pokemon_red.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        # Mock Settings to avoid needing env vars
        with patch("src.config.Settings") as mock_settings:
            mock_instance = mock_settings.return_value
            
            # First call
            settings1 = get_settings()
            # Second call should return cached
            settings2 = get_settings()
            
            # Settings should only be instantiated once
            assert mock_settings.call_count == 1
            assert settings1 is settings2


class TestPathValidation:
    """Test path validation and resolution."""
    
    def test_rom_path_expanded(self, tmp_path):
        """Test that ~ in paths is expanded."""
        rom_path = tmp_path / "rom.gbc"
        rom_path.write_bytes(b"rom")
        
        # Can't easily test ~ expansion without mocking, but we can test it's resolved
        settings = Settings(
            telegram_bot_token="test",
            webhook_url="https://example.com",
            webhook_secret="test_secret_1234567890",
            rom_path=Path("./relative/path.gbc"),
            data_dir=tmp_path / "data",
        )
        
        # Path should be resolved to absolute
        assert settings.rom_path.is_absolute()
    
    def test_data_dir_absolute(self, tmp_path):
        """Test that data_dir is converted to absolute path."""
        rom_path = tmp_path / "rom.gbc"
        rom_path.write_bytes(b"rom")
        
        settings = Settings(
            telegram_bot_token="test",
            webhook_url="https://example.com",
            webhook_secret="test_secret_1234567890",
            rom_path=rom_path,
            data_dir=Path("./relative/data"),
        )
        
        assert settings.data_dir.is_absolute()

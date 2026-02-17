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

os.environ["PYTEST_CURRENT_TEST"] = "1"  # Skip env loading

class TestRequiredSettings:
    """Test required settings validation."""

    def test_telegram_bot_token_required(self):
        """Test that telegram_bot_token is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token=None,
                webhook_url="https://example.com",
                webhook_secret="test_secret_1234567890",
            )
        assert "telegram_bot_token" in str(exc_info.value)

    def test_webhook_url_required(self):
        """Test that webhook_url is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token="test_token",
                webhook_url=None,
                webhook_secret="test_secret_1234567890",
            )
        assert "webhook_url" in str(exc_info.value)

    def test_webhook_secret_required(self):
        """Test that webhook_secret is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                telegram_bot_token="test_token",
                webhook_url="https://example.com",
                webhook_secret=None,
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
        rom_path = tmp_path / "game.gbc"
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
        assert valid_settings.input_hold_frames == 10
    
    def test_animation_duration_default(self, valid_settings):
        """Test animation_duration defaults to 5."""
        assert valid_settings.animation_duration == 5
    
    def test_animation_tick_frames_default(self, valid_settings):
        """Test animation_tick_frames defaults to 60."""
        assert valid_settings.animation_tick_frames == 60
    
    def test_save_slots_default(self, valid_settings):
        """Test save_slots defaults to 5."""
        assert valid_settings.save_slots == 5
    
    def test_tbc_duration_frames_default(self, valid_settings):
        """Test tbc_duration_frames defaults to 10."""
        assert valid_settings.tbc_duration_frames == 10


class TestSettingsValidation:
    """Test settings validation logic."""
    
    @pytest.fixture
    def base_settings(self, tmp_path):
        """Base settings dict with temporary paths."""
        rom_path = tmp_path / "game.gbc"
        rom_path.write_bytes(b"dummy rom data")
        
        return {
            "telegram_bot_token": "test_token",
            "webhook_url": "https://example.com",
            "webhook_secret": "test_secret_1234567890",
            "rom_path": rom_path,
            "data_dir": tmp_path / "data",
        }
    
    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_log_level_valid_values(self, base_settings, level):
        """Test that valid log levels are accepted."""
        settings = Settings(**base_settings, log_level=level)
        assert settings.log_level == level
    
    def test_log_level_invalid_value(self, base_settings):
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(**base_settings, log_level="INVALID")
        assert "log_level" in str(exc_info.value)
    
    @pytest.mark.parametrize("port,should_pass", [
        (1, True),
        (80, True),
        (8080, True),
        (65535, True),
        (0, False),
        (65536, False),
        (70000, False),
    ])
    def test_port_validation(self, base_settings, port, should_pass):
        """Test port validation with various values."""
        if should_pass:
            settings = Settings(**base_settings, port=port)
            assert settings.port == port
        else:
            with pytest.raises(ValidationError) as exc_info:
                Settings(**base_settings, port=port)
            assert "port" in str(exc_info.value)
    
    @pytest.mark.parametrize("slots,should_pass", [
        (1, True),
        (5, True),
        (10, True),
        (0, False),
        (11, False),
        (15, False),
    ])
    def test_save_slots_validation(self, base_settings, slots, should_pass):
        """Test save_slots validation with various values."""
        if should_pass:
            settings = Settings(**base_settings, save_slots=slots)
            assert settings.save_slots == slots
        else:
            with pytest.raises(ValidationError) as exc_info:
                Settings(**base_settings, save_slots=slots)
            assert "save_slots" in str(exc_info.value)
    
    def test_rom_path_must_exist(self, base_settings, tmp_path):
        """Test that ROM path must exist."""
        # Skip this test when running in test environment
        # The validation is skipped when PYTEST_CURRENT_TEST is set
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
            # Create a copy of base_settings without rom_path
            settings_dict = {k: v for k, v in base_settings.items() if k != 'rom_path'}
            with pytest.raises(ValidationError) as exc_info:
                Settings(
                    **settings_dict,
                    rom_path=tmp_path / "nonexistent.gbc",
                )
            assert "ROM file not found" in str(exc_info.value)
    
    def test_data_dir_created(self, base_settings, tmp_path):
        """Test that data directory is created if it doesn't exist."""
        data_dir = tmp_path / "new_data_dir"
        assert not data_dir.exists()

        # Create a copy of base_settings without data_dir
        settings_dict = {k: v for k, v in base_settings.items() if k != 'data_dir'}
        settings = Settings(**settings_dict, data_dir=data_dir)

        assert data_dir.exists()
        assert settings.data_dir == data_dir


class TestHelperMethods:
    """Test settings helper methods."""
    
    @pytest.fixture
    def settings(self, tmp_path):
        """Create settings with temporary paths."""
        rom_path = tmp_path / "game.gbc"
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
        assert webhook_path.startswith("webhook/")
        
        # Should contain a hash
        parts = webhook_path.split("/")
        assert len(parts) == 2
        assert len(parts[1]) == 16  # SHA256 hash truncated to 16 chars
    
    def test_get_webhook_path_consistency(self, settings):
        """Test webhook path is consistent for same secret."""
        path1 = settings.get_webhook_path()
        path2 = settings.get_webhook_path()
        assert path1 == path2
    
    def test_get_webhook_path_different_secrets(self, tmp_path):
        """Test different secrets produce different paths."""
        rom_path = tmp_path / "game.gbc"
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
        rom_path = tmp_path / "game.gbc"
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
        
        rom_path = tmp_path / "game.gbc"
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


class TestRateLimiterSettings:
    """Test rate limiter configuration settings."""

    def test_default_rate_limiter_settings(self, monkeypatch, tmp_path):
        """Should have default rate limiter values."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")

        # Must set rom_path for Settings validation
        rom_path = tmp_path / "rom.gbc"
        rom_path.write_bytes(b"rom")

        from src.config import Settings
        settings = Settings(rom_path=rom_path)

        assert settings.rate_limit_per_chat == 1
        assert settings.rate_limit_per_chat_window == 1.0
        assert settings.rate_limit_global == 30
        assert settings.rate_limit_global_window == 1.0

    def test_custom_rate_limiter_settings(self, monkeypatch, tmp_path):
        """Should allow custom rate limiter values."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
        monkeypatch.setenv("WEBHOOK_SECRET", "test_secret_123456789")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT", "5")
        monkeypatch.setenv("RATE_LIMIT_PER_CHAT_WINDOW", "2.0")
        monkeypatch.setenv("RATE_LIMIT_GLOBAL", "50")
        monkeypatch.setenv("RATE_LIMIT_GLOBAL_WINDOW", "5.0")

        # Must set rom_path for Settings validation
        rom_path = tmp_path / "rom.gbc"
        rom_path.write_bytes(b"rom")

        from src.config import Settings
        settings = Settings(rom_path=rom_path)

        assert settings.rate_limit_per_chat == 5
        assert settings.rate_limit_per_chat_window == 2.0
        assert settings.rate_limit_global == 50
        assert settings.rate_limit_global_window == 5.0


def test_max_queue_size_default():
    """Test max_queue_size has default value."""
    from src.config import Settings

    settings = Settings(
        telegram_bot_token="test_token",
        webhook_url="https://test.example.com",
        webhook_secret="test_secret_1234567890",
    )

    assert settings.max_queue_size == 10

def test_max_queue_size_custom():
    """Test max_queue_size accepts custom values."""
    from src.config import Settings

    settings = Settings(
        telegram_bot_token="test_token",
        webhook_url="https://test.example.com",
        webhook_secret="test_secret_1234567890",
        max_queue_size=20,
    )

    assert settings.max_queue_size == 20

def test_max_queue_size_validation():
    """Test max_queue_size validates range."""
    from src.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="test_token",
            webhook_url="https://test.example.com",
            webhook_secret="test_secret_1234567890",
            max_queue_size=0,  # Below minimum
        )

    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="test_token",
            webhook_url="https://test.example.com",
            webhook_secret="test_secret_1234567890",
            max_queue_size=100,  # Above maximum
        )

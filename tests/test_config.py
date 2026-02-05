"""Tests for configuration module."""

import os
import hashlib
from pathlib import Path
import pytest
from pydantic import ValidationError


class TestSettingsRequired:
    """Test required settings validation."""

    def test_telegram_bot_token_required(self):
        """Test that telegram_bot_token is required."""
        from src.config import Settings
        
        # Clear any existing env vars
        for key in ['TELEGRAM_BOT_TOKEN', 'WEBHOOK_URL', 'WEBHOOK_SECRET']:
            os.environ.pop(key, None)
        
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        
        assert 'telegram_bot_token' in str(exc_info.value)

    def test_webhook_url_required(self):
        """Test that webhook_url is required."""
        from src.config import Settings
        
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ.pop('WEBHOOK_URL', None)
        os.environ.pop('WEBHOOK_SECRET', None)
        
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        
        assert 'webhook_url' in str(exc_info.value)

    def test_webhook_secret_required(self):
        """Test that webhook_secret is required."""
        from src.config import Settings
        
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ.pop('WEBHOOK_SECRET', None)
        
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        
        assert 'webhook_secret' in str(exc_info.value)


class TestSettingsOptionalDefaults:
    """Test optional settings with defaults."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield
        # Cleanup is handled by individual tests

    def test_port_default(self):
        """Test default port value."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.port == 8000

    def test_rom_path_default(self):
        """Test default rom_path value."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.rom_path == Path("./roms/pokemon_red.gbc")

    def test_data_dir_default(self):
        """Test default data_dir value."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.data_dir == Path("./data")

    def test_initial_save_path_default(self):
        """Test default initial_save_path value."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.initial_save_path == Path("./roms/initial.state")

    def test_log_level_default(self):
        """Test default log_level value."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.log_level == "INFO"


class TestGameTimingSettings:
    """Test game timing settings defaults."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_input_hold_frames_default(self):
        """Test default input_hold_frames."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.input_hold_frames == 30

    def test_animation_duration_default(self):
        """Test default animation_duration."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.animation_duration == 10

    def test_animation_interval_default(self):
        """Test default animation_interval."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.animation_interval == 1.0

    def test_animation_tick_frames_default(self):
        """Test default animation_tick_frames."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.animation_tick_frames == 60

    def test_auto_save_interval_default(self):
        """Test default auto_save_interval."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.auto_save_interval == 300

    def test_save_slots_default(self):
        """Test default save_slots."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.save_slots == 5


class TestTelegramSettings:
    """Test Telegram settings defaults."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_max_retries_default(self):
        """Test default max_retries."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.max_retries == 3

    def test_retry_delay_default(self):
        """Test default retry_delay."""
        from src.config import Settings
        
        settings = Settings()
        assert settings.retry_delay == 1.0


class TestSettingsFromEnv:
    """Test loading settings from environment variables."""

    def test_custom_port_from_env(self):
        """Test loading custom port from environment."""
        from src.config import Settings
        
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        os.environ['PORT'] = '9000'
        
        settings = Settings()
        assert settings.port == 9000

    def test_custom_log_level_from_env(self):
        """Test loading custom log_level from environment."""
        from src.config import Settings
        
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        os.environ['LOG_LEVEL'] = 'DEBUG'
        
        settings = Settings()
        assert settings.log_level == 'DEBUG'

    def test_custom_rom_path_from_env(self):
        """Test loading custom rom_path from environment."""
        from src.config import Settings
        
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        os.environ['ROM_PATH'] = './roms/pokemon_red.gbc'  # Use existing file
        
        settings = Settings()
        assert settings.rom_path == Path('./roms/pokemon_red.gbc')


class TestSettingsValidation:
    """Test settings validation."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_invalid_log_level_rejected(self):
        """Test that invalid log levels are rejected."""
        from src.config import Settings
        
        os.environ['LOG_LEVEL'] = 'INVALID'
        
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        
        assert 'log_level' in str(exc_info.value)

    def test_rom_path_must_exist(self):
        """Test that rom_path must exist."""
        from src.config import Settings
        
        # Clear any previous LOG_LEVEL setting and set invalid rom_path
        os.environ.pop('LOG_LEVEL', None)
        os.environ['ROM_PATH'] = '/nonexistent/path/rom.gbc'
        
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        
        error_msg = str(exc_info.value).lower()
        assert 'rom' in error_msg or 'exist' in error_msg or 'not found' in error_msg

    def test_valid_log_levels_accepted(self):
        """Test that all valid log levels are accepted."""
        from src.config import Settings
        
        # Ensure we use default rom path that exists
        os.environ.pop('ROM_PATH', None)
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        
        for level in valid_levels:
            os.environ['LOG_LEVEL'] = level
            # Should not raise
            settings = Settings()
            assert settings.log_level == level


class TestHelperMethods:
    """Test helper methods."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_get_webhook_path(self):
        """Test get_webhook_path returns correct format."""
        from src.config import Settings
        
        settings = Settings()
        webhook_path = settings.get_webhook_path()
        
        assert webhook_path.startswith('/webhook/')
        # The path should contain a hash of the secret
        secret_hash = hashlib.sha256('test_secret'.encode()).hexdigest()[:16]
        expected_path = f'/webhook/{secret_hash}'
        assert webhook_path == expected_path

    def test_get_chat_save_dir(self):
        """Test get_chat_save_dir returns correct path."""
        from src.config import Settings
        
        settings = Settings()
        chat_id = 12345
        save_dir = settings.get_chat_save_dir(chat_id)
        
        expected = Path('./data/saves/12345')
        assert save_dir == expected

    def test_get_chat_save_dir_different_chat_ids(self):
        """Test get_chat_save_dir with different chat IDs."""
        from src.config import Settings
        
        settings = Settings()
        
        test_cases = [
            (12345, Path('./data/saves/12345')),
            (67890, Path('./data/saves/67890')),
            (-1, Path('./data/saves/-1')),
        ]
        
        for chat_id, expected in test_cases:
            assert settings.get_chat_save_dir(chat_id) == expected


class TestSingletonInstance:
    """Test singleton instance."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_settings_singleton_exists(self):
        """Test that settings singleton is created."""
        from src.config import settings
        
        assert settings is not None
        assert hasattr(settings, 'telegram_bot_token')
        assert hasattr(settings, 'webhook_url')
        assert hasattr(settings, 'webhook_secret')

    def test_telegram_token_is_secretstr(self):
        """Test that telegram_bot_token is SecretStr type."""
        from src.config import settings
        from pydantic import SecretStr
        
        assert isinstance(settings.telegram_bot_token, SecretStr)
        assert settings.telegram_bot_token.get_secret_value() == 'test_token'

    def test_webhook_url_is_parsed(self):
        """Test that webhook_url is properly parsed as HttpUrl."""
        from src.config import settings
        
        assert str(settings.webhook_url) == 'https://example.com/webhook'


class TestDataDirCreation:
    """Test data directory creation."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up required environment variables."""
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['WEBHOOK_URL'] = 'https://example.com/webhook'
        os.environ['WEBHOOK_SECRET'] = 'test_secret'
        yield

    def test_data_dir_created_if_not_exists(self, tmp_path):
        """Test that data_dir is created if it doesn't exist."""
        from src.config import Settings
        
        new_data_dir = tmp_path / "new_data"
        os.environ['DATA_DIR'] = str(new_data_dir)
        
        assert not new_data_dir.exists()
        
        # Should create the directory during validation
        settings = Settings()
        
        assert new_data_dir.exists()
        assert new_data_dir.is_dir()

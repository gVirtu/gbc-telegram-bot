"""Configuration management using Pydantic Settings.

This module provides centralized configuration management with environment variable
support, type validation, and sensible defaults for the Telegram GBC Bot.
"""

import os
import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support.
    
    All settings can be configured via environment variables. Required settings
    must be provided, while optional settings use sensible defaults.
    
    Example:
        >>> from src.config import settings
        >>> print(settings.port)
        8000
        >>> webhook_path = settings.get_webhook_path()
    """
    
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
    
    # Required settings
    telegram_bot_token: SecretStr = Field(
        ...,
        description="Telegram bot token from @BotFather",
    )
    webhook_url: HttpUrl = Field(
        ...,
        description="Public URL for webhook endpoint (e.g., https://example.com)",
    )
    webhook_secret: str = Field(
        ...,
        description="Secret token for webhook validation",
        min_length=16,
    )
    
    # Server settings
    port: int = Field(
        default=8000,
        description="Server port to listen on",
        ge=1,
        le=65535,
    )
    
    # Game file paths
    rom_path: Path = Field(
        default=Path("./roms/game.gbc"),
        description="Path to GBC ROM file",
    )
    sym_path: Path | None = Field(
        default=None,
        description="Path to GBC ROM symbol file",
    )
    data_dir: Path = Field(
        default=Path("./data"),
        description="Directory for data storage (saves, config, polls)",
    )
    
    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )

    # Internationalization
    default_language: str = Field(
        default="en-US",
        description="Default language code for bot messages (e.g., 'pt-BR', 'en-US')",
    )

    # Game timing settings
    input_hold_frames: int = Field(
        default=10,
        description="Number of frames to hold button input (30 = 0.5s @ 60fps)",
        ge=1,
    )
    animation_duration: int = Field(
        default=5,
        description="Animation phase duration in seconds",
        ge=1,
    )
    tbc_overlay_path: Path = Field(
        default=Path("./assets/to_be_continued.png"),
        description="Path to To Be Continued overlay image",
    )
    tbc_duration_frames: int = Field(
        default=10,
        description="Number of frames for the 'To Be Continued' end sequence",
        ge=5,
        le=60,
    )
    timelapse_frame_skip: int = Field(
        default=20,
        description="Keep 1 out of N frames for timelapse (higher = faster timelapse, smaller file)",
        ge=1,
        le=60,
    )
    timelapse_backoff_delays: str = Field(
        default="1,2,4",
        description="Comma-separated list of delays in seconds for timelapse retries (empty = no retries)",
    )
    save_slots: int = Field(
        default=5,
        description="Number of rotating save slots",
        ge=1,
        le=10,
    )
    backup_hour: int = Field(
        default=0,
        ge=0,
        le=23,
        description="Hour (UTC) to run daily backup (BACKUP_HOUR env var)",
    )
    backup_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute (UTC) to run daily backup (BACKUP_MINUTE env var)",
    )
    backup_retention_days: int = Field(
        default=30,
        ge=1,
        description="Days to keep backups before purging (BACKUP_RETENTION_DAYS env var)",
    )

    # Sequence input settings
    max_sequence_length: int = Field(
        default=6,
        description="Maximum number of buttons in a sequence",
        ge=1,
        le=10,
    )
    sequence_delay_seconds: float = Field(
        default=1.0,
        description="Delay in seconds between button presses in a sequence",
        ge=0.1,
        le=5.0,
    )
    max_queue_size: int = Field(
        default=10,
        description="Maximum number of items in the input queue",
        ge=1,
        le=50,
    )

    # Rate limiter settings
    rate_limit_per_chat: int = Field(
        default=1,
        description="Maximum messages per chat within the window",
        ge=1,
        le=100,
    )
    rate_limit_per_chat_window: float = Field(
        default=1.0,
        description="Time window in seconds for per-chat rate limit",
        ge=0.1,
        le=60.0,
    )
    rate_limit_global: int = Field(
        default=30,
        description="Maximum messages globally across all chats within the window",
        ge=1,
        le=1000,
    )
    rate_limit_global_window: float = Field(
        default=1.0,
        description="Time window in seconds for global rate limit",
        ge=0.1,
        le=60.0,
    )

    allowed_chat_ids: str = Field(
        default="",
        description="Comma-separated list of allowed Telegram chat IDs (empty = allow all)",
    )
    
    @field_validator("rom_path")
    @classmethod
    def validate_rom_path(cls, v: Path) -> Path:
        """Validate that ROM paths are absolute or relative to working directory."""
        return v.expanduser().resolve()
    
    @field_validator("sym_path")
    @classmethod
    def validate_sym_path(cls, v: Path | None) -> Path | None:
        """Validate that SYM paths are absolute or relative to working directory."""
        return None if v is None else v.expanduser().resolve()
    
    @field_validator("data_dir")
    @classmethod
    def validate_data_dir(cls, v: Path) -> Path:
        """Ensure data directory exists or create it."""
        v = v.expanduser().resolve()
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @field_validator("timelapse_backoff_delays")
    @classmethod
    def parse_timelapse_backoff_delays(cls, v: str) -> list[int]:
        """Parse comma-separated delays into a list of integers."""
        if not v:
            return []
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    
    @field_validator("allowed_chat_ids")
    @classmethod
    def parse_allowed_chat_ids(cls, v: str) -> list[int]:
        """Parse comma-separated chat IDs into a list of integers."""
        if not v:
            return []
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    
    @model_validator(mode="after")
    def validate_rom_exists(self) -> "Settings":
        """Validate that ROM file exists if not in testing mode."""
        # Skip validation if we're in a test environment without ROM
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return self
            
        if not self.rom_path.exists():
            raise ValueError(
                f"ROM file not found: {self.rom_path}. "
                "Please provide a valid ROM file path."
            )
        if self.sym_path is not None and not self.sym_path.exists():
            raise ValueError(
                f"SYM file not found: {self.sym_path}. "
                "Please provide a valid SYM file path."
            )

        return self
    
    def get_webhook_hash(self) -> str:
        return hashlib.sha256(self.webhook_secret.encode()).hexdigest()[:16]
    
    def get_webhook_path(self) -> str:
        """Generate webhook path with hashed secret.
        
        Returns:
            Webhook path in format /webhook/{hash}
            
        Example:
            >>> settings.get_webhook_path()
            '/webhook/a1b2c3d4e5f67890'
        """
        return f"webhook/{self.get_webhook_hash()}"
    
    def get_chat_save_dir(self, chat_id: int) -> Path:
        """Get save directory for a specific chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            Path to chat's save directory (created if doesn't exist)
            
        Example:
            >>> settings.get_chat_save_dir(123456789)
            PosixPath('/path/to/data/saves/123456789')
        """
        save_dir = self.data_dir / "saves" / str(chat_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir
    
    def get_chat_backup_dir(self, chat_id: int) -> Path:
        """Get backup directory for a specific chat.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Path to chat's backup directory (created if doesn't exist)
        """
        backup_dir = self.data_dir / "backups" / str(chat_id)
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def get_config_file(self, chat_id: int) -> Path:
        """Get config file path for a specific chat.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            Path to chat's config file
        """
        config_dir = self.data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / f"{chat_id}.json"
    
    def setup_logging(self) -> None:
        """Configure logging with the specified level."""
        logging.basicConfig(
            level=getattr(logging, self.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.
    
    Using lru_cache ensures we only create one Settings instance,
    which is important for performance and consistency.
    
    Returns:
        Settings instance
    """
    return Settings()


class _SettingsProxy:
    """Proxy class for lazy settings access.
    
    This allows importing 'settings' without triggering instantiation
    at import time. Settings are only created when first accessed.
    """
    
    _instance: Settings | None = None
    
    def _get_instance(self) -> Settings:
        if self._instance is None:
            self._instance = get_settings()
        return self._instance
    
    def __getattr__(self, name: str) -> any:
        return getattr(self._get_instance(), name)
    
    def __setattr__(self, name: str, value: any) -> None:
        if name == "_instance":
            super().__setattr__(name, value)
        else:
            setattr(self._get_instance(), name, value)


# Singleton proxy for import convenience
settings = _SettingsProxy()

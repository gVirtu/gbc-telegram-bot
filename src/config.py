"""Configuration module using Pydantic Settings.

This module provides centralized configuration management for the Telegram
Pokémon Red Bot using Pydantic Settings for environment variable validation.
"""

import hashlib
import os
from pathlib import Path
from typing import Any

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    This class uses Pydantic Settings to automatically load and validate
    configuration from environment variables. Required settings must be
    provided via environment variables, while optional settings have sensible
    defaults.
    
    Example:
        from src.config import settings
        
        print(settings.telegram_bot_token.get_secret_value())
        print(settings.port)
        webhook_path = settings.get_webhook_path()
    
    Attributes:
        telegram_bot_token: Bot token from @BotFather (required)
        webhook_url: Public URL for webhook endpoint (required)
        webhook_secret: Secret for webhook validation (required)
        port: Server port (default: 8000)
        rom_path: Path to ROM file (default: ./roms/pokemon_red.gbc)
        data_dir: Data storage directory (default: ./data)
        initial_save_path: Initial save state path (default: ./roms/initial.state)
        log_level: Logging level (default: INFO)
        input_hold_frames: Frames to hold button (default: 30)
        animation_duration: Animation phase duration in seconds (default: 10)
        animation_interval: Seconds between frame updates (default: 1.0)
        animation_tick_frames: Frames to tick between updates (default: 60)
        auto_save_interval: Auto-save interval in seconds (default: 300)
        save_slots: Number of rotating save slots (default: 5)
        max_retries: Max API retry attempts (default: 3)
        retry_delay: Seconds between retries (default: 1.0)
    """
    
    # Required settings (no defaults)
    telegram_bot_token: SecretStr = Field(
        ...,
        description="Bot token from @BotFather"
    )
    webhook_url: HttpUrl = Field(
        ...,
        description="Public URL for webhook endpoint"
    )
    webhook_secret: str = Field(
        ...,
        description="Secret for webhook validation"
    )
    
    # Optional settings with defaults
    port: int = Field(
        default=8000,
        description="Server port"
    )
    rom_path: Path = Field(
        default=Path("./roms/pokemon_red.gbc"),
        description="Path to ROM file"
    )
    data_dir: Path = Field(
        default=Path("./data"),
        description="Data storage directory"
    )
    initial_save_path: Path = Field(
        default=Path("./roms/initial.state"),
        description="Initial save state path"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    
    # Game timing settings
    input_hold_frames: int = Field(
        default=30,
        description="Frames to hold button (0.5s @ 60fps)"
    )
    animation_duration: int = Field(
        default=10,
        description="Animation phase duration in seconds"
    )
    animation_interval: float = Field(
        default=1.0,
        description="Seconds between frame updates"
    )
    animation_tick_frames: int = Field(
        default=60,
        description="Frames to tick between updates"
    )
    auto_save_interval: int = Field(
        default=300,
        description="Auto-save interval in seconds"
    )
    save_slots: int = Field(
        default=5,
        description="Number of rotating save slots"
    )
    
    # Telegram settings
    max_retries: int = Field(
        default=3,
        description="Max API retry attempts"
    )
    retry_delay: float = Field(
        default=1.0,
        description="Seconds between retries"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        """Validate settings after initial parsing.
        
        Performs the following validations:
        - Checks that log_level is one of the valid levels
        - Validates that rom_path exists
        - Creates data_dir if it doesn't exist
        
        Returns:
            Self for method chaining
            
        Raises:
            ValidationError: If any validation fails
        """
        # Validate log_level
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {self.log_level}. "
                f"Must be one of: {', '.join(sorted(valid_levels))}"
            )
        
        # Validate rom_path exists
        if not self.rom_path.exists():
            raise ValueError(
                f"ROM file not found: {self.rom_path}. "
                f"Please ensure the ROM file exists at the specified path."
            )
        
        # Create data_dir if it doesn't exist
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        
        return self
    
    def get_webhook_path(self) -> str:
        """Generate webhook path with hashed secret.
        
        Creates a unique webhook path by hashing the webhook secret
        using SHA-256 and taking the first 16 characters of the hex digest.
        
        Returns:
            Webhook path in format /webhook/{hashed_secret}
            
        Example:
            >>> settings.get_webhook_path()
            '/webhook/a1b2c3d4e5f67890'
        """
        secret_hash = hashlib.sha256(self.webhook_secret.encode()).hexdigest()[:16]
        return f"/webhook/{secret_hash}"
    
    def get_chat_save_dir(self, chat_id: int) -> Path:
        """Get the save directory for a specific chat.
        
        Constructs a path for storing save states for a particular
        Telegram chat, creating the directory structure if needed.
        
        Args:
            chat_id: The Telegram chat ID
            
        Returns:
            Path to the chat's save directory
            
        Example:
            >>> settings.get_chat_save_dir(12345)
            PosixPath('data/saves/12345')
        """
        save_dir = self.data_dir / "saves" / str(chat_id)
        if not save_dir.exists():
            save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir


# Lazy-loaded singleton instance
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Get or create the singleton settings instance.
    
    This function implements lazy initialization of the settings
    singleton, allowing the module to be imported without requiring
    environment variables to be set immediately.
    
    Returns:
        The Settings singleton instance
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


# Module-level singleton (lazy-loaded via property-like access)
class _SettingsProxy:
    """Proxy class to provide attribute access to lazy-loaded settings."""
    
    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_settings(), name, value)
    
    def __repr__(self) -> str:
        return repr(get_settings())


settings: Settings = _SettingsProxy()  # type: ignore[assignment]

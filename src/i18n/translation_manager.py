"""Translation manager for internationalization support.

This module provides a singleton TranslationManager that loads translation
files and provides methods to retrieve translated strings with variable
interpolation and fallback support.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES = ["pt-BR", "en-US"]


class TranslationManager:
    """Manages translations for the bot.

    Loads translation files from i18n/ directory and provides methods to
    retrieve translated strings with variable interpolation.

    Features:
    - Loads all translation files at startup
    - Caches resolved language per chat_id
    - Supports nested keys via dot notation (e.g., "commands.save.success")
    - Variable interpolation using Python's .format(**kwargs)
    - Fallback chain: requested language → default language → key itself

    Example:
        >>> t = TranslationManager()
        >>> t.get("commands.save.success", chat_id=123, slot=1)
        "💾 Jogo salvo no slot 1!"
    """

    def __init__(self):
        """Initialize the translation manager."""
        self._translations: Dict[str, Dict] = {}
        self._language_cache: Dict[int, str] = {}  # chat_id -> language code
        self._load_translations()

    def _load_translations(self) -> None:
        """Load all translation files from i18n/ directory.

        Raises:
            FileNotFoundError: If pt-BR.json (default language) is not found
        """
        # Get i18n directory path (relative to this file's parent)
        i18n_dir = Path(__file__).parent.parent.parent / "i18n"

        if not i18n_dir.exists():
            logger.error(f"i18n directory not found: {i18n_dir}")
            raise FileNotFoundError(f"i18n directory not found: {i18n_dir}")

        # Load each supported language
        for language in SUPPORTED_LANGUAGES:
            file_path = i18n_dir / f"{language}.json"

            if not file_path.exists():
                if language == "pt-BR":
                    # pt-BR is critical (default language)
                    logger.error(f"Default language file not found: {file_path}")
                    raise FileNotFoundError(f"Default language file not found: {file_path}")
                else:
                    # Other languages can be missing
                    logger.warning(f"Translation file not found: {file_path}")
                    continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self._translations[language] = json.load(f)
                logger.info(f"Loaded translations for {language}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse translation file {file_path}: {e}")
                if language == "pt-BR":
                    raise

        logger.info(f"Translation manager initialized with languages: {list(self._translations.keys())}")

    def _resolve_language(self, chat_id: int) -> str:
        """Resolve language for a chat with caching.

        Resolution order:
        1. Check cache
        2. Load from database (ChatConfig)
        3. Fall back to settings.default_language
        4. Fall back to hardcoded "pt-BR"

        Args:
            chat_id: Telegram chat ID

        Returns:
            Language code (e.g., "pt-BR", "en-US")
        """
        # Check cache first
        if chat_id in self._language_cache:
            return self._language_cache[chat_id]

        # Try to load from database
        language = None
        try:
            # Import here to avoid circular dependency
            from src.utils.state_manager import state_manager
            config = state_manager.load_chat_config(chat_id)
            if config and config.language:
                language = config.language
                logger.debug(f"Loaded language {language} from config for chat {chat_id}")
        except Exception as e:
            logger.debug(f"Failed to load language from config for chat {chat_id}: {e}")

        # Fall back to settings default
        if not language:
            try:
                from src.config import settings
                language = settings.default_language
                logger.debug(f"Using default language {language} for chat {chat_id}")
            except Exception as e:
                logger.warning(f"Failed to load default language from settings: {e}")
                language = "pt-BR"  # Hardcoded fallback

        # Validate language exists
        if language not in self._translations:
            logger.warning(f"Language {language} not found, falling back to pt-BR")
            language = "pt-BR"

        # Cache the result
        self._language_cache[chat_id] = language

        return language

    def _get_nested_value(self, data: Dict, key: str) -> Optional[str]:
        """Get nested value from dict using dot notation.

        Args:
            data: Dictionary to search
            key: Dot-separated key (e.g., "commands.save.success")

        Returns:
            Value if found, None otherwise

        Example:
            >>> data = {"commands": {"save": {"success": "Saved!"}}}
            >>> _get_nested_value(data, "commands.save.success")
            "Saved!"
        """
        parts = key.split(".")
        current = data

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current if isinstance(current, str) else None

    def _get_translation(self, key: str, language: str) -> str:
        """Get translation for key, with fallback to default language.

        Args:
            key: Translation key (e.g., "commands.save.success")
            language: Language code (e.g., "pt-BR")

        Returns:
            Translated string, or key itself if not found
        """
        # Try requested language
        if language in self._translations:
            value = self._get_nested_value(self._translations[language], key)
            if value is not None:
                return value
            else:
                logger.warning(f"Translation key '{key}' not found in language '{language}'")

        # Fall back to default language (pt-BR)
        if language != "pt-BR" and "pt-BR" in self._translations:
            value = self._get_nested_value(self._translations["pt-BR"], key)
            if value is not None:
                logger.debug(f"Using fallback translation for key '{key}'")
                return value

        # Last resort: return the key itself
        logger.error(f"Translation key '{key}' not found in any language")
        return key

    def get(self, key: str, chat_id: int, **kwargs) -> str:
        """Get translated string with optional variable interpolation.

        Args:
            key: Translation key (e.g., "commands.save.success")
            chat_id: Telegram chat ID (used to resolve language)
            **kwargs: Variables to interpolate into the string

        Returns:
            Translated and interpolated string

        Example:
            >>> t.get("commands.save.success", chat_id=123, slot=1)
            "💾 Jogo salvo no slot 1!"
        """
        # Resolve language for this chat
        language = self._resolve_language(chat_id)

        # Get translation
        text = self._get_translation(key, language)

        # Interpolate variables if provided
        if kwargs:
            try:
                return text.format(**kwargs)
            except KeyError as e:
                logger.error(f"Missing variable {e} for translation key '{key}'")
                return text  # Return unformatted text
            except Exception as e:
                logger.error(f"Failed to format translation '{key}': {e}")
                return text

        return text

    def invalidate_cache(self, chat_id: int) -> None:
        """Clear language cache for a chat.

        Call this after changing the language for a chat to force
        reloading from the database.

        Args:
            chat_id: Telegram chat ID
        """
        if chat_id in self._language_cache:
            del self._language_cache[chat_id]
            logger.debug(f"Invalidated language cache for chat {chat_id}")

    def get_available_languages(self) -> list[str]:
        """Get list of available language codes.

        Returns:
            List of language codes (e.g., ["pt-BR", "en-US"])
        """
        return list(self._translations.keys())


# Module-level singleton
translation_manager = TranslationManager()

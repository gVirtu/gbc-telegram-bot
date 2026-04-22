"""Game-specific shop extension registry.

Each file in this package calls register() at import time.
All files are auto-imported when this package is imported.
"""
from __future__ import annotations
import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shop.items import ShopCategory

_EXTENSIONS: dict[str, list[ShopCategory]] = {}


def register(game_id: str, categories: list[ShopCategory]) -> None:
    """Register game-specific shop categories for the given cartridge title."""
    _EXTENSIONS[game_id] = categories


def get_categories_for_game(game_id: str) -> list[ShopCategory]:
    """Return extra categories for the given cartridge title (empty list if none)."""
    return list(_EXTENSIONS.get(game_id, []))


def _load_all() -> None:
    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        importlib.import_module(f"src.game_shops.{module_info.name}")


_load_all()

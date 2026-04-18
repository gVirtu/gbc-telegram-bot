from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shop.items import ShopCategory, ShopItem


@dataclass
class SelectionOption:
    label: str   # display string — may be dynamic game content, not an i18n key
    value: str   # opaque; passed back as MakeSelection.value


@dataclass
class CategoryListScreen:
    categories: list[ShopCategory]
    page: int
    total_pages: int
    balance: int
    chat_id: int
    platform: str
    user_id: int
    status: str | None = None   # resolved string (not an i18n key)


@dataclass
class ItemListScreen:
    category: ShopCategory
    items: list[ShopItem]
    page: int
    total_pages: int
    balance: int
    chat_id: int
    platform: str
    user_id: int
    owned_items: frozenset[str] = field(default_factory=frozenset)
    status: str | None = None   # resolved string (not an i18n key)


@dataclass
class SelectionScreen:
    prompt: str   # resolved string (not an i18n key)
    options: list[SelectionOption]
    page: int
    total_pages: int
    chat_id: int


ShopScreen = CategoryListScreen | ItemListScreen | SelectionScreen

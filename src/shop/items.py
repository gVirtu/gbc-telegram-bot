"""Shop items for the points shop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShopItem:
    """A purchasable item in the points shop.

    Attributes:
        id: Unique identifier used in callback data.
        name_i18n_key: Translation key for the display name.
        cost: Point cost (0 = free).
        effect: Dict describing what changes on purchase.
            Currently supports: {"name_tag_color": "#RRGGBB"}
    """

    id: str
    name_i18n_key: str
    cost: int
    effect: dict


ITEMS_PER_PAGE: int = 3

SHOP_ITEMS: list[ShopItem] = [
    ShopItem("name_tag_white",   "shop.items.name_tag_white",   0,    {"name_tag_color": "#FFFFFF"}),
    ShopItem("name_tag_red",     "shop.items.name_tag_red",     5000, {"name_tag_color": "#FF0000"}),
    ShopItem("name_tag_green",   "shop.items.name_tag_green",   1, {"name_tag_color": "#00FF00"}),
    ShopItem("name_tag_blue",    "shop.items.name_tag_blue",    5000, {"name_tag_color": "#0000FF"}),
    ShopItem("name_tag_yellow",  "shop.items.name_tag_yellow",  5000, {"name_tag_color": "#FFFF00"}),
    ShopItem("name_tag_magenta", "shop.items.name_tag_magenta", 5000, {"name_tag_color": "#FF00FF"}),
    ShopItem("name_tag_cyan",    "shop.items.name_tag_cyan",    5000, {"name_tag_color": "#00FFFF"}),
    ShopItem("react_joy", "shop.items.react_joy", 1, {"reaction": "joy"}),
]

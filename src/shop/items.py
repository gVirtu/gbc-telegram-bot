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
    ShopItem("name_tag_green",   "shop.items.name_tag_green",   5000, {"name_tag_color": "#00FF00"}),
    ShopItem("name_tag_blue",    "shop.items.name_tag_blue",    5000, {"name_tag_color": "#0000FF"}),
    ShopItem("name_tag_yellow",  "shop.items.name_tag_yellow",  5000, {"name_tag_color": "#FFFF00"}),
    ShopItem("name_tag_magenta", "shop.items.name_tag_magenta", 5000, {"name_tag_color": "#FF00FF"}),
    ShopItem("name_tag_cyan",    "shop.items.name_tag_cyan",    5000, {"name_tag_color": "#00FFFF"}),
    ShopItem("react_joy", "shop.items.react_joy", 1, {"reaction": "joy"}),
    ShopItem("react_clap", "shop.items.react_clap", 1, {"reaction": "clap"}),
    ShopItem("react_clown", "shop.items.react_clown", 1, {"reaction": "clown"}),
    ShopItem("react_cry", "shop.items.react_cry", 1, {"reaction": "cry"}),
    ShopItem("react_eyes", "shop.items.react_eyes", 1, {"reaction": "eyes"}),
    ShopItem("react_fire", "shop.items.react_fire", 1, {"reaction": "fire"}),
    ShopItem("react_heart", "shop.items.react_heart", 1, {"reaction": "heart"}),
    ShopItem("react_mind_blown", "shop.items.react_mind_blown", 1, {"reaction": "mind_blown"}),
    ShopItem("react_moai", "shop.items.react_moai", 1, {"reaction": "moai"}),
    ShopItem("react_party_popper", "shop.items.react_party_popper", 1, {"reaction": "party_popper"}),
    ShopItem("react_pointing_down", "shop.items.react_pointing_down", 1, {"reaction": "pointing_down"}),
    ShopItem("react_pointing_left", "shop.items.react_pointing_left", 1, {"reaction": "pointing_left"}),
    ShopItem("react_pointing_right", "shop.items.react_pointing_right", 1, {"reaction": "pointing_right"}),
    ShopItem("react_pointing_up", "shop.items.react_pointing_up", 1, {"reaction": "pointing_up"}),
    ShopItem("react_poop", "shop.items.react_poop", 1, {"reaction": "poop"}),
    ShopItem("react_skull", "shop.items.react_skull", 1, {"reaction": "skull"}),
    ShopItem("react_sunglasses", "shop.items.react_sunglasses", 1, {"reaction": "sunglasses"}),
    ShopItem("react_thumbs_up", "shop.items.react_thumbs_up", 1, {"reaction": "thumbs_up"})
]

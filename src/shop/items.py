"""Shop items for the points shop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShopItem:
    """A purchasable item in the points shop.

    Attributes:
        id: Unique identifier used in callback data.
        name_i18n_key: Translation key for the display name.
        cost: Point cost (0 = free).
        effect: Dict describing what changes on purchase.
            Currently supports: {"name_tag_color": "#RRGGBB"} or {"reaction": "type"}
    """

    id: str
    name_i18n_key: str
    cost: int
    effect: dict
    one_time_purchase: bool = False


@dataclass
class ShopCategory:
    """A category of shop items.

    Attributes:
        id: Unique identifier used in callback data.
        label: i18n key for the display label.
        description: i18n key for the display description.
        items_per_page: How many items fit on one page.
        items_per_row: How many item buttons per keyboard row.
        items: The items in this category.
    """

    id: str
    label: str
    description: str
    items_per_page: int
    items_per_row: int
    items: list[ShopItem] = field(default_factory=list)


SHOP_CATEGORIES: list[ShopCategory] = [
    ShopCategory(
        id="name_tags",
        label="shop.categories.name_tags.label",
        description="shop.categories.name_tags.description",
        items_per_page=3,
        items_per_row=1,
        items=[
            ShopItem("name_tag_white",   "shop.items.name_tag_white",   0,    {"name_tag_color": "#FFFFFF"}, one_time_purchase=True),
            ShopItem("name_tag_red",     "shop.items.name_tag_red",     25000, {"name_tag_color": "#FF8888"}, one_time_purchase=True),
            ShopItem("name_tag_green",   "shop.items.name_tag_green",   25000, {"name_tag_color": "#88FF88"}, one_time_purchase=True),
            ShopItem("name_tag_blue",    "shop.items.name_tag_blue",    25000, {"name_tag_color": "#8888FF"}, one_time_purchase=True),
            ShopItem("name_tag_yellow",  "shop.items.name_tag_yellow",  25000, {"name_tag_color": "#FFFF88"}, one_time_purchase=True),
            ShopItem("name_tag_magenta", "shop.items.name_tag_magenta", 25000, {"name_tag_color": "#FF88FF"}, one_time_purchase=True),
            ShopItem("name_tag_cyan",    "shop.items.name_tag_cyan",    25000, {"name_tag_color": "#88FFFF"}, one_time_purchase=True),
        ],
    ),
    ShopCategory(
        id="reactions",
        label="shop.categories.reactions.label",
        description="shop.categories.reactions.description",
        items_per_page=18,
        items_per_row=6,
        items=[
            ShopItem("react_thumbs_up",      "shop.items.react_thumbs_up",      50, {"reaction": "thumbs_up"}),
            ShopItem("react_clap",           "shop.items.react_clap",           50, {"reaction": "clap"}),
            ShopItem("react_party_popper",   "shop.items.react_party_popper",   50, {"reaction": "party_popper"}),
            ShopItem("react_heart",          "shop.items.react_heart",          50, {"reaction": "heart"}),
            ShopItem("react_fire",           "shop.items.react_fire",           50, {"reaction": "fire"}),
            ShopItem("react_joy",            "shop.items.react_joy",            50, {"reaction": "joy"}),
            ShopItem("react_sunglasses",     "shop.items.react_sunglasses",     50, {"reaction": "sunglasses"}),
            ShopItem("react_mind_blown",     "shop.items.react_mind_blown",     50, {"reaction": "mind_blown"}),
            ShopItem("react_cry",            "shop.items.react_cry",            50, {"reaction": "cry"}),
            ShopItem("react_clown",          "shop.items.react_clown",          50, {"reaction": "clown"}),
            ShopItem("react_poop",           "shop.items.react_poop",           50, {"reaction": "poop"}),
            ShopItem("react_eyes",           "shop.items.react_eyes",           50, {"reaction": "eyes"}),
            ShopItem("react_pointing_up",    "shop.items.react_pointing_up",    50, {"reaction": "pointing_up"}),
            ShopItem("react_pointing_left",  "shop.items.react_pointing_left",  50, {"reaction": "pointing_left"}),
            ShopItem("react_pointing_right", "shop.items.react_pointing_right", 50, {"reaction": "pointing_right"}),
            ShopItem("react_pointing_down",  "shop.items.react_pointing_down",  50, {"reaction": "pointing_down"}),
            ShopItem("react_moai",           "shop.items.react_moai",           50, {"reaction": "moai"}),
            ShopItem("react_skull",          "shop.items.react_skull",          50, {"reaction": "skull"}),
        ],
    ),
]

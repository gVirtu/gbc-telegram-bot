from __future__ import annotations
from dataclasses import dataclass


@dataclass
class OpenShop:
    chat_id: int


@dataclass
class NavigateCategories:
    chat_id: int
    page: int


@dataclass
class NavigateCategoryItems:
    chat_id: int
    cat_id: str
    page: int


@dataclass
class BuyItem:
    chat_id: int
    item_id: str
    cat_id: str
    cat_page: int


@dataclass
class MakeSelection:
    chat_id: int
    value: str


@dataclass
class NavigateSelectionPage:
    chat_id: int
    page: int


@dataclass
class Cancel:
    chat_id: int


ShopAction = (
    OpenShop
    | NavigateCategories
    | NavigateCategoryItems
    | BuyItem
    | MakeSelection
    | NavigateSelectionPage
    | Cancel
)

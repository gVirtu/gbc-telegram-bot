# tests/test_shop_router.py
import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import math
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.shop.flow.actions import (
    OpenShop, NavigateCategories, NavigateCategoryItems,
    BuyItem, MakeSelection, NavigateSelectionPage, Cancel,
)
from src.shop.flow.screens import CategoryListScreen, ItemListScreen, SelectionScreen
from src.shop.flow.handlers import (
    PurchaseComplete, SelectionStep, FlowSession, ShopInteractionContext,
)
from src.shop.flow.screens import SelectionOption
from src.shop.items import ShopCategory, ShopItem


def _make_ctx(platform="telegram", user_id=1, user_name="Ash"):
    adapter = MagicMock()
    adapter.platform = platform
    return ShopInteractionContext(platform=platform, user_id=user_id, user_name=user_name, adapter=adapter)


def _make_category(cat_id="cats", items_per_page=3):
    return ShopCategory(
        id=cat_id,
        label=f"shop.{cat_id}.label",
        description=f"shop.{cat_id}.desc",
        items_per_page=items_per_page,
        items_per_row=1,
        items=[
            ShopItem(id=f"item_{i}", name_i18n_key=f"shop.item_{i}", cost=100, effect={})
            for i in range(5)
        ],
    )


@pytest.mark.asyncio
async def test_open_shop_returns_category_list_screen():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category()

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 5000
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_tm.get.return_value = ""

        screen = await router.handle(OpenShop(chat_id=100), ctx)

    assert isinstance(screen, CategoryListScreen)
    assert screen.balance == 5000
    assert screen.chat_id == 100
    assert screen.platform == "telegram"
    assert screen.user_id == 1
    assert screen.categories == [cat]
    assert screen.page == 0


@pytest.mark.asyncio
async def test_navigate_categories_returns_category_list_screen():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 0
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = []
        mock_tm.get.return_value = ""

        screen = await router.handle(NavigateCategories(chat_id=100, page=2), ctx)

    assert isinstance(screen, CategoryListScreen)
    assert screen.page == 2


@pytest.mark.asyncio
async def test_navigate_category_items_returns_item_list_screen():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="name_tags", items_per_page=3)

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 0
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_sm.get_owned_items.return_value = {"item_0"}
        mock_tm.get.return_value = ""

        screen = await router.handle(
            NavigateCategoryItems(chat_id=100, cat_id="name_tags", page=1), ctx
        )

    assert isinstance(screen, ItemListScreen)
    assert screen.category == cat
    assert screen.page == 1
    assert screen.total_pages == math.ceil(5 / 3)
    assert "item_0" in screen.owned_items


@pytest.mark.asyncio
async def test_navigate_category_items_unknown_cat_returns_category_list():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 0
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = []
        mock_tm.get.return_value = ""

        screen = await router.handle(
            NavigateCategoryItems(chat_id=100, cat_id="nonexistent", page=0), ctx
        )

    assert isinstance(screen, CategoryListScreen)

# tests/test_shop_router.py
import os
os.environ.setdefault("PYTEST_CURRENT_TEST", "1")

import math
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.shop.flow.actions import (
    OpenShop, NavigateCategories, NavigateCategoryItems,
    BuyItem, MakeSelection, Cancel,
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


@pytest.mark.asyncio
async def test_buy_item_success_returns_category_list_screen():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="name_tags", items_per_page=5)

    async def instant_success(purchase_ctx):
        return PurchaseComplete(success=True)

    cat.items[0].purchase_handler = instant_success

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 5000
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_tm.get.return_value = "ok"

        screen = await router.handle(
            BuyItem(chat_id=100, item_id="item_0", cat_id="name_tags", cat_page=0), ctx
        )

    assert isinstance(screen, CategoryListScreen)
    assert screen.status == "ok"


@pytest.mark.asyncio
async def test_buy_item_failure_returns_item_list_screen():
    from src.shop.flow.router import ShopRouter
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="name_tags", items_per_page=5)

    async def instant_fail(purchase_ctx):
        return PurchaseComplete(success=False, error_message="shop.insufficient_funds")

    cat.items[0].purchase_handler = instant_fail

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 0
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_sm.get_owned_items.return_value = set()
        mock_tm.get.return_value = "error msg"

        screen = await router.handle(
            BuyItem(chat_id=100, item_id="item_0", cat_id="name_tags", cat_page=0), ctx
        )

    assert isinstance(screen, ItemListScreen)
    assert screen.status == "error msg"
    assert screen.category == cat


@pytest.mark.asyncio
async def test_buy_unknown_item_returns_category_list_screen():
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
            BuyItem(chat_id=100, item_id="nonexistent", cat_id="cats", cat_page=0), ctx
        )

    assert isinstance(screen, CategoryListScreen)


@pytest.mark.asyncio
async def test_buy_item_returns_selection_screen_and_stores_session():
    from src.shop.flow.router import ShopRouter
    from src.shop.flow.session import get_session, clear_session
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="game_shop", items_per_page=5)

    async def multi_step_handler(purchase_ctx):
        return SelectionStep(
            prompt="shop.select_pokemon",
            options=[SelectionOption(label="pikachu", value="0")],
            per_page=6,
            on_select=AsyncMock(return_value=PurchaseComplete(success=True)),
        )

    cat.items[0].purchase_handler = multi_step_handler

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 1000
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        
        # Translates options first, then prompt
        mock_tm.get.side_effect = ["Pikachu", "Select a Pokémon"]

        screen = await router.handle(
            BuyItem(chat_id=100, item_id="item_0", cat_id="game_shop", cat_page=0), ctx
        )

    assert isinstance(screen, SelectionScreen)
    assert screen.prompt == "Select a Pokémon"
    assert screen.options[0].label == "Pikachu"

    # Session must be stored
    session = get_session("telegram", 1, 100)
    assert session is not None
    assert session.item.id == "item_0"
    clear_session("telegram", 1, 100)


@pytest.mark.asyncio
async def test_make_selection_final_step_returns_category_list():
    from src.shop.flow.router import ShopRouter
    from src.shop.flow.session import set_session, get_session
    from src.shop.flow.screens import SelectionOption
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="game_shop", items_per_page=5)
    item = cat.items[0]

    on_select = AsyncMock(return_value=PurchaseComplete(success=True))
    step = SelectionStep(
        prompt="shop.select_pokemon",
        options=[SelectionOption(label="Pikachu", value="0")],
        per_page=6,
        on_select=on_select,
    )
    session = FlowSession(item=item, cat_id="game_shop", cat_page=0, chat_id=100, step=step)
    set_session("telegram", 1, 100, session)

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 900
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_tm.get.return_value = "ok"

        screen = await router.handle(MakeSelection(chat_id=100, value="0"), ctx)

    assert isinstance(screen, CategoryListScreen)
    on_select.assert_awaited_once()
    # Session cleared
    assert get_session("telegram", 1, 100) is None


@pytest.mark.asyncio
async def test_make_selection_state_accumulates_across_steps():
    from src.shop.flow.router import ShopRouter
    from src.shop.flow.session import set_session
    from src.shop.flow.screens import SelectionOption
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="game_shop", items_per_page=5)
    item = cat.items[0]

    recorded_state = {}

    async def second_step(value: str, purchase_ctx):
        recorded_state.update(purchase_ctx.session.state)
        return PurchaseComplete(success=True)

    async def first_step(value: str, purchase_ctx):
        purchase_ctx.session.state["selected"] = value
        return SelectionStep(
            prompt="shop.second",
            options=[SelectionOption(label="Move A", value="1")],
            per_page=6,
            on_select=second_step,
        )

    step = SelectionStep(
        prompt="shop.first",
        options=[SelectionOption(label="Pikachu", value="0")],
        per_page=6,
        on_select=first_step,
    )
    session = FlowSession(item=item, cat_id="game_shop", cat_page=0, chat_id=100, step=step)
    set_session("telegram", 1, 100, session)

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 1000
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_tm.get.return_value = "prompt"

        # First selection — returns another SelectionScreen
        screen1 = await router.handle(MakeSelection(chat_id=100, value="0"), ctx)
        assert isinstance(screen1, SelectionScreen)

        # Second selection — completes flow
        screen2 = await router.handle(MakeSelection(chat_id=100, value="1"), ctx)
        assert isinstance(screen2, CategoryListScreen)

    # State was visible in second step
    assert recorded_state == {"selected": "0"}


@pytest.mark.asyncio
async def test_stale_make_selection_returns_category_list():
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

        screen = await router.handle(MakeSelection(chat_id=100, value="0"), ctx)

    assert isinstance(screen, CategoryListScreen)


@pytest.mark.asyncio
async def test_cancel_clears_session_and_returns_item_list():
    from src.shop.flow.router import ShopRouter
    from src.shop.flow.session import set_session, get_session
    from src.shop.flow.screens import SelectionOption
    router = ShopRouter()
    ctx = _make_ctx()
    cat = _make_category(cat_id="game_shop", items_per_page=5)
    item = cat.items[0]

    step = SelectionStep(
        prompt="shop.select",
        options=[SelectionOption(label="A", value="0")],
        per_page=6,
        on_select=AsyncMock(),
    )
    session = FlowSession(item=item, cat_id="game_shop", cat_page=0, chat_id=100, step=step)
    set_session("telegram", 1, 100, session)

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 500
        mock_gcm.get_controller.return_value = None
        mock_sm.get_categories.return_value = [cat]
        mock_sm.get_owned_items.return_value = set()
        mock_tm.get.return_value = ""

        screen = await router.handle(Cancel(chat_id=100), ctx)

    assert isinstance(screen, ItemListScreen)
    assert screen.category == cat
    assert screen.status is None
    assert get_session("telegram", 1, 100) is None


@pytest.mark.asyncio
async def test_cancel_with_no_session_returns_category_list():
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

        screen = await router.handle(Cancel(chat_id=100), ctx)

    assert isinstance(screen, CategoryListScreen)


@pytest.mark.asyncio
async def test_game_specific_categories_appear_for_matching_cartridge():
    from src.shop.flow.router import ShopRouter
    import src.game_shops

    extra_cat = _make_category(cat_id="game_cat")
    src.game_shops._EXTENSIONS["TEST_GAME"] = [extra_cat]

    router = ShopRouter()
    ctx = _make_ctx()
    mock_controller = MagicMock()
    mock_controller.pyboy.cartridge_title = "TEST_GAME"

    with patch("src.shop.flow.router.shop_manager") as mock_sm, \
         patch("src.shop.flow.router.game_controller_manager") as mock_gcm, \
         patch("src.shop.flow.router.translation_manager") as mock_tm:
        mock_sm.get_balance.return_value = 0
        mock_gcm.get_controller.return_value = mock_controller
        mock_sm.get_categories.return_value = []
        mock_tm.get.return_value = ""

        screen = await router.handle(OpenShop(chat_id=100), ctx)

    assert any(c.id == "game_cat" for c in screen.categories)
    # cleanup
    del src.game_shops._EXTENSIONS["TEST_GAME"]

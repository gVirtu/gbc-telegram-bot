from __future__ import annotations

import math
import logging
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shop.flow.actions import ShopAction
    from src.shop.flow.screens import ShopScreen

from src.shop.flow.actions import (
    OpenShop, NavigateCategories, NavigateCategoryItems,
    BuyItem, MakeSelection, NavigateSelectionPage, Cancel,
)
from src.shop.flow.screens import (
    CategoryListScreen, ItemListScreen, SelectionScreen, SelectionOption,
)
from src.shop.flow.handlers import (
    FlowSession, ShopInteractionContext, ShopPurchaseContext,
    PurchaseComplete, SelectionStep, default_purchase_handler,
)
from src.shop.flow.session import get_session, set_session, clear_session

# Module-level imports for patching in tests
from src.shop.shop_manager import shop_manager
from src.i18n import translation_manager
from src.game import game_controller_manager

logger = logging.getLogger(__name__)


class ShopRouter:
    """Routes ShopActions to ShopScreens.

    Both platforms call handle(action, ctx) and receive a ShopScreen to render.
    Business logic, i18n resolution, and FlowSession management all live here.
    """

    async def handle(
        self, action: ShopAction, ctx: ShopInteractionContext
    ) -> ShopScreen:
        if isinstance(action, (OpenShop, NavigateCategories)):
            chat_id = action.chat_id
            page = action.page if isinstance(action, NavigateCategories) else 0
            balance = shop_manager.get_balance(ctx.platform, ctx.user_id)
            controller = game_controller_manager.get_controller(chat_id)
            categories = self._get_categories(chat_id, controller)
            return CategoryListScreen(
                categories=categories,
                page=page,
                total_pages=1,
                balance=balance,
                chat_id=chat_id,
                platform=ctx.platform,
                user_id=ctx.user_id,
            )

        if isinstance(action, NavigateCategoryItems):
            chat_id = action.chat_id
            controller = game_controller_manager.get_controller(chat_id)
            cat = self._find_category(action.cat_id, chat_id, controller)
            if cat is None:
                balance = shop_manager.get_balance(ctx.platform, ctx.user_id)
                categories = self._get_categories(chat_id, controller)
                return CategoryListScreen(
                    categories=categories, page=0, total_pages=1,
                    balance=balance, chat_id=chat_id,
                    platform=ctx.platform, user_id=ctx.user_id,
                )
            owned_items = frozenset(shop_manager.get_owned_items(ctx.platform, ctx.user_id))
            items, total_pages = self._paginate(cat, action.page, owned_items)
            balance = shop_manager.get_balance(ctx.platform, ctx.user_id)
            return ItemListScreen(
                category=cat,
                items=items,
                page=action.page,
                total_pages=total_pages,
                balance=balance,
                chat_id=chat_id,
                platform=ctx.platform,
                user_id=ctx.user_id,
                owned_items=owned_items,
            )

        if isinstance(action, BuyItem):
            return await self._handle_buy(action, ctx)

        if isinstance(action, MakeSelection):
            return await self._handle_selection(action, ctx)

        if isinstance(action, NavigateSelectionPage):
            return await self._handle_selection_page(action, ctx)

        if isinstance(action, Cancel):
            return await self._handle_cancel(action, ctx)

        # Unreachable — satisfies type checker
        raise ValueError(f"Unknown action type: {type(action)}")

    def _get_categories(self, chat_id: int, controller) -> list:
        cats = list(shop_manager.get_categories())
        if controller is not None:
            try:
                from src.game_shops import get_categories_for_game
                game_id = controller.pyboy.cartridge_title
                cats += get_categories_for_game(game_id)
            except ImportError:
                pass
        return cats

    def _find_category(self, cat_id: str, chat_id: int, controller):
        return next(
            (c for c in self._get_categories(chat_id, controller) if c.id == cat_id),
            None,
        )

    def _find_item(self, item_id: str, chat_id: int, controller):
        for cat in self._get_categories(chat_id, controller):
            for item in cat.items:
                if item.id == item_id:
                    return item
        return None

    @staticmethod
    def _paginate(cat, page: int, owned_items: frozenset) -> tuple[list, int]:
        items = [i for i in cat.items if not i.secret or i.id in owned_items]
        total_pages = max(1, math.ceil(len(items) / cat.items_per_page))
        page = max(0, min(page, total_pages - 1))
        start = page * cat.items_per_page
        return items[start : start + cat.items_per_page], total_pages

    async def _handle_buy(self, action: BuyItem, ctx: ShopInteractionContext) -> ShopScreen:
        chat_id = action.chat_id
        controller = game_controller_manager.get_controller(chat_id)
        item = self._find_item(action.item_id, chat_id, controller)

        if item is None:
            balance = shop_manager.get_balance(ctx.platform, ctx.user_id)
            categories = self._get_categories(chat_id, controller)
            return CategoryListScreen(
                categories=categories, page=0, total_pages=1,
                balance=balance, chat_id=chat_id,
                platform=ctx.platform, user_id=ctx.user_id,
            )

        session = FlowSession(
            item=item,
            cat_id=action.cat_id,
            cat_page=action.cat_page,
            chat_id=chat_id,
        )
        purchase_ctx = ShopPurchaseContext(
            platform=ctx.platform,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            chat_id=chat_id,
            item=item,
            game_controller=controller,
            session=session,
        )
        handler = item.purchase_handler or default_purchase_handler
        outcome = await handler(purchase_ctx)

        return await self._screen_from_outcome(outcome, session, ctx, chat_id, controller)

    async def _handle_selection(self, action: MakeSelection, ctx: ShopInteractionContext) -> ShopScreen:
        session = get_session(ctx.platform, ctx.user_id, action.chat_id)
        if session is None or session.step is None:
            return await self.handle(OpenShop(chat_id=action.chat_id), ctx)

        controller = game_controller_manager.get_controller(action.chat_id)
        purchase_ctx = ShopPurchaseContext(
            platform=ctx.platform,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            chat_id=action.chat_id,
            item=session.item,
            game_controller=controller,
            session=session,
        )
        outcome = await session.step.on_select(action.value, purchase_ctx)
        return await self._screen_from_outcome(outcome, session, ctx, action.chat_id, controller)

    async def _handle_selection_page(self, action: NavigateSelectionPage, ctx: ShopInteractionContext) -> ShopScreen:
        session = get_session(ctx.platform, ctx.user_id, action.chat_id)
        if session is None or session.step is None:
            return await self.handle(OpenShop(chat_id=action.chat_id), ctx)

        step = session.step
        total_pages = max(1, math.ceil(len(step.options) / step.per_page))
        page = max(0, min(action.page, total_pages - 1))
        start = page * step.per_page
        options = [
            SelectionOption(
                label=translation_manager.get(opt.label, action.chat_id, **step.bindings),
                value=opt.value,
            ) for opt in step.options[start : start + step.per_page]
        ]
        prompt = translation_manager.get(step.prompt, action.chat_id, **step.bindings)
        return SelectionScreen(
            prompt=prompt,
            options=options,
            page=page,
            total_pages=total_pages,
            chat_id=action.chat_id,
        )

    async def _handle_cancel(self, action: Cancel, ctx: ShopInteractionContext) -> ShopScreen:
        session = get_session(ctx.platform, ctx.user_id, action.chat_id)
        clear_session(ctx.platform, ctx.user_id, action.chat_id)

        if session is None:
            return await self.handle(OpenShop(chat_id=action.chat_id), ctx)

        controller_ref = game_controller_manager.get_controller(action.chat_id)

        cat = self._find_category(session.cat_id, action.chat_id, controller_ref)
        if cat is None:
            return await self.handle(OpenShop(chat_id=action.chat_id), ctx)

        owned_items = frozenset(shop_manager.get_owned_items(ctx.platform, ctx.user_id))
        items, total_pages = self._paginate(cat, session.cat_page, owned_items)
        balance = shop_manager.get_balance(ctx.platform, ctx.user_id)
        return ItemListScreen(
            category=cat,
            items=items,
            page=session.cat_page,
            total_pages=total_pages,
            balance=balance,
            chat_id=action.chat_id,
            platform=ctx.platform,
            user_id=ctx.user_id,
            owned_items=owned_items,
        )

    async def _screen_from_outcome(self, outcome, session: FlowSession, ctx: ShopInteractionContext, chat_id: int, controller) -> ShopScreen:
        if isinstance(outcome, PurchaseComplete):
            clear_session(ctx.platform, ctx.user_id, chat_id)
            balance = shop_manager.get_balance(ctx.platform, ctx.user_id)

            if outcome.success:
                success_key = outcome.success_message or "shop.purchase_success"
                status = translation_manager.get(
                    success_key, chat_id,
                    **outcome.bindings,
                    item_name=translation_manager.get(session.item.name_i18n_key, chat_id),
                )
                categories = self._get_categories(chat_id, controller)
                return CategoryListScreen(
                    categories=categories, page=0, total_pages=1,
                    balance=balance, chat_id=chat_id,
                    platform=ctx.platform, user_id=ctx.user_id,
                    status=status, extra_messages=outcome.extra_messages,
                )
            else:
                error_key = outcome.error_message or "shop.insufficient_funds"
                cost = f"{session.item.cost:,}"
                status = translation_manager.get(
                    error_key, chat_id,
                    **outcome.bindings,
                    cost=cost, balance=f"{balance:,}",
                )
                cat = self._find_category(session.cat_id, chat_id, controller)
                if cat is None:
                    categories = self._get_categories(chat_id, controller)
                    return CategoryListScreen(
                        categories=categories, page=0, total_pages=1,
                        balance=balance, chat_id=chat_id,
                        platform=ctx.platform, user_id=ctx.user_id,
                        status=status,
                    )
                owned_items = frozenset(shop_manager.get_owned_items(ctx.platform, ctx.user_id))
                items, total_pages = self._paginate(cat, session.cat_page, owned_items)
                return ItemListScreen(
                    category=cat, items=items,
                    page=session.cat_page, total_pages=total_pages,
                    balance=balance, chat_id=chat_id,
                    platform=ctx.platform, user_id=ctx.user_id,
                    owned_items=owned_items, status=status,
                )

        step: SelectionStep = outcome
        session.step = step
        set_session(ctx.platform, ctx.user_id, chat_id, session)
        total_pages = max(1, math.ceil(len(step.options) / step.per_page))
        options = [
            SelectionOption(
                label=translation_manager.get(opt.label, chat_id, **step.bindings),
                value=opt.value,
            ) for opt in step.options[: step.per_page]
        ]
        prompt = translation_manager.get(step.prompt, chat_id, **step.bindings)
        return SelectionScreen(
            prompt=prompt,
            options=options,
            page=0,
            total_pages=total_pages,
            chat_id=chat_id,
        )


shop_router = ShopRouter()

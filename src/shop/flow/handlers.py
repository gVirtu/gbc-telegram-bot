from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Awaitable

if TYPE_CHECKING:
    from src.game import GameController
    from src.shop.items import ShopItem
    from src.adapters.base import BotAdapter
    from src.shop.flow.screens import SelectionOption


@dataclass
class PurchaseComplete:
    success: bool
    error_message: str | None = None   # i18n key; resolved by router


@dataclass
class SelectionStep:
    prompt: str                         # i18n key; resolved by router
    options: list[SelectionOption]
    per_page: int
    on_select: Callable[[str, "ShopPurchaseContext"], Awaitable["PurchaseOutcome"]]


PurchaseOutcome = PurchaseComplete | SelectionStep
PurchaseHandler = Callable[["ShopPurchaseContext"], Awaitable[PurchaseOutcome]]


@dataclass
class FlowSession:
    """In-memory state for a pending multi-step purchase flow."""
    item: ShopItem
    cat_id: str
    cat_page: int
    chat_id: int
    step: SelectionStep | None = None   # set once the first SelectionStep is returned
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShopInteractionContext:
    """Caller identity passed to ShopRouter.handle()."""
    platform: str
    user_id: int
    user_name: str
    adapter: BotAdapter


@dataclass
class ShopPurchaseContext:
    """Context passed to every purchase handler call."""
    platform: str
    user_id: int
    user_name: str
    chat_id: int
    item: ShopItem
    game_controller: GameController | None
    session: FlowSession   # always present; state dict starts empty

    async def check_balance(self) -> bool:
        """Return True if the user can afford item.cost (accounting for one_time_purchase)."""
        from src.shop.shop_manager import shop_manager
        can_afford, _ = shop_manager.validate_purchase(self.platform, self.user_id, self.item)
        return can_afford

    async def record_purchase(self, cost: int | None = None) -> None:
        """Deduct points and record the transaction.

        Args:
            cost: Override the point cost. If None, uses the effective cost from
                  validate_purchase (0 for already-owned one_time_purchase items).
        """
        from src.shop.shop_manager import shop_manager
        _, effective_cost = shop_manager.validate_purchase(self.platform, self.user_id, self.item)
        final_cost = cost if cost is not None else effective_cost
        shop_manager.record_transaction(self.platform, self.user_id, self.item.id, final_cost)


async def default_purchase_handler(ctx: ShopPurchaseContext) -> PurchaseOutcome:
    """Handler for all built-in items — delegates to shop_manager.purchase()."""
    from src.shop.shop_manager import shop_manager
    result = shop_manager.purchase(
        ctx.platform, ctx.user_id, ctx.item.id, ctx.chat_id, ctx.user_name
    )
    if result.success:
        return PurchaseComplete(success=True)
    return PurchaseComplete(success=False, error_message=result.error_i18n_key)

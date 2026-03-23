"""Shop manager for the points shop."""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass

from src.db.connection import DatabaseConnection
from src.shop.items import SHOP_CATEGORIES, ShopCategory, ShopItem

logger = logging.getLogger(__name__)


@dataclass
class PurchaseResult:
    """Result of a purchase attempt."""

    success: bool
    error_i18n_key: str | None = None
    item: ShopItem | None = None


class ShopManager:
    """Handles shop balance queries, pagination, validation, and purchases."""

    def __init__(self, conn: DatabaseConnection) -> None:
        self._conn = conn

    def get_balance(self, platform: str, user_id: int) -> int:
        """Return earned - spent for the user (0 if no profile)."""
        row = self._conn.execute(
            "SELECT total_score_earned - total_score_spent "
            "FROM user_player_profiles WHERE platform = ? AND user_id = ?;",
            (platform, user_id),
        ).fetchone()
        return row[0] if row else 0

    def get_categories(self) -> list[ShopCategory]:
        """Return all shop categories."""
        return SHOP_CATEGORIES

    def get_category(self, cat_id: str) -> ShopCategory | None:
        """Return the category with the given id, or None."""
        return next((c for c in SHOP_CATEGORIES if c.id == cat_id), None)

    def get_category_page(self, cat_id: str, page: int) -> tuple[list[ShopItem], int]:
        """Return (items_on_page, total_pages) for the given category, clamping page to valid range."""
        cat = self.get_category(cat_id)
        if cat is None:
            return [], 1
        total_pages = max(1, math.ceil(len(cat.items) / cat.items_per_page))
        page = max(0, min(page, total_pages - 1))
        start = page * cat.items_per_page
        return cat.items[start : start + cat.items_per_page], total_pages

    def get_item(self, item_id: str) -> ShopItem | None:
        """Search across all categories and return the item with the given id, or None."""
        for cat in SHOP_CATEGORIES:
            for item in cat.items:
                if item.id == item_id:
                    return item
        return None

    def validate_shop_access(
        self, platform: str, user_id: int, chat_id: int
    ) -> tuple[bool, str | None]:
        """Validate that the user can open the shop for the given chat.

        Returns:
            (True, None) if valid.
            (False, None) if chat not found — silent ignore.
            (False, "shop.no_profile") if user has no profile.
        """
        chat_row = self._conn.execute(
            "SELECT 1 FROM chat_configs WHERE chat_id = ?;", (chat_id,)
        ).fetchone()
        if chat_row is None:
            return (False, None)

        profile_row = self._conn.execute(
            "SELECT 1 FROM user_player_profiles WHERE platform = ? AND user_id = ?;",
            (platform, user_id),
        ).fetchone()
        if profile_row is None:
            return (False, "shop.no_profile")

        return (True, None)

    def purchase(
        self,
        platform: str,
        user_id: int,
        item_id: str,
        chat_id: int = 0,
        user_name: str = "",
    ) -> PurchaseResult:
        """Attempt to purchase an item.

        Called only after validate_shop_access has passed.
        Returns PurchaseResult with success=True or error details.
        """
        item = self.get_item(item_id)
        if item is None:
            return PurchaseResult(success=False)  # unknown item_id; callers handle gracefully

        balance = self.get_balance(platform, user_id)
        if balance < item.cost:
            return PurchaseResult(
                success=False, error_i18n_key="shop.insufficient_funds", item=item
            )

        if "reaction" in item.effect:
            reaction_type = item.effect["reaction"]
            self._conn.execute(
                "INSERT INTO reaction_queue (chat_id, user_id, user_name, reaction_type) "
                "VALUES (?, ?, ?, ?);",
                (chat_id, user_id, user_name, reaction_type),
            )
            self._conn.execute(
                "UPDATE user_player_profiles "
                "SET total_score_spent = total_score_spent + ? "
                "WHERE platform = ? AND user_id = ?;",
                (item.cost, platform, user_id),
            )
        else:
            name_tag_color = item.effect.get("name_tag_color", "#FFFFFF")
            self._conn.execute(
                "UPDATE user_player_profiles "
                "SET name_tag_color = ?, total_score_spent = total_score_spent + ? "
                "WHERE platform = ? AND user_id = ?;",
                (name_tag_color, item.cost, platform, user_id),
            )

        self._conn.commit()
        return PurchaseResult(success=True, item=item)


class _ShopManagerProxy:
    """Lazy singleton proxy, mirroring the pattern used by scoring_manager."""

    _instance: ShopManager | None = None

    def _get_instance(self) -> ShopManager:
        if self._instance is None:
            from src.utils.state_manager import state_manager

            self._instance = ShopManager(state_manager.connection)
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get_instance(), name)


shop_manager: _ShopManagerProxy = _ShopManagerProxy()


def build_shop_text(
    balance: int,
    category: ShopCategory | None,
    page: int,
    total_pages: int,
    chat_id: int,
    status_message: str | None = None,
) -> str:
    """Build the shop message text (platform-agnostic).

    Args:
        balance: Current point balance to display.
        page: Zero-based page index.
        total_pages: Total number of pages.
        chat_id: Chat ID used for i18n lookups.
        status_message: Optional status line prepended before the welcome text.
    """
    from src.i18n import translation_manager

    parts = []
    if status_message:
        parts.append(status_message)
    parts.append(translation_manager.get("shop.welcome", chat_id))
    if category:
        parts.append(translation_manager.get(category.label, chat_id))
        parts.append(translation_manager.get(category.description, chat_id))
    parts.append(translation_manager.get("shop.balance", chat_id, balance=f"{balance:,}"))
    parts.append(translation_manager.get("shop.page_indicator", chat_id, page=page + 1, total=total_pages))
    return "\n\n".join(parts)

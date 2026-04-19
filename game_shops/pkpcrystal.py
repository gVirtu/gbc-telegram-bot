"""Polished Crystal game-specific shop extensions.

Handlers defined here have access to ctx.game_controller (a GameController) and
ctx.session.state (a dict that persists across SelectionStep chains).
"""
from game_shops import register
from src.shop.items import ShopCategory, ShopItem

# No categories yet — placeholder for future game-specific items.
register("POKEMON CRYSTAL", [])

"""Scoring data models for the player points system."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoredInput:
    """Result of scoring a single player input.

    Attributes:
        platform: Platform identifier (e.g. "telegram", "discord")
        user_id: Platform user ID
        chat_id: Chat/channel ID
        button: Button value pressed
        base_score: Points earned from input diversity window
        streak_bonus: Points earned from daily streak
        total_score: base_score + streak_bonus
    """

    platform: str
    user_id: int
    chat_id: int
    button: str
    base_score: int
    streak_bonus: int
    total_score: int


@dataclass
class PlayerProfile:
    """Persistent player scoring profile.

    Attributes:
        platform: Platform identifier
        user_id: Platform user ID
        total_score_earned: Lifetime points earned
        total_score_spent: Lifetime points spent (reserved for future use)
        current_streak: Current consecutive-day streak
        best_streak: All-time best streak
        best_streak_date: UTC date when best_streak was set (ISO format)
        last_input_at: UTC timestamp of last scored input (ISO format)
    """

    platform: str
    user_id: int
    total_score_earned: int
    total_score_spent: int
    current_streak: int
    best_streak: int
    best_streak_date: str | None
    last_input_at: str | None

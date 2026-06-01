"""Scoring manager for the player points system.

Computes base score and daily streak bonus for each button press,
then persists results to user_player_profiles and returns them for
inclusion in the recent_inputs log row.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.config import settings
from src.db.connection import DatabaseConnection
from src.models.scoring import PlayerProfile, ScoredInput

logger = logging.getLogger(__name__)


class ScoringManager:
    """Computes and persists player scores.

    Uses the same DatabaseConnection as the rest of the app so all writes
    share the same SQLite file.
    """

    def __init__(self, connection: DatabaseConnection) -> None:
        self._conn = connection

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def score_input(
        self,
        platform: str,
        user_id: int,
        chat_id: int,
        button: str,
        user_name: str = "",
        commit: bool = True,
    ) -> ScoredInput:
        """Score a single player input and update their profile.

        Args:
            platform: Platform identifier (e.g. "telegram")
            user_id: Platform user ID
            chat_id: Chat/channel ID
            button: Button value string
            commit: Whether to commit after writing. Pass False when the caller
                will issue a batched commit after processing multiple inputs.

        Returns:
            ScoredInput with computed scores (all zeros on error)
        """
        try:
            return self._score_input_unsafe(platform, user_id, chat_id, button, user_name=user_name, commit=commit)
        except Exception as e:
            logger.error(f"score_input failed for user {user_id} in chat {chat_id}: {e}")
            return ScoredInput(
                platform=platform,
                user_id=user_id,
                chat_id=chat_id,
                button=button,
                base_score=0,
                streak_bonus=0,
                total_score=0,
            )

    def score_event(self, platform: str, user_id: int, awarded_score: int, commit: bool = True) -> None:
        """Add score directly to user_player_profiles.total_score_earned.

        Does NOT affect streaks, recent_inputs, or diversity scoring.

        When commit=False, the caller is responsible for committing the transaction
        (used within batch processing to keep all scoring in a single transaction).
        """
        self._conn.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, total_score_earned, total_score_spent,
                current_streak, best_streak, best_streak_date, last_input_at)
               VALUES (?, ?, ?, 0, 0, 0, NULL, NULL)
               ON CONFLICT(platform, user_id) DO UPDATE SET
                   total_score_earned = total_score_earned + excluded.total_score_earned;""",
            (platform, user_id, awarded_score),
        )
        if commit:
            self._conn.commit()

    def get_player_profile(self, platform: str, user_id: int) -> PlayerProfile | None:
        """Fetch a player's scoring profile.

        Returns:
            PlayerProfile if found, None otherwise
        """
        cursor = self._conn.execute(
            "SELECT * FROM user_player_profiles WHERE platform = ? AND user_id = ?;",
            (platform, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return PlayerProfile(
            platform=row["platform"],
            user_id=row["user_id"],
            total_score_earned=row["total_score_earned"],
            total_score_spent=row["total_score_spent"],
            current_streak=row["current_streak"],
            best_streak=row["best_streak"],
            best_streak_date=row["best_streak_date"],
            last_input_at=row["last_input_at"],
            name_tag_color=row["name_tag_color"],
        )

    def get_player_profiles_batch(self, platform: str, user_ids: list) -> dict:
        """Fetch multiple player profiles in a single query.

        Returns a dict keyed by user_id. Users not found are absent from the dict.
        """
        if not user_ids:
            return {}
        placeholders = ",".join("?" * len(user_ids))
        cursor = self._conn.execute(
            f"SELECT * FROM user_player_profiles WHERE platform = ? AND user_id IN ({placeholders});",
            (platform, *user_ids),
        )
        return {
            row["user_id"]: PlayerProfile(
                platform=row["platform"],
                user_id=row["user_id"],
                total_score_earned=row["total_score_earned"],
                total_score_spent=row["total_score_spent"],
                current_streak=row["current_streak"],
                best_streak=row["best_streak"],
                best_streak_date=row["best_streak_date"],
                last_input_at=row["last_input_at"],
                name_tag_color=row["name_tag_color"],
            )
            for row in cursor.fetchall()
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _score_input_unsafe(
        self,
        platform: str,
        user_id: int,
        chat_id: int,
        button: str,
        user_name: str = "",
        commit: bool = True,
    ) -> ScoredInput:
        max_score = settings.player_input_max_score
        streak_bonus_per_day = settings.daily_streak_score_bonus

        now_utc = datetime.now(timezone.utc)

        # --- Base score: diversity window ---
        cursor = self._conn.execute(
            """SELECT user_id FROM recent_inputs
               WHERE chat_id = ?
               ORDER BY id DESC
               LIMIT ?;""",
            (chat_id, max_score),
        )
        window_rows = cursor.fetchall()
        same_user_count = sum(1 for r in window_rows if r["user_id"] == user_id)
        base_score = max(1, max_score - same_user_count)

        # --- Streak logic ---
        profile = self.get_player_profile(platform, user_id)
        today_utc = now_utc.date()

        if profile is None:
            # Brand new player
            current_streak = 1
            streak_bonus = 1 * streak_bonus_per_day
            best_streak = 1
            best_streak_date: str | None = today_utc.isoformat()
            total_score_earned = base_score + streak_bonus
            total_score_spent = 0
        else:
            current_streak = profile.current_streak
            best_streak = profile.best_streak
            best_streak_date = profile.best_streak_date
            total_score_earned = profile.total_score_earned
            total_score_spent = profile.total_score_spent

            if profile.last_input_at is None:
                # Existing row but never played (shouldn't happen, defensive)
                current_streak = 1
                streak_bonus = 1 * streak_bonus_per_day
            else:
                last_date = datetime.fromisoformat(profile.last_input_at).date()
                delta = (today_utc - last_date).days

                if delta == 0:
                    streak_bonus = 0  # same day, no bonus
                elif delta == 1:
                    current_streak += 1
                    streak_bonus = current_streak * streak_bonus_per_day
                else:
                    current_streak = 1
                    streak_bonus = 1 * streak_bonus_per_day

            if current_streak > best_streak:
                best_streak = current_streak
                best_streak_date = today_utc.isoformat()

            total_score_earned += base_score + streak_bonus

        # --- Persist profile ---
        self._conn.execute(
            """INSERT INTO user_player_profiles
               (platform, user_id, user_name, total_score_earned, total_score_spent,
                current_streak, best_streak, best_streak_date, last_input_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform, user_id) DO UPDATE SET
                   user_name = excluded.user_name,
                   total_score_earned = excluded.total_score_earned,
                   current_streak = excluded.current_streak,
                   best_streak = excluded.best_streak,
                   best_streak_date = excluded.best_streak_date,
                   last_input_at = excluded.last_input_at;""",
            (
                platform,
                user_id,
                user_name,
                total_score_earned,
                total_score_spent,
                current_streak,
                best_streak,
                best_streak_date,
                now_utc.isoformat(),
            ),
        )
        if commit:
            self._conn.commit()

        return ScoredInput(
            platform=platform,
            user_id=user_id,
            chat_id=chat_id,
            button=button,
            base_score=base_score,
            streak_bonus=streak_bonus,
            total_score=base_score + streak_bonus,
            current_streak=current_streak,
        )


class _ScoringManagerProxy:
    """Lazy singleton proxy, mirroring the pattern used by state_manager."""

    _instance: ScoringManager | None = None

    def _get_instance(self) -> ScoringManager:
        if self._instance is None:
            from src.utils.state_manager import state_manager

            self._instance = ScoringManager(state_manager.connection)
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get_instance(), name)


scoring_manager: _ScoringManagerProxy = _ScoringManagerProxy()

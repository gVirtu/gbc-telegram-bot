from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shop.flow.handlers import FlowSession

# Keyed by (platform, user_id, chat_id)
_sessions: dict[tuple[str, int, int], FlowSession] = {}


def get_session(platform: str, user_id: int, chat_id: int) -> FlowSession | None:
    return _sessions.get((platform, user_id, chat_id))


def set_session(platform: str, user_id: int, chat_id: int, session: FlowSession) -> None:
    _sessions[(platform, user_id, chat_id)] = session


def clear_session(platform: str, user_id: int, chat_id: int) -> None:
    _sessions.pop((platform, user_id, chat_id), None)

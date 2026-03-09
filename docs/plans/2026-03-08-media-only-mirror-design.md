# Design: media_only_mirror Feature Flag

**Date:** 2026-03-08
**Branch:** experimental/discord

## Overview

Add a `media_only_mirror` feature flag that turns a mirror chat into a media-only space: it receives `/print`, `/gif`, `/recap`, and `/status` outputs but never game frame broadcasts, text broadcasts, button inputs, or `/resume`. The flag has no effect on leader chats.

## Feature Flag & Model

- Add `"media_only_mirror"` to `KNOWN_FEATURE_FLAGS` in `src/models/game_state.py`.
- No DB migration needed — the `feature_flags` JSON column already stores arbitrary keys.
- Toggled via the existing `/feature media_only_mirror true|false` command (admin only).
- Flag is only meaningful when the chat has `mirrors_chat_id` set; on a leader it is a no-op.

## Helper Predicate

Add `is_media_only_mirror(chat_id: int) -> bool` to `src/utils/mirror_utils.py`.

Returns `True` if and only if:
1. `chat_id` is a mirror (`mirrors_chat_id` is set), **and**
2. `feature_flags["media_only_mirror"]` is `True`.

This is the single source of truth for all enforcement sites.

## Enforcement Sites

| Location | Behaviour |
|---|---|
| `broadcast_game_update` (`mirror_utils.py`) | Skip target if `is_media_only_mirror(target_id)` |
| `broadcast_text` (`mirror_utils.py`) | Skip target if `is_media_only_mirror(target_id)` |
| `resume_command` (`commands.py`) | Return immediately (no message) if `is_media_only_mirror(chat_id)` |
| `InputHandler.handle_button_press` (`handlers/input_handler.py`) | Return immediately (no message) if `is_media_only_mirror(chat_id)` |

## Testing

- `is_media_only_mirror` returns `False` for leader chats, non-mirror chats, and mirrors without the flag
- `is_media_only_mirror` returns `True` only for mirrors with the flag enabled
- `broadcast_game_update` skips media-only mirrors (adapter not called for that target)
- `broadcast_text` skips media-only mirrors
- `resume_command` returns early silently for media-only mirrors
- `handle_button_press` returns early silently for media-only mirrors
- `/feature media_only_mirror true/false` toggling works via existing `feature_command` path

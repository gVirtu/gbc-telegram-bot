# Modifier Rendering in Input Sidebar — Design

**Date:** 2026-04-15  
**Branch:** experimental/discord

## Summary

When a button press is made with an active modifier (e.g. holding B while pressing UP to run), the modifier button char is displayed before the pressed button char in the input sidebar overlay.

**Before:**
```
Player: ⬆
```

**After:**
```
Player: Ⓑ⬆
```

## Architecture

The modifier value flows from execution time → DB persistence → overlay rendering. Three layers are touched:

### 1. DB Migration (`src/db/migrations/024_add_modifier_to_recent_inputs.py`)

Add nullable `modifier TEXT` column to `recent_inputs`:

```sql
ALTER TABLE recent_inputs ADD COLUMN modifier TEXT DEFAULT NULL;
```

- No backfill. Historical rows have `NULL` modifier and render unchanged.
- Downgrade is a no-op (SQLite cannot drop columns).

### 2. Data Flow (`src/handlers/input_handler.py`, `src/db/manager.py`)

**`_process_batch`:** When the modifier branch is taken (a `ModifierButtonSpec` applies), capture `spec.modifier_button.value` (e.g. `"b"`), otherwise `None`. Add to both `input_dict` and the `append_recent_input` call.

**`append_recent_input`:** Add `modifier: str | None = None` parameter; include in INSERT.

**`get_recent_inputs_for_overlay`:** Add `ri.modifier` to SELECT and returned dicts.

`_load_recent_inputs` (text caption / grouping path) is not changed.

### 3. Rendering (`src/utils/frame_utils.py`)

In `render_input_sidebar`, prepend modifier char when present:

```python
modifier_val = entry.get("modifier")
modifier_char = BUTTON_CHARS.get(modifier_val, "") if modifier_val else ""
suffix = f": {modifier_char}{button_char}"
```

Reuses the existing `BUTTON_CHARS` map. No new mapping needed. `None`/absent modifier produces no prefix — identical to current behavior.

## Scope

- `_build_recent_inputs_grouped` is not changed (feeds text caption only).
- No changes to scoring, grouping, or caption logic.

## Testing

- Unit test: `render_input_sidebar` with a modifier entry renders `Ⓑ⬆` correctly.
- Unit test: `render_input_sidebar` with no modifier renders unchanged.
- Unit test: `append_recent_input` / `get_recent_inputs_for_overlay` round-trip with modifier value.
- Unit test: `_process_batch` sets `modifier` in `input_dict` when a matching spec is active; `None` otherwise.

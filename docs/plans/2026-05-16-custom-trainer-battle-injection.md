# Custom Trainer Battle Injection

Inject a programmed trainer battle as a "points shop reward" — player purchases an item, bot redirects game state into a battle with a custom team, then returns to the overworld.

## Architecture

Three components orchestrate the flow:

```
Purchase handler (async)
  └─ validates preconditions, stores cache entry (state=pending)

Hook A (@ PlayerEvents, every frame)
  └─ reads cache, re-validates, injects a script + trainer data (state=starting)

Hook B (@ ReadTrainerParty.return, after ROM data loaded)
  └─ reads cache, overwrites WRAM with custom team (clears cache)
```

All three share an **in-memory dict** keyed by `chat_id`. The state machine:

```
pending ──Hook A──→ starting ──Hook B──→ (deleted)
```

The battle runs through the **game's own script engine** — no PC redirect, no trampoline, no bank switching. A 3-byte script (`startbattle`, `reloadmapafterbattle`, `end`) is written to an unused WRAM0 byte and the script engine pointer is set to it.

## File changes

| File                                                       | Change                                              |
| ---------------------------------------------------------- | --------------------------------------------------- |
| `src/game.py`                                              | `begin_hooks()` passes `chat_id` to hook module     |
| `src/game_hooks/pkpcrystal.py`                             | Module-level battle request cache + Hook A + Hook B |
| `src/game_shops/pkpcrystal.py`                             | New `redeem_battle` shop item + purchase handler    |
| `docs/plans/2026-05-16-custom-trainer-battle-injection.md` | This plan                                           |

## Key symbols

Lookups via `pyboy.symbol_lookup()`. All reads/writes use symbol names, never absolute addresses.

### ROM symbols (hook registration + script target)

| Symbol                    | Address   | Purpose                |
| ------------------------- | --------- | ---------------------- |
| `PlayerEvents`            | `25:5216` | Hook A — trigger       |
| `ReadTrainerParty.return` | `07:4137` | Hook B — data override     |

### WRAM symbols (reads + writes)

Read via `symbol_read_u8(pyboy, "wBattleMode")` etc., write via `pyboy.memory[symbol_lookup("wBattleMode")] = value`.

| Symbol                 | Size | Purpose                                                     |
| ---------------------- | ---- | ----------------------------------------------------------- |
| `wBattleMode`          | 1    | 0=overworld, 2=trainer                                      |
| `wScriptRunning`       | 1    | 0=no script                                                 |
| `wPartyCount`          | 1    | player's party size                                         |
| `wOtherTrainerClass`   | 1    | set to valid class for pic                                  |
| `wOtherTrainerID`      | 1    | trainer ID within class                                     |
| `wTrainerClass`        | 1    | copied from wOtherTrainerClass by InitEnemy                 |
| `wCurPartyLevel`       | 1    | level of mon being processed (read by ComputeTrainerReward) |
| `wCurPartySpecies`     | 1    | species to process                                          |
| `wCurForm`             | 1    | form (0 for default)                                        |
| `wMonType`             | 1    | set to OTPARTYMON (1)                                       |
| `wOtherTrainerType`    | 1    | bitfield, set to 0                                          |
| `wEnemyTrainerAIFlags` | 3    | zero for default AI                                         |
| `wPartyMon1Level`      | 1    | level of player's lead — read to scale enemy                |
| `wBattleReward`        | 3    | money reward, set to 0                                      |

### Party data area (WRAMX, via symbol_lookup)

| Symbol                 | Size | Purpose                                    |
| ---------------------- | ---- | ------------------------------------------ |
| `wOTPartyCount`        | 1    | enemy party size                           |
| `wOTPartyMon1`         | 48   | enemy mon 1 (Ditto)                        |
| `wOTPartyMonNicknames` | 66   | enemy nicknames (first 11 bytes for mon 1) |

### Player data (reads only)

| Symbol                          | Read for                                |
| ------------------------------- | --------------------------------------- |
| `wPartyMon1` + MON_LEVEL offset | enemy Ditto level = player's lead level |

### HRAM symbols

| Symbol                 | Purpose                       |
| ---------------------- | ----------------------------- |
| `hScriptPos` (2 bytes) | script engine program counter |
| `hScriptBank` (1 byte) | script engine bank selector   |

## Constant reference

| Constant                       | Value  | Notes                            |
| ------------------------------ | ------ | -------------------------------- |
| DITTO                          | `0x54` | species ID                       |
| PARTYMON_STRUCT_LENGTH         | 48     | size of each party entry         |
| MON_LEVEL                      | 31     | level offset within party_struct |
| `startbattle_command`          | `0x5E` | script bytecode                  |
| `reloadmapafterbattle_command` | `0x5F` | script bytecode                  |
| `end_command`                  | `0x8F` | script bytecode                  |

For TRANSFORM move ID: look up in `constants/move_constants.asm`. If unavailable, substitute with TACKLE.

## Implementation tasks

### Task 1 — Pass `chat_id` to `begin_hooks`

**File:** `src/game.py`

**Change:** `GameController.begin_hooks()` passes `self.chat_id` as a second argument:

```python
def begin_hooks(self) -> dict:
    ...
    return self._hook_module.begin_hooks(self.pyboy, self.chat_id)
```

**Acceptance criteria:**

- `chat_id` arrives in `pkpcrystal.begin_hooks(pyboy, chat_id)`
- All call sites (including tests) are updated

---

### Task 2 — Battle request cache

**File:** `src/game_hooks/pkpcrystal.py` (module-level)

```python
_battle_requests: dict[int, dict] = {}

def queue_battle_request(chat_id: int, user_id: int) -> None:
    _battle_requests[chat_id] = {"state": "pending", "user_id": user_id}

def _resolve_battle_request(chat_id: int) -> dict | None:
    return _battle_requests.get(chat_id)

def _remove_battle_request(chat_id: int) -> None:
    _battle_requests.pop(chat_id, None)
```

**Acceptance criteria:**

- `queue_battle_request` creates entry with `state="pending"`
- `_resolve_battle_request` returns the dict by `chat_id` or `None`
- `_remove_battle_request` deletes the entry

---

### Task 3 — Hook A (PlayerEvents)

**File:** `src/game_hooks/pkpcrystal.py`

Register via `pyboy.hook_register(None, "PlayerEvents", hook_a_callback, None)`.

**On fire:**

1. `req = _resolve_battle_request(chat_id)`
2. If `req is None` or `req["state"] != "pending"`: return (no-op)
3. Re-validate (read via `symbol_read_u8`):
   - `wBattleMode == 0`
   - `wScriptRunning == 0`
   - `wPartyCount > 0`
   - If invalid: return (entry stays `pending`, retries next frame)
4. Read `wPartyMon1Level` (via `wPartyMon1` + `MON_LEVEL` in a 48-byte struct lookup) → save as enemy level
5. Build the 3-byte script in a safe WRAM0 area (use `_battle_script_addr` as the location):
   - Byte 0: `0x5E` (startbattle)
   - Byte 1: `0x5F` (reloadmapafterbattle)
   - Byte 2: `0x8F` (end)
6. Set `hScriptBank` to 0 (doesn't matter for WRAM reads, still set for cleanliness)
7. Set `hScriptPos` (2 bytes, LE) to the WRAM0 address of the script
8. Set `wScriptRunning = 1`
9. Set `wOtherTrainerClass` = 1 (YOUNGSTER — first class, valid pic)
10. Set cache `state = "starting"`
11. Populate the enemy trainer data so ReadTrainerParty's ROM-load won't matter _if_ Hook B fires late — actually, Hook B will overwrite this. The important thing is:
    - Write custom team data to a _scratch buffer_ in WRAM (the Unused WRAM0 section works, or use the same area)
    - Nothing else needed — Hook B will write the actual WRAM fields
12. Return

After Hook A returns, PlayerEvents checks `wScriptRunning != 0 → ret nz`. ScriptEvents runs next within the same MapEvents call, reads `0x5E`, dispatches to `Script_startbattle` → `predef StartBattle` → `BattleIntro`.

**Script bytecode location:** Use the 69-byte `SECTION "Unused"` in WRAM0. Find its exact address by deriving from `wFootprintQueue` + 7

**HRAM note:** `hScriptBank` and `hScriptPos` are in HRAM ($FF80-$FFFE). `symbol_lookup("hScriptBank")` returns `(0, 0xFFEB)` and `(0, 0xFFEC)` for `hScriptPos`. Use the tuple form `pyboy.memory[(0, 0xFFEB)] = 0`.

**WRAMX note:** All writes to WRAMX symbols (like `wOTPartyMon1`) must set `pyboy.memory[0xFF70] = 1` first (SVBK = WRAMX bank 1). Writes to WRAM0 symbols don't need this.

**Acceptance criteria:**

- Hook fires every frame at PlayerEvents
- Cache lookup for chat_id works across hook boundaries
- Re-validates wBattleMode, wScriptRunning, wPartyCount
- Skips redirect if re-validation fails (entry stays pending)
- Writes 3-byte script to WRAM0 correctly
- Sets hScriptPos, hScriptBank to point at script
- Sets wScriptRunning = 1
- Sets wOtherTrainerClass = 1
- Transitions cache state to "starting"
- Returns without PC redirect (let game engine take over)

---

### Task 4 — Hook B (ReadTrainerParty.return)

**File:** `src/game_hooks/pkpcrystal.py`

Register via `pyboy.hook_register(None, "ReadTrainerParty.return", hook_b_callback, None)`.

ReadTrainerParty runs normally (loads a ROM trainer's team into wOTPartyMons). Hook B fires *after* it finishes, overwriting the just-loaded data with our custom team. No PC redirect needed — the farcall return mechanism handles bank restoration naturally.

**On fire:**

1. `req = _resolve_battle_request(chat_id)`
2. If `req is None` or `req["state"] != "starting"`: return (no-op — normal trainer battle; ReadTrainerParty loaded the real YOUNGSTER team, which remains as a safe fallback)
3. Write custom team to WRAMX (set SVBK to 1 first via `pyboy.memory[0xFF70] = 1`):
   - `wOTPartyCount` = 1
   - `wOTPartyMon1` (48 bytes) — Ditto at saved level
   - `wOTPartyMonNicknames` (first 11 bytes) — species name in game encoding
4. Override trainer identity:
   - `wOTPlayerName` (11 bytes) — e.g., "DITTO\x50\x50\x50\x50\x50\x50" or keep defaults from GetTrainerAttributes
   - `wOTClassName` (13 bytes) — keep defaults ("YOUNGSTER")
5. Set processing variables (some were already set by ReadTrainerParty, overwrite ours):
   - `wCurPartySpecies` = DITTO
   - `wCurPartyLevel` = saved enemy level
   - `wCurForm` = 0
   - `wMonType` = 1 (OTPARTYMON)
   - `wOtherTrainerType` = 0
   - `wEnemyTrainerAIFlags` (3 bytes) = 0, 0, 0
   - `wBattleReward` (3 bytes) = 0, 0, 0
6. Clear cache: `_remove_battle_request(chat_id)`

**Acceptance criteria:**

- Hook fires at ReadTrainerParty.return (after ROM data is loaded)
- Skips overwrite when cache state is not "starting" (normal trainer battle — real team stays)
- Writes all required fields to WRAM
- Clears cache entry
- No PC redirect needed — ReadTrainerParty ran naturally

---

### Task 5 — Dummy team builder

**File:** `src/game_hooks/pkpcrystal.py` (helper function)

Hooks A and/or B need a 48-byte `party_struct` for the enemy mon. Because Hook B skips `ReadTrainerParty`, the normal initialization function `TryAddMonToParty` (which computes moves from level-up learnset, sets default DVs, calculates stats, fills OT name/ID) **never runs**. Every byte of the struct is whatever was left in WRAM — garbage, stale data, or zeros.

`SendInUserPkmn` (called in `DoBattle`) copies the struct verbatim into `wEnemyMon`:

```asm
ld bc, MON_ID - MON_SPECIES
rst CopyBytes           ; species, item, moves
ld bc, MON_PKRUS - MON_DVS
rst CopyBytes           ; DVs, personality, PP, happiness
ld bc, PARTYMON_STRUCT_LENGTH - MON_LEVEL
rst CopyBytes           ; level, status, HP, stats
```

No recalculation. Zero HP = fainted before the battle starts.

**Which fields actually matter?** For a Ditto that uses Transform on turn 1, most fields are overwritten by the opponent's stats. Only these are genuinely required:

| Must be set | Reason |
|-------------|--------|
| Species (offset 0) | Identifies the mon for Transform's copy, EXP yield, etc. |
| Level (offset 30) | Used by `ComputeTrainerReward` for money and by EXP calculation |
| HP/MaxHP (offsets 33-36) | Must be > 0 so Ditto survives to move |
| DVs (offsets 17-19) | Affects Hidden Power type if relevant; max is safe |
| Moves (offsets 2-5) | TRANSFORM so AI has something to use (enemy PP is unlimited in GSC) |

Everything else (Item, ID, Exp, EVs, Personality, PP, Happiness, PkRS, CaughtData, Status, Stats after MaxHP) can be zero — Transform replaces them before they matter.

```python
def _build_dummy_party_mon(level: int) -> bytes:
    """Construct a 48-byte party_struct for Ditto at given level.
    
    Most fields are 0 because Ditto's Transform overwrites them.
    """
    buf = bytearray(48)
    buf[0] = 0x54              # Species: DITTO
    buf[2] = TRANSFORM_MOVE_ID # Moves[0]
    buf[17] = 0xFF             # HP/Atk DV (max)
    buf[18] = 0xFF             # Def/Spe DV (max)
    buf[19] = 0xFF             # Sat/Sdf DV (max)
    buf[30] = level            # Level
    # HP/MaxHP: simple formula so mon survives one hit before Transform
    hp = (2 * 48 + 15 + 0) * level // 100 + level + 10  # = ~level + 10 for Ditto base
    buf[33] = hp & 0xFF
    buf[34] = (hp >> 8) & 0xFF
    buf[35] = hp & 0xFF       # MaxHP = HP (no damage yet)
    buf[36] = (hp >> 8) & 0xFF
    return bytes(buf)
```

**Acceptance criteria:**

- Returns exactly 48 bytes
- Species byte is DITTO at offset 0
- Level byte (at offset 30) matches input
- DVs at offsets 17, 18, 19 are 0xFF
- HP at offsets 33-34 is nonzero

---

### Task 6 — Purchase handler + shop item

**File:** `src/game_shops/pkpcrystal.py`

Import `queue_battle_request` from `src.game_hooks.pkpcrystal`.

**Precondition checks:**

```python
controller = purchase_ctx.game_controller
if controller is None:
    return PurchaseComplete(success=False, error_message=...)

pyboy = controller.pyboy
mode = symbol_read_u8(pyboy, "wBattleMode")
script = symbol_read_u8(pyboy, "wScriptRunning")
party = symbol_read_u8(pyboy, "wPartyCount")

if mode != 0:
    return PurchaseComplete(success=False, error_message=...)
if script != 0:
    return PurchaseComplete(success=False, error_message=...)
if party == 0:
    return PurchaseComplete(success=False, error_message=...)
```

**On success:**

```python
queue_battle_request(purchase_ctx.chat_id, purchase_ctx.user_id)
return PurchaseComplete(success=True)
```

**New ShopItem** (add to an existing or new category):

```python
ShopItem(
    "redeem_battle",
    f"{SHOP_PREFIX}.items.redeem_battle",
    <points_cost>,
    {},
    purchase_handler=redeem_battle_handler,
)
```

**Acceptance criteria:**

- Preconditions checked with specific error messages per failure
- On success, cache entry created with state "pending"
- On failure, cache NOT modified

---

### Task 7 — Tests

**File:** `tests/test_battle_injection.py`

| Test                                 | What it verifies                  |
| ------------------------------------ | --------------------------------- |
| `test_cache_create_resolve_remove`   | State machine lifecycle           |
| `test_cache_per_chat_isolation`      | Two chat_ids don't interfere      |
| `test_hook_a_skips_without_cache`    | No-op when no pending request     |
| `test_hook_a_skips_wrong_state`      | No-op when state != "pending"     |
| `test_hook_a_revalidates_state`      | Skips if wBattleMode != 0 etc.    |
| `test_hook_b_skips_without_starting` | No-op for normal trainer battles  |
| `test_hook_b_writes_data`            | Verifies WRAM fields after Hook B |
| `test_hook_b_clears_cache`           | Entry removed after processing    |
| `test_build_dummy_mon`               | 48 bytes, correct species + level |
| `test_script_bytes`                  | 3 bytes = 0x5E, 0x5F, 0x8F        |

---

## Script engine flow (detailed)

```
frame N+0:
  MapEvents
    PlayerEvents → Hook A fires
      ├─ cache lookup, re-validate
      ├─ write 3 bytes to WRAM0: 5E 5F 8F
      ├─ hScriptPos = WRAM0_addr
      ├─ hScriptBank = 0
      ├─ wScriptRunning = 1
      ├─ wOtherTrainerClass = 1
      └─ return
    PlayerEvents checks wScriptRunning=1 → ret nz (early exit)
    ScriptEvents
      ├─ GetScriptByte → 0x5E
      └─ Script_startbattle
           ├─ call BufferScreen
           └─ predef StartBattle
                ├─ BattleIntro
                │   ├─ LoadTrainerOrWildMonPic (YOUNGSTER pic)
                │   ├─ ...setup...
                │   └─ InitEnemy
                │        ├─ wTrainerClass = wOtherTrainerClass
                │        ├─ farcall GetTrainerAttributes
                │        ├─ farcall ReadTrainerParty → Hook B fires
                │        │   ├─ cache state=starting?
                │        │   ├─ PC = ReadTrainerParty.return
                │        │   ├─ write custom team to WRAM
                │        │   ├─ set processing vars
                │        │   └─ clear cache
                │        ├─ farcall ComputeTrainerReward (reads wCurPartyLevel)
                │        └─ ...load pic, set wBattleMode=2
                ├─ InitBattleDisplay
                └─ BattleStartMessage

frames N+1 ... N+M:
  DoBattle runs in halt-driven loop, VBlank each frame

frame N+M+1:
  ExitBattle → wBattleMode=0, wOtherTrainerClass=0
  predef StartBattle returns
  Script_startbattle returns

frame N+M+1 (same frame, ScriptEvents continues):
  ScriptEvents: GetScriptByte → 0x5F → Script_reloadmapafterbattle
    ├─ post-battle cleanup
    ├─ wMapStatus = 1 (MAPSTATUS_START)
    └─ StopScript → wScriptRunning = 0

frame N+M+2:
  MapEvents → PlayerEvents (wBattleMode=0, wScriptRunning=0, normal)
  MapEvents checks wMapStatus → map reload triggered
  Player back in overworld at last position
```

## Risks and edge cases

| Risk                                                                                | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Player's party is empty at Hook A time                                              | Re-validation check: `wPartyCount > 0`. Entry stays `pending`, retries.                                                                                                                                                                                                                                                                                                                                                                  |
| Player enters another battle between purchase and Hook A                            | Re-validation: `wBattleMode == 0`. Fail-safe.                                                                                                                                                                                                                                                                                                                                                                                            |
| A script is running between purchase and Hook A                                     | Re-validation: `wScriptRunning == 0`. Fail-safe.                                                                                                                                                                                                                                                                                                                                                                                         |
| WRAMX bank wrong when writing enemy party data                                      | Always set SVBK (`$FF70`) to 1 before WRAMX writes                                                                                                                                                                                                                                                                                                                                                                                       |
| HRAM writes fail with tuple form                                                    | Verify `pyboy.memory[(0, addr)] = value` works for HRAM ($FF00-$FFFE)                                                                                                                                                                                                                                                                                                                                                                    |
| ReadTrainerParty.return is a `ret` that doesn't properly clean up the farcall stack | Verify by inspecting `0x4137` in bank 7 — if it's a `ret` used internally by ReadTrainerParty (not the farcall return stub), the farcall return mechanism won't execute and the bank won't be restored. **Fix:** use `symbol_lookup("ComputeTrainerReward")` as the jump target instead — it's the instruction immediately after `farcall ReadTrainerParty` in InitEnemy, and the farcall return will handle bank restoration naturally. |
| `wScriptMode` needs to be set                                                       | ScriptEvents checks `wScriptRunning`, not `wScriptMode`. Default value of `wScriptMode` should be 0 (SCRIPT_OFF) which is fine as long as it's not a stale value. Set to 0 explicitly if needed.                                                                                                                                                                                                                                         |

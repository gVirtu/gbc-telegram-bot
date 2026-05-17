# Custom Trainer Battle Injection — Design

## Problem

Players earn points through gameplay and redeem them in a shop. One new class of reward will be a "trainer battle" — the player purchases a battle token, and the bot initiates a programmed battle with a custom enemy team. After the battle ends, the player returns to wherever they were in the overworld.

The constraint: the bot runs a headless Game Boy emulator (PyBoy) that does not have write access to the ROM. All game state manipulation happens at runtime through emulator memory access and hooks (function-call intercepts at symbol addresses).

## Design overview

```
Purchase handler        → cache[chat_id] = pending
                              ↓ (next emulator tick)
Hook A @ PlayerEvents   → inject 3-byte script + trainer data
                              ↓ (script engine → predef StartBattle)
Hook B @ ReadTrainerParty.return → overwrite custom team
                              ↓ (script engine continues)
reloadmapafterbattle    → StopScript → overworld resumes
```

Three components, two hook points, one in-memory cache entry. The battle runs through the game's own battle engine — no custom battle loop, no state restoration after the battle ends.

## Key decisions

### 1. Script engine injection (not PC redirect)

**Decision:** Hook A sets `wScriptRunning = 1` and points the script engine (`hScriptPos`) at 3 bytes of script bytecode written to WRAM:

```
0x5E  → startbattle
0x5F  → reloadmapafterbattle
0x8F  → end
```

The overworld's normal `ScriptEvents` function reads these bytes on the next frame and dispatches through the game's script command handlers.

**Why not PC redirect:** Redirecting the program counter to `StartBattle` requires switching ROM banks ($25 → $0f). After the battle, the return address on the stack points back to code in bank $25, but the wrong bank is active. Fixing this requires either a WRAM trampoline (15 bytes: switch bank → call → restore bank → ret) or stack manipulation with farcall return stubs. Both add complexity and fragility. The script engine already handles bank switching through its existing `predef`/`farcall` infrastructure — using it costs zero additional machinery.

**Why this is safe:** The game's `PlayerEvents` function (where Hook A fires) gates on `wScriptRunning` — if nonzero, it returns immediately. So setting `wScriptRunning = 1` in Hook A naturally prevents the rest of `PlayerEvents` from running on the same frame. Immediately after, `ScriptEvents` runs (called from `MapEvents`, same frame) and picks up the script. No re-entry, no race.

**WRAM as script source:** The script reading function `GetScriptByte` reads from `hScriptBank`:`hScriptPos` via `rst Bankswitch`. For ROM addresses ($0000-$7FFF), this switches the visible bank. For WRAM addresses ($C000-$FFFF), `rst Bankswitch` is a no-op — it only affects the ROM window ($4000-$7FFF). So a script in WRAM is read correctly regardless of `hScriptBank`'s value.

### 2. Two-hook design: PlayerEvents + ReadTrainerParty.return

**Decision:** Two hooks, one at `PlayerEvents` (trigger + state setup) and one at `ReadTrainerParty.return` (data override).

**Hook A @ PlayerEvents** is the trigger point. `PlayerEvents` runs every overworld frame at the start of `MapEvents`, before `ScriptEvents`. This gives us a guaranteed ordering: Hook A fires, sets up the script + data, then `ScriptEvents` reads the script on the same frame.

**Hook B @ ReadTrainerParty.return** fires immediately after `ReadTrainerParty` finishes loading a ROM trainer's team into `wOTPartyMons`. The hook overwrites the just-loaded data with our custom team. `ReadTrainerParty` runs normally — the hook fires at `.return`, after the function body, so the farcall return mechanism handles all bank switching naturally.

**Why hook at `.return` instead of the entry:** The original design hooked at `ReadTrainerParty` entry and redirected PC to `.return` to skip the function body. Hooking at `.return` directly eliminates the PC redirect entirely. If the cache state is wrong (normal trainer battle), ReadTrainerParty loaded the real ROM team into `wOTPartyMons` — the player gets a normal YOUNGSTER fight as a safe fallback. No redirect to go wrong.

**Why two hooks instead of one:** A single hook at `PlayerEvents` that writes the team data AND triggers the battle would have its data overwritten by `ReadTrainerParty` during `InitEnemy` (which runs inside `BattleIntro`, called from `predef StartBattle`). The second hook ensures our custom data arrives after `ReadTrainerParty` would have overwritten it.

### 3. Cache state machine (pending → starting → deleted)

**Decision:** A plain Python `dict[chat_id, dict]` with two states.

The cache decouples the purchase handler (async, runs in the shop flow) from the hooks (synchronous, run during emulator ticks). Both execute on the same asyncio event loop thread — no locking needed.

**State transitions:**

- `pending`: Set by the purchase handler after validation. Means "check player state and start battle when possible."
- `starting`: Set by Hook A just before the battle begins. Means "Hook B should expect this battle and override data."
- (deleted): Set by Hook B as it writes the custom team. Means "battle is in progress under the engine's control; no further cache operations needed."

**Why not a single flag:** The two states prevent race conditions. `pending` survives across frames — the player might not be in valid overworld state when the purchase completes, and Hook A re-validates before transitioning. `starting` distinguishes "our battle" from a normal trainer battle at Hook B time.

### 4. Precondition validation at two stages

**Decision:** Validate at purchase time AND at Hook A time.

| Check                 | Purchase handler | Hook A |
| --------------------- | ---------------- | ------ |
| `wBattleMode == 0`    | Yes              | Yes    |
| `wScriptRunning == 0` | Yes              | Yes    |
| `wPartyCount > 0`     | Yes              | Yes    |

Purchase-time validation gives immediate feedback to the user ("you can't buy a battle right now"). Hook A re-validation catches the window between purchase and execution where the player might have entered a battle, walked into a Pokécenter, or released their last Pokémon.

If Hook A finds invalid state, the cache entry stays `pending` and retries on the next frame. No error is surfaced — the battle starts automatically when the player next returns to valid overworld state.

### 5. ReadTrainerParty.return as hook point (not entry)

**Decision:** Hook B is registered on `ReadTrainerParty.return` (bank $07, address $4137), not on `ReadTrainerParty` entry.

`ReadTrainerParty.return` is the label at the end of `ReadTrainerParty`'s function body. When the hook fires at this address:

- `ReadTrainerParty` has already loaded the ROM trainer's team into `wOTPartyMons`
- We are still in bank $07, inside the farcall that called `ReadTrainerParty`
- The `ret` instruction at `.return` will return to the farcall stub, which restores the caller's bank ($0f) and returns to `InitEnemy`

The hook overwrites the just-loaded ROM data with our custom team. Since both entry and `.return` are in the same bank, no bank switching is needed anywhere.

**Why this is better than the entry-skip approach:** The original design hooked at `ReadTrainerParty` entry and redirected PC to `.return`. This skips the function body — meaning for our battle, `ReadTrainerParty` never executes. Hooking at `.return` instead means:

- No PC redirect (no risk of breaking the farcall return path)
- `ReadTrainerParty` runs normally as the game expects
- If our cache is in the wrong state (normal trainer battle, or a stale entry), `ReadTrainerParty` already loaded the real ROM team — the player gets a normal YOUNGSTER fight as a safe fallback
- One less thing that can go wrong

### 6. Ditto as test mon

**Decision:** The MVP dummy team is a single Ditto at the player's lead level.

Ditto's Transform copies the opponent's stats, moves, and type on turn 1. This means:

- No move balancing needed (Transform uses the opponent's moves)
- No stat calculation needed (Transform copies stats)
- The battle is always winnable regardless of player level (Ditto becomes the player's mon)
- The battle resolves quickly

The level is set to the player's lead mon's level so that EXP rewards are proportional.

### 7. Custom team struct: full 48-byte fill

**Decision:** Construct the full 48-byte `party_struct` in Python, write it to `wOTPartyMon1` in Hook B.

`ReadTrainerParty` runs normally and calls `TryAddMonToParty` for each mon — that function computes moves from level-up learnset, sets default DVs, calculates stats from base stats + DVs + EVs + level, and fills OT name/ID. Hook B fires after this completes and overwrites `wOTPartyMon1` with our custom team. The normal data is replaced.

`SendInUserPkmn` (called during `DoBattle`) copies the struct verbatim into `wEnemyMon` with no recalculation:

```asm
ld bc, MON_ID - MON_SPECIES
rst CopyBytes           ; species, item, moves
ld bc, MON_PKRUS - MON_DVS
rst CopyBytes           ; DVs, personality, PP, happiness
ld bc, PARTYMON_STRUCT_LENGTH - MON_LEVEL
rst CopyBytes           ; level, status, HP, stats
```

Zero HP = fainted mon before battle starts. The struct must have correct values for species, level, DVs, moves, and HP. Everything else can be zero — Ditto's Transform overwrites stats and type on turn 1.

### 8. Symbol-based WRAM access

**Decision:** All WRAM reads and writes use `pyboy.symbol_lookup("symbol_name")` — never absolute addresses.

The ROM's `.sym` file maps every named label to a `(bank, address)` tuple. Using symbol names means:

- Address changes across ROM versions are handled automatically
- Code is self-documenting ("what is at $D233?" → `wBattleMode`)
- Read helpers (`symbol_read_u8`, `symbol_read_u16le`) already exist in `src/game_utils/pkpcrystal/reader.py`

For writes: `pyboy.memory[symbol_lookup("wBattleMode")] = value`. For WRAMX symbols (bank 1 at $Dxxx), the SVBK register ($FF70) must be set to 1 before writing.

### 9. HRAM access for script engine pointers

**Decision:** `hScriptPos` and `hScriptBank` (in HRAM at $FFEB-$FFEE) are written via their symbol names.

HRAM ($FF80-$FFFE) is accessible via `pyboy.memory[(0, addr)]` with bank 0. These are set by Hook A before returning — `hScriptPos` points to the WRAM0 location of the 3-byte script, `hScriptBank` is set to 0 (doesn't matter for WRAM scripts but set for safety).

## Alternatives considered

### Trampoline in WRAM (rejected)

Write a 15-byte routine to an unused WRAM0 area that switches to bank $0f, calls `StartBattle`, restores bank $25, and returns. Set PC to the trampoline address from Hook A.

Rejected because: The script engine approach achieves the same goal with zero extra code — just 3 bytes of bytecode data instead of a 15-byte executable trampoline. Both require a free WRAM area; the script approach uses less and integrates with the game's existing flow.

### Single hook at PlayerEvents (rejected)

Set all data + trigger battle in one hook. ReadTrainerParty overwrites the custom team with ROM data.

Rejected because: Hook B is necessary to prevent the ROM-data overwrite. The data written in Hook A would be destroyed before the battle uses it.

### ReadTrainerParty entry skip with PC redirect (rejected)

Hook at `ReadTrainerParty` entry, redirect PC to `.return` to skip the function body. Write custom team directly without ReadTrainerParty ever running.

Rejected because: Hooking at `.return` is safer — no PC redirect, no risk of breaking the farcall return path. ReadTrainerParty emits a safe fallback (real YOUNGSTER team) if the cache state is wrong. The entry-skip approach has an extra failure mode for no benefit.

### Dummy mon with a damaging move (viable but worse)

Instead of Ditto, use a mon with a real moveset (e.g., Magikarp with Tackle).

Rejected because: Ditto's Transform ensures the battle is always winnable and fast. The opponent becomes a mirror of the player's mon — the fight depends on the player's own team strength. A fixed mon with fixed moves would be trivially beatable at high levels or frustratingly hard at low levels.

## Data flow

```
                    Purchase handler
                          │
                    cache[chat_id] = pending
                          │
              ┌───────────┴───────────┐
              │   (next emulator tick) │
              │       Hook A fires     │
              │       re-validate      │
              │      (invalid → skip)  │
              └───────────┬───────────┘
                          │
                    ┌─────┴─────┐
                    │ Set state │
                    │  starting │
                    │           │
                    │ Write     │
                    │ 3-byte    │
                    │ script to │
                    │ WRAM0     │
                    │           │
                    │ Set       │
                    │ wScript-  │
                    │ Running=1 │
                    │ hScriptPos│
                    │ wOther-   │
                    │ Trainer-  │
                    │ Class=1   │
                    └─────┬─────┘
                          │
                    PlayerEvents sees
                    wScriptRunning=1
                    → ret nz
                          │
                    ScriptEvents reads
                    0x5E (startbattle)
                          │
                    predef StartBattle
                          │
                    BattleIntro
                          │
                    InitEnemy
                          │
                    farcall ReadTrainerParty
                          │
                    ─── ReadTrainerParty runs ───
                    (loads ROM trainer team into
                     wOTPartyMons)
                          │
                    ReadTrainerParty.return
                          │
                    ┌─────┴─────┐
                    │ Hook B    │
                    │ fires     │
                    │           │
                    │ state ==  │
                    │ starting? │
                    │           │
                    │ Overwrite │
                    │ wOTParty- │
                    │ Mons with │
                    │ custom    │
                    │ team      │
                    │           │
                    │ del cache │
                    └─────┬─────┘
                          │
                    farcall return stub
                    restores bank $0f
                    ComputeTrainerReward
                    Set wBattleMode=2
                          │
                    BattleIntro continues
                    InitBattleDisplay
                    BattleStartMessage
                          │
                    DoBattle
                    (many frames)
                          │
                    ExitBattle
                    wBattleMode=0
                    wOtherTrainerClass=0
                          │
                    ScriptEvents reads
                    0x5F → reloadmapafterbattle
                    0x8F → end → StopScript
                          │
                    Overworld resumes
```

## State machine

```
                ┌──────────┐
                │  absent  │
                └─────┬────┘
                      │ queue_battle_request()
                      ▼
                ┌──────────┐
                │ pending  │ ← re-validation fails, retries next frame
                └─────┬────┘
                      │ Hook A: player valid, inject script
                      ▼
                ┌──────────┐
                │ starting │ ← Hook B will override ReadTrainerParty
                └─────┬────┘
                      │ Hook B: skip RTP, write custom team
                      ▼
                ┌──────────┐
                │ (absent) │ ← battle in progress, no more cache ops
                └──────────┘
```

## Dependencies

- PyBoy symbol lookup (`pyboy.symbol_lookup()`) for both ROM and WRAM addresses
- PyBoy memory read/write (`pyboy.memory[...]`) for WRAM0, WRAMX, and HRAM
- PyBoy hook registration (`pyboy.hook_register()` / `pyboy.hook_deregister()`)
- The ROM's `.sym` file must contain `PlayerEvents`, `ReadTrainerParty`, `ReadTrainerParty.return`, and all WRAM symbols
- The Polished Crystal ROM (PKPCRYSTAL) — the script bytecodes ($5E, $5F, $8F) and the startbattle/reloadmapafterbattle handlers are version-specific
- The `begin_hooks`/`end_hooks` lifecycle in `GameController` (hooks must be cleaned up between input batches)

## Future considerations

- **Permanent custom team data:** The dummy Ditto team is hardcoded for the MVP. A real implementation would accept custom team parameters from the shop item configuration (species, level, moves, item, EVs, DVs).
- **Post-battle rewards:** The current design gives no reward for winning — the battle IS the reward. Future versions might give money, items, or captured Pokémon.
- **NPC trainer sprite selection:** Currently hardcoded to class 1 (YOUNGSTER). A shop item could specify which trainer class sprite to use, reusing the existing avatar infrastructure.
- **DB-backed requests:** The in-memory cache is ephemeral (lost on restart). Moving to a database would persist pending battle requests across restarts and allow refund logic for expired requests.
- **TryAddMonToParty invocation:** Instead of filling the 48-byte struct manually, future versions could call `TryAddMonToParty` from the hook by setting up registers and jumping to it. This would let the engine compute moves, DVs, and stats naturally from just species + level.

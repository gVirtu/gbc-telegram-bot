from src.game_utils.pkpcrystal.charmap import CHARMAP, NAME_LENGTH

def symbol_read_u8(pyboy, symbol: str) -> int:
    return pyboy.memory[pyboy.symbol_lookup(symbol)]

def symbol_read_u16le(pyboy, symbol: str) -> int:
    bank, addr = pyboy.symbol_lookup(symbol)
    return read_u16le(pyboy, bank, addr)

def symbol_read_u24le(pyboy, symbol: str) -> int:
    bank, addr = pyboy.symbol_lookup(symbol)
    return read_u24le(pyboy, bank, addr)

def read_u8(pyboy, bank, addr):
    return pyboy.memory[bank, addr]

def read_u16(pyboy, bank, addr):
    [lo, hi] = pyboy.memory[bank, addr:addr+2]
    return lo | (hi << 8)

def read_u16le(pyboy, bank, addr):
    [hi, lo] = pyboy.memory[bank, addr:addr+2]
    return lo | (hi << 8)

def read_u24le(pyboy, bank, addr):
    [hi, mi, lo] = pyboy.memory[bank, addr:addr+3]
    return lo | (mi << 8) | (hi << 16)

def get_nth_string_addr(pyboy, bank, addr, n):
    ptr = addr

    if n == 0:
        return ptr

    remaining = n

    while remaining > 0:
        if pyboy.memory[(bank, ptr)] == 0x53:
            remaining -= 1
        ptr += 1

    return ptr
    

def decode_text(pyboy, bank, addr, max_len = 2_147_483_647):
    text = []
    for _ in range(max_len):
        c = pyboy.memory[(bank, addr)]

        if c == 0x53:  # @ string terminator
            break

        text.append(CHARMAP.get(c, " "))
        addr += 1
    return "".join(text)


def get_pokemon_name(pyboy, species_id):
    bank, pokemon_base_addr = pyboy.symbol_lookup("PokemonNames")
    pokemon_name_ptr = pokemon_base_addr + (species_id * 10)
    pokemon_name = decode_text(pyboy, bank, pokemon_name_ptr, max_len=10)
    return pokemon_name

def get_pokemon_catch_rate(pyboy, species_id):
    bank, pokemon_base_addr = pyboy.symbol_lookup("BaseData")
    base_stats_width = 34
    base_catch_rate_offset = 8
    pokemon_base_stats_ptr = pokemon_base_addr + ((species_id - 1) * base_stats_width)
    return read_u8(pyboy, bank, pokemon_base_stats_ptr + base_catch_rate_offset)

def get_trainer_class_name(pyboy, class_id):
    trainer_class_names_bank, trainer_class_names_base_addr = pyboy.symbol_lookup("TrainerClassNames")
    trainer_class_name_addr = get_nth_string_addr(pyboy, trainer_class_names_bank, trainer_class_names_base_addr, class_id - 1)
    trainer_class_name = decode_text(pyboy, trainer_class_names_bank, trainer_class_name_addr)
    return trainer_class_name

def get_trainer_class_name_raw(pyboy, class_id):
    trainer_class_names_bank, trainer_class_names_base_addr = pyboy.symbol_lookup("TrainerClassNames")
    trainer_class_name_addr = get_nth_string_addr(pyboy, trainer_class_names_bank, trainer_class_names_base_addr, class_id - 1)

    text = []
    addr = trainer_class_name_addr

    for _ in range(NAME_LENGTH):
        c = pyboy.memory[(trainer_class_names_bank, addr)]

        if c == 0x53:  # @ string terminator
            break

        text.append(c)
        addr += 1

    return text


# ── Name table lookups ──────────────────────────────────────────

BASEDATA_STRIDE = 34
BASEDATA_GENDER = 12
BASEDATA_ABILITIES = 13
BASEDATA_TMHM = 20
TMHM_BYTES = 14
GENDER_UNKNOWN_NYBBLE = 15

PARTYMON_STRUCT_LENGTH = 48
P_ITEM = 1
P_MOVES = 2
P_EVS = 11
P_PERSONALITY = 20
P_LEVEL = 31

SHINY_MASK = 0x80
ABILITY_MASK = 0x60
ABILITY_1 = 0x20
ABILITY_2 = 0x40
HIDDEN_ABILITY = 0x60
NATURE_MASK = 0x1F
GENDER_MASK = 0x80
IS_EGG_MASK = 0x40
GENDER_MALE = 0x00
GENDER_FEMALE = 0x80


def get_item_name(pyboy, item_id):
    if item_id == 0:
        return None
    bank, base_addr = pyboy.symbol_lookup("ItemNames")
    addr = get_nth_string_addr(pyboy, bank, base_addr, item_id)
    return decode_text(pyboy, bank, addr)


def get_move_name(pyboy, move_id):
    if move_id == 0:
        return None
    bank, base_addr = pyboy.symbol_lookup("MoveNames")
    addr = get_nth_string_addr(pyboy, bank, base_addr, move_id - 1)
    return decode_text(pyboy, bank, addr)


def get_ability_name(pyboy, ability_id):
    if ability_id == 0:
        return None
    bank, base_addr = pyboy.symbol_lookup("AbilityNames")
    ptr = read_u16(pyboy, bank, base_addr + (ability_id) * 2)
    return decode_text(pyboy, bank, ptr)


def get_nature_name(pyboy, nature_id):
    if nature_id >= 25:
        return None
    bank, base_addr = pyboy.symbol_lookup("NatureNames")
    entry_addr = base_addr + nature_id
    offset = read_u8(pyboy, bank, entry_addr)
    return decode_text(pyboy, bank, entry_addr + offset)


def get_species_abilities(pyboy, species_id):
    bank, base_addr = pyboy.symbol_lookup("BaseData")
    entry = base_addr + ((species_id - 1) * BASEDATA_STRIDE)
    return [
        read_u8(pyboy, bank, entry + BASEDATA_ABILITIES),
        read_u8(pyboy, bank, entry + BASEDATA_ABILITIES + 1),
        read_u8(pyboy, bank, entry + BASEDATA_ABILITIES + 2),
    ]


def is_species_genderless(pyboy, species_id):
    bank, base_addr = pyboy.symbol_lookup("BaseData")
    entry = base_addr + ((species_id - 1) * BASEDATA_STRIDE)
    gender_byte = read_u8(pyboy, bank, entry + BASEDATA_GENDER)
    return (gender_byte >> 4) == GENDER_UNKNOWN_NYBBLE


def get_species_learnset(pyboy, species_id: int) -> list[tuple[int, int]]:
    """Return list of (level, move_id) for a species' level-up learnset from EvosAttacks."""
    bank, ptr_table = pyboy.symbol_lookup("EvosAttacksPointers")
    entry_addr = ptr_table + (species_id - 1) * 2
    data_addr = read_u16(pyboy, bank, entry_addr)

    addr = data_addr
    while read_u8(pyboy, bank, addr) != 0xFF:
        addr += 1
    addr += 1

    learnset = []
    while True:
        level = read_u8(pyboy, bank, addr)
        if level == 0xFF:
            break
        move_id = read_u8(pyboy, bank, addr + 1)
        learnset.append((level, move_id))
        addr += 2

    return learnset


def get_species_tmhm_moves(pyboy, species_id: int) -> list[int]:
    """Return list of move_ids the species can learn via TM/HM, from BaseData bitmask."""
    bank, base_addr = pyboy.symbol_lookup("BaseData")
    entry = base_addr + ((species_id - 1) * BASEDATA_STRIDE)
    bitmask = [read_u8(pyboy, bank, entry + BASEDATA_TMHM + i) for i in range(TMHM_BYTES)]

    tmhm_bank, tmhm_addr = pyboy.symbol_lookup("TMHMMoves")

    moves = []
    for byte_idx in range(TMHM_BYTES):
        bits = bitmask[byte_idx]
        for bit in range(8):
            if bits & (1 << bit):
                tmnum = byte_idx * 8 + bit
                move_id = read_u8(pyboy, tmhm_bank, tmhm_addr + tmnum)
                if move_id != 0:
                    moves.append(move_id)

    return moves


def get_species_egg_moves(pyboy, species_id: int) -> list[int]:
    """Return list of move_ids the species can learn as egg moves."""
    bank, ptr_table = pyboy.symbol_lookup("EggSpeciesMovesPointers")
    entry_addr = ptr_table + (species_id - 1) * 2
    data_addr = read_u16(pyboy, bank, entry_addr)

    addr = data_addr + 2

    moves = []
    while True:
        move_id = read_u8(pyboy, bank, addr)
        if move_id == 0xFF:
            break
        moves.append(move_id)
        addr += 1

    return moves


# ── Party member reads ───────────────────────────────────────────

def _party_mon_addr(pyboy, slot):
    bank, addr = pyboy.symbol_lookup(f"wPartyMon{slot}")
    return bank, addr


def read_party_mon_species(pyboy, slot):
    return symbol_read_u8(pyboy, f"wPartyMon{slot}Species")


def read_party_mon_level(pyboy, slot):
    return symbol_read_u8(pyboy, f"wPartyMon{slot}Level")


def read_party_mon_item(pyboy, slot):
    return symbol_read_u8(pyboy, f"wPartyMon{slot}Item")


def read_party_mon_moves(pyboy, slot):
    bank, addr = _party_mon_addr(pyboy, slot)
    return [read_u8(pyboy, bank, addr + P_MOVES + i) for i in range(4)]


def read_party_mon_evs(pyboy, slot):
    bank, addr = _party_mon_addr(pyboy, slot)
    return [read_u8(pyboy, bank, addr + P_EVS + i) for i in range(6)]


def read_party_mon_personality(pyboy, slot):
    bank, addr = _party_mon_addr(pyboy, slot)
    return (
        read_u8(pyboy, bank, addr + P_PERSONALITY),
        read_u8(pyboy, bank, addr + P_PERSONALITY + 1),
    )


def get_party_mon_nickname(pyboy, slot):
    bank, addr = pyboy.symbol_lookup(f"wPartyMon{slot}Nickname")
    return decode_text(pyboy, bank, addr, max_len=11)


# ── Byte-level party struct parsing ──────────────────────────────

def parse_party_struct(data: bytes):
    return {
        "species_id": read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, 0),
        "item_id": read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, P_ITEM),
        "move_ids": [data[P_MOVES + i] for i in range(4)],
        "personality": (
            read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, P_PERSONALITY),
            read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, P_PERSONALITY + 1),
        ),
        "level": read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, P_LEVEL),
        "evs": [read_u8_from_bytes(data, PARTYMON_STRUCT_LENGTH, P_EVS + i) for i in range(6)],
    }


def _read_u8_from_bytes(data: bytes, expected_len: int, offset: int) -> int:
    if len(data) != expected_len:
        raise ValueError(f"Expected {expected_len} bytes, got {len(data)}")
    return data[offset]


# Alias for readability
read_u8_from_bytes = _read_u8_from_bytes


# ── Box / savemon_struct reads (SRAM) ────────────────────────────

SAVEMON_STRUCT_LENGTH = 49
S_SPECIES = 0
S_ITEM = 1
S_MOVES = 2
S_EVS = 11
S_PERSONALITY = 20
S_LEVEL = 28
S_NICKNAME = 32

NEWBOX_ENTRIES = 0
NEWBOX_BANKS = 20
NEWBOX_NAME = 23
NEWBOX_STRIDE = 33

MONS_PER_BOX = 20
NUM_BOXES = 20
MONDB_ENTRIES_A = 167
MONDB_ENTRIES_B = 28
MONDB_ENTRIES_C = 12


def read_box_count(pyboy, box_index: int) -> int:
    bank, addr = pyboy.symbol_lookup(f"sNewBox{box_index + 1}Entries")
    count = 0
    for i in range(MONS_PER_BOX):
        if pyboy.memory[(bank, addr + i)] != 0:
            count += 1
    return count


def read_box_name(pyboy, box_index: int) -> str:
    bank, addr = pyboy.symbol_lookup(f"sNewBox{box_index + 1}Name")
    return decode_text(pyboy, bank, addr, max_len=9)


def _get_box_entry_and_bank(pyboy, box_index: int, slot: int) -> tuple[int, int]:
    entries_bank, entries_addr = pyboy.symbol_lookup(f"sNewBox{box_index + 1}Entries")
    banks_bank, banks_addr = pyboy.symbol_lookup(f"sNewBox{box_index + 1}Banks")

    pokedb_index = pyboy.memory[(entries_bank, entries_addr + slot)]
    if pokedb_index == 0:
        return (0, 0)

    flag_byte = pyboy.memory[(banks_bank, banks_addr + slot // 8)]
    bank_group = 1 + ((flag_byte >> (slot % 8)) & 1)
    return (pokedb_index, bank_group)


def _get_savemon_addr(pyboy, pokedb_index: int, bank_group: int) -> tuple[int, int]:
    if pokedb_index < MONDB_ENTRIES_A:
        entry_within = pokedb_index
        base_symbol = f"sBoxMons{bank_group}A"
    elif pokedb_index < MONDB_ENTRIES_A + MONDB_ENTRIES_B:
        entry_within = pokedb_index - MONDB_ENTRIES_A
        base_symbol = f"sBoxMons{bank_group}B"
    else:
        entry_within = pokedb_index - MONDB_ENTRIES_A - MONDB_ENTRIES_B
        base_symbol = f"sBoxMons{bank_group}C"

    base_bank, base_addr = pyboy.symbol_lookup(base_symbol)
    return base_bank, base_addr + entry_within * SAVEMON_STRUCT_LENGTH


def decode_savemon_text(pyboy, sram_bank: int, addr: int, max_len: int = 10) -> str:
    """Decode a nickname from a savemon_struct in SRAM (PokeDB).

    Savemon nicknames use a reversible 7-bit encoding to ensure all bytes
    stay in the 0x00-0x7F range (bit 7 = 0), allowing the high bit of each
    byte to be repurposed for a 16-bit checksum stored across the nickname+OT
    region (see EncodeTempMon / DecodeTempMon in engine/pc/bills_pc.asm).

    Encoding scheme (what the game does before writing to SRAM):
      - 0x7F (space)  -> 0x7A
      - 0x53 (@)      -> 0x7B
      - 0x00 (<START>) -> 0x7C
      - Everything else -> byte & 0x7F   (clear bit 7)

    This function reverses it:
      - 0x7A -> 0x7F (space)
      - 0x7B -> 0x53 (@)  — also used as string terminator (break)
      - 0x7C -> 0x00 (<START>)
      - Everything else -> byte | 0x80  (restore bit 7)

    The decoded bytes are then mapped through CHARMAP to readable text.
    """
    raw = []
    for _ in range(max_len):
        b = pyboy.memory[(sram_bank, addr)]
        if b == 0x7B:
            break
        if b == 0x7A:
            raw.append(0x7F)
        elif b == 0x7C:
            raw.append(0x00)
        else:
            raw.append(b | 0x80)
        addr += 1
    return decode_text_from_bytes(raw)


def decode_text_from_bytes(raw: list[int]) -> str:
    text = []
    for b in raw:
        text.append(CHARMAP.get(b, " "))
    return "".join(text)


def read_box_mon_raw(pyboy, box_index: int, slot: int) -> dict | None:
    pokedb_index, bank_group = _get_box_entry_and_bank(pyboy, box_index, slot)
    if pokedb_index == 0:
        return None

    sram_bank, addr = _get_savemon_addr(pyboy, pokedb_index - 1, bank_group)

    species_id = pyboy.memory[(sram_bank, addr + S_SPECIES)]
    item_id = pyboy.memory[(sram_bank, addr + S_ITEM)]
    move_ids = [pyboy.memory[(sram_bank, addr + S_MOVES + i)] for i in range(4)]
    p1 = pyboy.memory[(sram_bank, addr + S_PERSONALITY)]
    p2 = pyboy.memory[(sram_bank, addr + S_PERSONALITY + 1)]
    level = pyboy.memory[(sram_bank, addr + S_LEVEL)]
    evs_raw = [pyboy.memory[(sram_bank, addr + S_EVS + i)] for i in range(6)]
    nickname = decode_savemon_text(pyboy, sram_bank, addr + S_NICKNAME, max_len=10)

    return {
        "species_id": species_id,
        "item_id": item_id,
        "move_ids": move_ids,
        "p1": p1,
        "p2": p2,
        "level": level,
        "evs_raw": evs_raw,
        "nickname": nickname,
    }
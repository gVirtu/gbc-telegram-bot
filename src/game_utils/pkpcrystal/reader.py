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
GENDER_UNKNOWN_NYBBLE = 15

PARTYMON_STRUCT_LENGTH = 48
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
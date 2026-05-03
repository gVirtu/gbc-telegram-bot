from src.game_utils.pkpcrystal.charmap import CHARMAP

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
from contextlib import contextmanager


@contextmanager
def wramx_bank(pyboy, bank: int = 1):
    old_svbk = pyboy.memory[0xFF70]
    pyboy.memory[0xFF70] = bank
    try:
        yield
    finally:
        pyboy.memory[0xFF70] = old_svbk


def symbol_write_u8(pyboy, symbol: str, value: int) -> None:
    pyboy.memory[pyboy.symbol_lookup(symbol)] = value


def write_u8_wram0(pyboy, addr: int, value: int) -> None:
    pyboy.memory[addr] = value


def write_u8(pyboy, bank: int, addr: int, value: int) -> None:
    pyboy.memory[(bank, addr)] = value


def write_u16le_wram0(pyboy, addr: int, value: int) -> None:
    pyboy.memory[addr] = value & 0xFF
    pyboy.memory[addr + 1] = (value >> 8) & 0xFF


def write_u16le(pyboy, bank: int, addr: int, value: int) -> None:
    pyboy.memory[(bank, addr)] = value & 0xFF
    pyboy.memory[(bank, addr + 1)] = (value >> 8) & 0xFF


def write_bytes(pyboy, bank: int, base_addr: int, data: bytes) -> None:
    for i, b in enumerate(data):
        pyboy.memory[(bank, base_addr + i)] = b

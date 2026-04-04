"""Polished Crystal LZ decompression utilities."""

from __future__ import annotations

from dataclasses import dataclass

MAX_FILE_SIZE = 32768
SHORT_COMMAND_COUNT = 32
LOOKBACK_LIMIT = 128

LZ_END = 0xFF

LZ_EXT_MASK = 0xFC
LZ_EXT_BASE = 0xFC
LZ_EXT_PACKHI0 = 0xFC
LZ_EXT_PACK16_SHORT = 0xFD
LZ_EXT_PACKLO0 = 0xFE

LZ_DATA = 0
LZ_REPEAT = 1
LZ_ALTERNATE = 2
LZ_ZERO = 3
LZ_COPY_NORMAL = 4
LZ_COPY_FLIPPED = 5
LZ_COPY_REVERSED = 6
LZ_LONG = 7
LZ_EXT = 7

PACK16_TABLE = (
    0x00, 0xFF, 0x01, 0x02, 0x03, 0xFE, 0x80, 0x07,
    0xC0, 0x7F, 0x04, 0x0F, 0x1F, 0x3F, 0x08, 0xFC,
)

bit_flipped = [
    sum(((byte >> i) & 1) << (7 - i) for i in range(8))
    for byte in range(0x100)
]


def minimum_count(command: int) -> int:
    if command == LZ_REPEAT:
        return 2
    if command in (LZ_ALTERNATE,):
        return 3
    return 1


@dataclass
class _UsedCommand:
    name: str
    length: int
    address: int
    offset: int | None
    cmd_length: int
    direction: int | None


class Decompressed:
    """Interpret and decompress Polished Crystal LZ-compressed data."""

    lz = None
    start = 0
    debug = False

    arg_names = ("lz", "start", "debug")

    def __init__(self, *args, **kwargs):
        self.__dict__.update(dict(zip(self.arg_names, args)))
        self.__dict__.update(kwargs)

        self.address = self.start
        self.output: bytearray = bytearray()
        self.used_commands: list[_UsedCommand] = []
        self.compressed_data = bytearray()

        if self.lz is not None:
            self.decompress()

        if self.debug:
            print(self.command_list())

    def command_list(self) -> str:
        lines = []
        output_address = 0
        for attrs in self.used_commands:
            line = f"{output_address:03x} {attrs.name}: {attrs.length}"
            raw = " ".join(
                f"{byte:02x}"
                for byte in self.lz[attrs.address: attrs.address + attrs.cmd_length]
            )
            if raw:
                line += f"\t{raw}"
            lines.append(line)
            output_address += attrs.length
        return "\n".join(lines)

    def decompress(self, lz=None):
        if lz is not None:
            self.lz = lz

        if self.lz is None:
            raise ValueError("no LZ data provided")

        self.lz = bytearray(self.lz)
        self.address = self.start
        self.output = bytearray()
        self.used_commands = []

        while True:
            cmd_address = self.address
            offset = None
            direction = None

            b0 = self._next()
            if b0 == LZ_END:
                break

            if (b0 & LZ_EXT_MASK) == LZ_EXT_BASE:
                length = self._next() + 1
                name = {
                    LZ_EXT_PACKHI0: "packhi0",
                    LZ_EXT_PACK16_SHORT: "pack16",
                    LZ_EXT_PACKLO0: "packlo0",
                }.get(b0)
                if name is None:
                    raise ValueError(f"unknown extended opcode 0x{b0:02x}")
                self._decompress_ext(b0, length)
            else:
                command = b0 >> 5
                count = b0 & (SHORT_COMMAND_COUNT - 1)
                if command == LZ_LONG:
                    command = count >> 2
                    count = ((count & 0x01) << 8) | self._next()
                length = count + minimum_count(command)

                if command == LZ_DATA:
                    name = "literal"
                    self._write_literal(length)
                elif command == LZ_REPEAT:
                    name = "iterate"
                    self.output.extend([self._next()] * length)
                elif command == LZ_ALTERNATE:
                    name = "alternate"
                    a = self._next()
                    b = self._next()
                    self.output.extend(a if i % 2 == 0 else b for i in range(length))
                elif command == LZ_ZERO:
                    name = "blank"
                    self.output.extend(b"\x00" * length)
                elif command in (LZ_COPY_NORMAL, LZ_COPY_FLIPPED, LZ_COPY_REVERSED):
                    offset = self._read_offset()
                    if command == LZ_COPY_NORMAL:
                        name = "repeat"
                        direction = 1
                        self._copy(length, offset, direction=1, flipped=False)
                    elif command == LZ_COPY_FLIPPED:
                        name = "flip"
                        direction = 1
                        self._copy(length, offset, direction=1, flipped=True)
                    else:
                        name = "reverse"
                        direction = -1
                        self._copy(length, offset, direction=-1, flipped=False)
                else:
                    raise ValueError(f"unknown command {command}")

            if len(self.output) > MAX_FILE_SIZE:
                raise ValueError("decompressed output exceeds MAX_FILE_SIZE")

            self.used_commands.append(
                _UsedCommand(
                    name=name,
                    length=length,
                    address=cmd_address,
                    offset=offset,
                    cmd_length=self.address - cmd_address,
                    direction=direction,
                )
            )

        self.compressed_data = self.lz[self.start:self.address]
        return self.output

    def _write_literal(self, length: int) -> None:
        end = self.address + length
        if end > len(self.lz):
            raise ValueError("truncated literal payload")
        self.output.extend(self.lz[self.address:end])
        self.address = end

    def _decompress_ext(self, opcode: int, length: int) -> None:
        payload_length = (length + 1) // 2
        payload = self._read_bytes(payload_length)

        if opcode == LZ_EXT_PACK16_SHORT:
            remaining = length
            for packed in payload:
                hi = packed >> 4
                lo = packed & 0x0F
                self.output.append(PACK16_TABLE[hi])
                remaining -= 1
                if remaining:
                    self.output.append(PACK16_TABLE[lo])
                    remaining -= 1
            return

        remaining = length
        for packed in payload:
            if opcode == LZ_EXT_PACKHI0:
                self.output.append(packed & 0xF0)
                remaining -= 1
                if remaining:
                    self.output.append((packed & 0x0F) << 4)
                    remaining -= 1
            elif opcode == LZ_EXT_PACKLO0:
                self.output.append(packed >> 4)
                remaining -= 1
                if remaining:
                    self.output.append(packed & 0x0F)
                    remaining -= 1

    def _copy(self, length: int, offset: int, direction: int, flipped: bool) -> None:
        start_len = len(self.output)
        if offset < 0:
            if -offset > start_len:
                raise ValueError("invalid negative copy offset")
            for index in range(length):
                source_index = start_len + offset + index * direction
                if source_index < 0 or source_index >= len(self.output):
                    raise ValueError("copy source out of range")
                value = self.output[source_index]
                self.output.append(bit_flipped[value] if flipped else value)
            return

        if offset >= start_len:
            raise ValueError("invalid absolute copy offset")
        for index in range(length):
            source_index = offset + index * direction
            if source_index < 0 or source_index >= len(self.output):
                raise ValueError("copy source out of range")
            value = self.output[source_index]
            self.output.append(bit_flipped[value] if flipped else value)

    def _read_offset(self) -> int:
        first = self._next()
        if first & LOOKBACK_LIMIT:
            return (LOOKBACK_LIMIT - 1) - first
        return (first << 8) | self._next()

    def _read_bytes(self, length: int) -> bytearray:
        end = self.address + length
        if end > len(self.lz):
            raise ValueError("truncated payload")
        payload = self.lz[self.address:end]
        self.address = end
        return payload

    def _next(self) -> int:
        if self.address >= len(self.lz):
            raise ValueError("unexpected end of input")
        value = self.lz[self.address]
        self.address += 1
        return value

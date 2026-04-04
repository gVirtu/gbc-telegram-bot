"""Tests for the Crystal LZ decompressor (Python 3 port)."""
from src.utils.lz import Decompressed


def test_literal_command():
    # cmd=0 (literal), n=3: byte = (0<<5)|(3-1) = 0x02, then 3 literal bytes, then 0xFF
    data = bytes([0x02, 0xAA, 0xBB, 0xCC, 0xFF])
    assert list(Decompressed(data).output) == [0xAA, 0xBB, 0xCC]


def test_iterate_command():
    # cmd=1 (iterate), n=4: byte = (1<<5)|(4-1) = 0x23, then 1 value byte, then 0xFF
    data = bytes([0x23, 0x55, 0xFF])
    assert list(Decompressed(data).output) == [0x55] * 4


def test_blank_command():
    # cmd=3 (blank), n=2: byte = (3<<5)|(2-1) = 0x61, then 0xFF
    data = bytes([0x61, 0xFF])
    assert list(Decompressed(data).output) == [0x00, 0x00]


def test_alternate_command():
    # cmd=2 (alternate), n=4: byte = (2<<5)|(4-1) = 0x43, then 2 alt bytes, then 0xFF
    data = bytes([0x43, 0xAA, 0xBB, 0xFF])
    assert list(Decompressed(data).output) == [0xAA, 0xBB, 0xAA, 0xBB]


def test_empty_stream():
    assert list(Decompressed(bytes([0xFF])).output) == []

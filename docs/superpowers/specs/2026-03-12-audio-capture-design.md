# Audio Capture — Design Document

**Date:** 2026-03-12
**Status:** Approved

## Overview

Add parallel audio capture to the existing frame-capture cycle in `GameController`. During a capture window (`begin_capture` → tick(s) → `end_capture`), collect per-tick audio arrays from the PyBoy sound emulator and persist them as a WAV file in the chat's media cache directory.

Audio is infrastructure-only for now — it is not sent to Telegram. Future features (audio messages, combined A/V clips) can build on this.

## Design Decisions

### Audio source
`pyboy.sound.ndarray` returns a numpy array of shape `(N, 2)` with dtype `int8` — signed 8-bit stereo samples for the current tick. We copy it each tick (`.copy()`) to avoid stale references.

### Storage format
16-bit stereo WAV at 48 000 Hz (PyBoy's native sample rate). Conversion: `int8 * 256 → int16`. File path: `data/media/{chat_id}/last_audio.wav`, overwritten each capture.

### Enabling audio emulation
`PyBoy(..., sound_emulated=True)` — previously `False`. This adds CPU overhead but is required for audio data.

### Capture lifecycle

| Phase | Action |
|-------|--------|
| `begin_capture()` | Reset `_audio_buffer = []` |
| each `tick()` while `_capturing` | Append `pyboy.sound.ndarray.copy()` |
| `end_capture()` | Copy buffer to `_last_captured_audio`, clear `_audio_buffer` |
| after `end_capture()` | `input_handler` calls `save_last_audio(chat_id, chunks)` |

### What is NOT in scope
- Sending audio to Telegram
- Audio/video muxing
- Compression (MP3, AAC, OGG)
- Per-button audio segmentation

## Files Modified

| File | Change |
|------|--------|
| `src/game.py` | `sound_emulated=True`; `_audio_buffer`, `_last_captured_audio`; audio accumulation in `tick()`; save/clear in `end_capture()`; `get_last_captured_audio()` |
| `src/utils/media_cache.py` | `save_last_audio(chat_id, audio_chunks, sample_rate)` |
| `src/handlers/input_handler.py` | Call `save_last_audio` after `end_capture()` |
| `tests/test_game.py` | Audio buffer tests |
| `tests/test_media_cache.py` | WAV writing tests |

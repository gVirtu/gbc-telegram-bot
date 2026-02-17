"""Game-specific hook modules for PyBoy emulator.

Each module is named after the lowercase cartridge title and exports:
- begin_hooks(pyboy) -> dict: Register hooks, return context
- end_hooks(pyboy, context) -> None: Deregister hooks
"""

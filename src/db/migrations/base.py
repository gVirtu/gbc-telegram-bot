"""Base migration class and utilities."""

from dataclasses import dataclass
from typing import Callable, Optional
import sqlite3


@dataclass
class Migration:
    """Represents a database migration.
    
    Attributes:
        version: The migration version number (positive integer)
        name: The migration name (from filename)
        upgrade: Function to apply the migration (required)
        downgrade: Function to rollback the migration (optional)
    """
    version: int
    name: str
    upgrade: Callable[[sqlite3.Connection], None]
    downgrade: Optional[Callable[[sqlite3.Connection], None]] = None

#!/usr/bin/env python3
"""CLI script to check database migration status.

Usage:
    python scripts/migration_status.py
    
Shows current migration version, pending migrations, and full history.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.config import settings
from src.db.connection import DatabaseConnection
from src.db.migrations.runner import MigrationRunner


def main():
    """Show migration status."""
    db_path = settings.data_dir / "bot.db"
    conn = DatabaseConnection(db_path)
    runner = MigrationRunner(conn)
    
    status = runner.get_status()
    
    print(f"Database: {db_path}")
    print(f"Current Version: {status['current_version']}")
    print(f"Applied: {status['applied_count']} / {status['total_count']}")
    print(f"Pending: {status['pending_count']}")
    print()
    
    print("Migrations:")
    print("-" * 60)
    for m in status["migrations"]:
        status_str = "✓ Applied" if m["applied"] else "  Pending"
        downgrade_str = " [↓]" if m["has_downgrade"] else ""
        print(f"  {m['version']:3d}  {status_str}  {m['name']}{downgrade_str}")
    
    if status["pending_count"] > 0:
        print()
        print("Run migrations with: python -m src.main")
        return 1
    
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

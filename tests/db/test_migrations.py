"""Tests for database migration system."""
import pytest
from pathlib import Path


class TestMigrationDiscovery:
    """Test migration file discovery."""
    
    def test_migrations_directory_exists(self):
        """Verify migrations directory exists."""
        from src.db.migrations import MIGRATIONS_DIR
        assert MIGRATIONS_DIR.exists()
        assert MIGRATIONS_DIR.is_dir()
    
    def test_discover_migrations_finds_files(self):
        """Verify discover_migrations finds migration files."""
        from src.db.migrations import discover_migrations
        
        migrations = discover_migrations()
        assert len(migrations) > 0
        assert any(m.name == "001_baseline" for m in migrations)


class TestMigrationBaseClass:
    """Test Migration base class."""
    
    def test_migration_has_version_and_name(self):
        """Verify Migration dataclass has required fields."""
        from src.db.migrations.base import Migration
        
        migration = Migration(
            version=1,
            name="test_migration",
            upgrade=lambda conn: None,
            downgrade=None
        )
        assert migration.version == 1
        assert migration.name == "test_migration"


class TestMigrationHistoryTable:
    """Test migration_history table structure."""
    
    def test_migration_history_table_created(self, tmp_path):
        """Verify migration_history table is created."""
        from src.db.connection import DatabaseConnection
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_history';"
        )
        assert cursor.fetchone() is not None
        conn.close()

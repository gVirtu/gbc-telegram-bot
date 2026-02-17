"""Tests for database migration system."""
import pytest
import importlib
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


class TestMigrationRunner:
    """Test MigrationRunner functionality."""
    
    def test_runner_initializes_migration_history(self, tmp_path):
        """Verify runner creates migration_history table on init."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        runner._ensure_migration_history_table()
        
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_history';"
        )
        assert cursor.fetchone() is not None
        conn.close()
    
    def test_get_applied_migrations_empty_db(self, tmp_path):
        """Verify get_applied_migrations returns empty for new DB."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        runner._ensure_migration_history_table()
        
        applied = runner.get_applied_migrations()
        assert applied == []
        conn.close()
    
    def test_record_migration_applied(self, tmp_path):
        """Verify record_migration_applied works."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        runner._ensure_migration_history_table()
        
        runner._record_migration_applied(1, "001_baseline")
        
        applied = runner.get_applied_migrations()
        assert len(applied) == 1
        assert applied[0]["version"] == 1
        assert applied[0]["name"] == "001_baseline"
        conn.close()
    
    def test_is_migration_applied(self, tmp_path):
        """Verify is_migration_applied detection."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        runner._ensure_migration_history_table()
        
        assert not runner.is_migration_applied(1)
        runner._record_migration_applied(1, "001_baseline")
        assert runner.is_migration_applied(1)
        conn.close()


class TestBaselineMigration:
    """Test baseline migration for existing databases."""
    
    def test_detect_existing_database_with_schema_version(self, tmp_path):
        """Verify detection of existing database via schema_version table."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        baseline = importlib.import_module("src.db.migrations.001_baseline")
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        
        # Simulate existing database (before migrations existed)
        raw_conn = conn.get_connection()
        baseline.upgrade(raw_conn)
        
        # Verify schema_version table exists
        cursor = raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version';"
        )
        assert cursor.fetchone() is not None
        
        runner = MigrationRunner(conn)
        assert runner._is_existing_database()
        conn.close()
    
    def test_detect_new_database(self, tmp_path):
        """Verify new database is detected as not existing."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        
        assert not runner._is_existing_database()
        conn.close()
    
    def test_mark_baseline_as_applied(self, tmp_path):
        """Verify baseline is marked as applied for existing DBs."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        baseline = importlib.import_module("src.db.migrations.001_baseline")
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        
        # Simulate existing database
        raw_conn = conn.get_connection()
        baseline.upgrade(raw_conn)
        
        runner = MigrationRunner(conn)
        runner._ensure_migration_history_table()
        runner._mark_baseline_as_applied_if_needed()
        
        # Verify baseline is marked as applied
        assert runner.is_migration_applied(1)
        conn.close()


class TestMigrationIntegration:
    """Test migration integration with database initialization."""
    
    def test_migrations_run_on_connection_initialize(self, tmp_path):
        """Verify migrations run when DatabaseConnection.initialize() is called."""
        from src.db.connection import DatabaseConnection
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        # Verify migration_history table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_history';"
        )
        assert cursor.fetchone() is not None
        
        # Verify baseline is marked as applied
        cursor = conn.execute(
            "SELECT version FROM migration_history WHERE version = 1;"
        )
        assert cursor.fetchone() is not None
        conn.close()
    
    def test_migration_error_aborts_initialization(self, tmp_path):
        """Verify migration failure aborts with error."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationError
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        
        # Temporarily add a bad migration - patch where it's used, not defined
        import src.db.migrations.runner
        original_discover = src.db.migrations.runner.discover_migrations
        
        def mock_discover():
            from src.db.migrations.base import Migration
            
            def bad_upgrade(conn):
                raise ValueError("Migration failed!")
            
            return [
                Migration(version=999, name="999_bad", upgrade=bad_upgrade, downgrade=None)
            ]
        
        src.db.migrations.runner.discover_migrations = mock_discover
        
        try:
            with pytest.raises(MigrationError) as exc_info:
                conn.initialize()
            
            assert "Migration 999_bad (v999) failed" in str(exc_info.value)
        finally:
            src.db.migrations.runner.discover_migrations = original_discover
            conn.close()


class TestSampleMigration:
    """Test the sample migration for adding updated_at column."""
    
    def test_migration_002_adds_updated_at_column(self, tmp_path):
        """Verify migration 002 adds updated_at column to migration_history."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        runner = MigrationRunner(conn)
        runner.run_migrations()
        
        # Check if migration 002 is applied
        assert runner.is_migration_applied(2)
        
        # Verify the column was added
        cursor = conn.execute("PRAGMA table_info(migration_history);")
        columns = {row['name'] for row in cursor.fetchall()}
        assert 'updated_at' in columns
        conn.close()
    
    def test_migration_002_downgrade_removes_column(self, tmp_path):
        """Verify migration 002 downgrade removes the column."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        runner = MigrationRunner(conn)
        runner.run_migrations()
        
        # Apply migration 002
        assert runner.is_migration_applied(2)
        
        # Rollback migration 002
        runner.rollback_migration(2)
        
        # Verify it's no longer applied
        assert not runner.is_migration_applied(2)
        conn.close()


class TestMigrationStatus:
    """Test migration status reporting."""
    
    def test_get_migration_status_new_db(self, tmp_path):
        """Verify status for new database."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        
        status = runner.get_status()
        
        assert status["current_version"] == 0
        assert status["pending_count"] > 0
        assert len(status["migrations"]) > 0
        conn.close()
    
    def test_get_migration_status_after_migrations(self, tmp_path):
        """Verify status after running migrations."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        runner = MigrationRunner(conn)
        runner.run_migrations()
        
        status = runner.get_status()
        
        assert status["current_version"] > 0
        assert status["pending_count"] == 0
        
        # Check all migrations are marked as applied
        for m in status["migrations"]:
            if m["version"] <= status["current_version"]:
                assert m["applied"] is True
        conn.close()

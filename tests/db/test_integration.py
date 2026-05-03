"""Integration tests for the complete migration system."""

import pytest
import importlib
from datetime import datetime


class TestFullMigrationWorkflow:
    """Test complete migration workflow from fresh to fully migrated."""
    
    def test_fresh_database_gets_all_migrations(self, tmp_path):
        """Verify fresh database gets all migrations applied."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        runner = MigrationRunner(conn)
        status = runner.get_status()
        
        # All migrations should be applied
        assert status["pending_count"] == 0
        assert status["applied_count"] == status["total_count"]
        
        # Verify tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        
        assert "migration_history" in tables
        assert "chat_configs" in tables
        assert "game_states" in tables
        
        conn.close()
    
    def test_existing_database_baseline_marked_applied(self, tmp_path):
        """Verify existing database marks baseline as applied without running."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        baseline = importlib.import_module("src.db.migrations.001_baseline")
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        
        # Create database the "old" way (before migrations)
        raw_conn = conn.get_connection()
        baseline.upgrade(raw_conn)
        
        # Now run migrations
        runner = MigrationRunner(conn)
        runner.run_migrations()
        
        status = runner.get_status()
        
        # Baseline should be marked as applied without re-running
        assert runner.is_migration_applied(1)
        
        # All migrations should be applied
        assert status["pending_count"] == 0
        
        conn.close()
    
    def test_migration_applied_timestamp_recorded(self, tmp_path):
        """Verify migration timestamps are recorded."""
        from src.db.connection import DatabaseConnection
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        cursor = conn.execute(
            "SELECT version, name, applied_at FROM migration_history ORDER BY version;"
        )
        rows = cursor.fetchall()
        
        assert len(rows) > 0
        
        for row in rows:
            assert row["version"] > 0
            assert row["name"]
            # applied_at should be a valid timestamp
            applied_at = datetime.fromisoformat(row["applied_at"])
            assert isinstance(applied_at, datetime)
        
        conn.close()


class TestRollbackWorkflow:
    """Test migration rollback functionality."""
    
    def test_rollback_migration_removes_applied_status(self, tmp_path):
        """Verify rollback removes migration from applied list."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        runner = MigrationRunner(conn)
        
        # Find a migration with downgrade
        migrations = runner.get_status()["migrations"]
        rollbackable = [m for m in migrations if m["has_downgrade"]]
        
        if not rollbackable:
            pytest.skip("No migrations with downgrade found")
        
        target = rollbackable[-1]  # Rollback the last one
        version = target["version"]
        
        # Verify it's applied
        assert runner.is_migration_applied(version)
        
        # Rollback
        runner.rollback_migration(version)
        
        # Verify it's no longer applied
        assert not runner.is_migration_applied(version)
        
        # Verify reverted_at is set
        cursor = conn.execute(
            "SELECT reverted_at FROM migration_history WHERE version = ?;",
            (version,)
        )
        row = cursor.fetchone()
        assert row["reverted_at"] is not None
        
        conn.close()
    
    def test_rollback_without_downgrade_fails(self, tmp_path):
        """Verify rollback fails for migrations without downgrade."""
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner, MigrationError
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        conn.initialize()
        
        runner = MigrationRunner(conn)
        
        # Find a migration without downgrade (if any)
        migrations = runner.get_status()["migrations"]
        non_rollbackable = [m for m in migrations if not m["has_downgrade"]]
        
        if not non_rollbackable:
            pytest.skip("No migrations without downgrade found")
        
        target = non_rollbackable[0]
        version = target["version"]
        
        with pytest.raises(MigrationError) as exc_info:
            runner.rollback_migration(version)
        
        assert "no downgrade function" in str(exc_info.value).lower()
        
        conn.close()


class TestTransactionSafety:
    """Test that migrations run in transactions."""
    
    def test_failed_migration_not_recorded_as_applied(self, tmp_path):
        """Verify failed migration is not recorded as applied."""
        import src.db.migrations.runner
        from src.db.connection import DatabaseConnection
        from src.db.migrations.runner import MigrationRunner, MigrationError
        
        db_path = tmp_path / "test.db"
        conn = DatabaseConnection(db_path)
        
        # Create a good baseline
        raw_conn = conn.get_connection()
        raw_conn.executescript("""
            CREATE TABLE IF NOT EXISTS migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reverted_at TIMESTAMP
            );
        """)
        
        # Mark baseline as applied
        runner = MigrationRunner(conn)
        runner._record_migration_applied(1, "001_baseline")
        
        # Now inject a failing migration
        original_discover = src.db.migrations.runner.discover_migrations
        
        def mock_discover_with_failure():
            from src.db.migrations.base import Migration
            
            def partial_upgrade(conn):
                conn.execute("CREATE TABLE test_partial (id INTEGER PRIMARY KEY);")
                raise ValueError("Intentional failure!")
            
            return [
                Migration(version=2, name="002_failing", upgrade=partial_upgrade, downgrade=None),
            ]
        
        src.db.migrations.runner.discover_migrations = mock_discover_with_failure
        
        try:
            with pytest.raises(MigrationError):
                runner.run_migrations()
            
            # Verify migration was NOT recorded as applied
            assert not runner.is_migration_applied(2)
            
        finally:
            src.db.migrations.runner.discover_migrations = original_discover
            conn.close()

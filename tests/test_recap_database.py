"""Tests for recap file database operations."""

import pytest
from datetime import datetime
from pathlib import Path

from src.db.manager import DatabaseManager
from src.models.game_state import RecapFileRecord


@pytest.fixture
def db_manager(tmp_path):
    """Create a test database manager."""
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


class TestRecapFileDatabase:
    """Tests for recap file database operations."""

    @pytest.mark.asyncio
    async def test_get_recap_file_nonexistent(self, db_manager):
        """Test getting a recap file that doesn't exist."""
        result = await db_manager.get_recap_file(123, "20260221")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_recap_metadata_new(self, db_manager):
        """Test upserting new recap metadata."""
        await db_manager.upsert_recap_metadata(
            chat_id=123,
            date="20260221",
            added_frame_count=100,
            added_duration_sec=10.0,
            file_size_bytes=50000,
        )

        record = await db_manager.get_recap_file(123, "20260221")
        assert record is not None
        assert record.chat_id == 123
        assert record.date == "20260221"
        assert record.part_number == 1
        assert record.is_rt is False
        assert record.file_id is None  # Initially null
        assert record.frame_count == 100
        assert record.duration_sec == 10.0
        assert record.file_size_bytes == 50000
        assert record.created_at is not None
        assert record.updated_at is not None

    @pytest.mark.asyncio
    async def test_upsert_recap_metadata_increment(self, db_manager):
        """Test upserting existing recap metadata increments values."""
        # Insert initial record
        await db_manager.upsert_recap_metadata(
            chat_id=123,
            date="20260221",
            added_frame_count=100,
            added_duration_sec=10.0,
            file_size_bytes=50000,
        )

        # Set file_id
        await db_manager.update_recap_file_id(123, "20260221", 1, False, "file_123")

        # Upsert again (should increment frame count and duration)
        await db_manager.upsert_recap_metadata(
            chat_id=123,
            date="20260221",
            added_frame_count=50,
            added_duration_sec=5.0,
            file_size_bytes=25000,
        )

        record = await db_manager.get_recap_file(123, "20260221")
        assert record.frame_count == 150  # 100 + 50
        assert record.duration_sec == 15.0  # 10.0 + 5.0
        assert record.file_size_bytes == 25000 # Replaced
        assert record.file_id is None  # Invalidated on upsert

    @pytest.mark.asyncio
    async def test_update_recap_file_id(self, db_manager):
        """Test updating recap file_id."""
        await db_manager.upsert_recap_metadata(
            chat_id=123,
            date="20260221",
            added_frame_count=100,
            added_duration_sec=10.0,
            file_size_bytes=50000,
        )

        await db_manager.update_recap_file_id(123, "20260221", 1, False, "telegram_file_id_xyz")

        record = await db_manager.get_recap_file(123, "20260221")
        assert record.file_id == "telegram_file_id_xyz"

    @pytest.mark.asyncio
    async def test_get_nearest_recap_date_before(self, db_manager):
        """Test finding nearest recap date before target."""
        # Insert multiple dates
        await db_manager.upsert_recap_metadata(123, "20260218", 10, 1.0, 1000)
        await db_manager.upsert_recap_metadata(123, "20260220", 10, 1.0, 1000)
        await db_manager.upsert_recap_metadata(123, "20260222", 10, 1.0, 1000)

        # Find date before 20260221
        result = await db_manager.get_nearest_recap_date(123, "20260221", "before")
        assert result == "20260220"

        # Find date before 20260220 (should be 20260218)
        result = await db_manager.get_nearest_recap_date(123, "20260220", "before")
        assert result == "20260218"

    @pytest.mark.asyncio
    async def test_get_nearest_recap_date_after(self, db_manager):
        """Test finding nearest recap date after target."""
        # Insert multiple dates
        await db_manager.upsert_recap_metadata(123, "20260218", 10, 1.0, 1000)
        await db_manager.upsert_recap_metadata(123, "20260220", 10, 1.0, 1000)
        await db_manager.upsert_recap_metadata(123, "20260222", 10, 1.0, 1000)

        # Find date after 20260221
        result = await db_manager.get_nearest_recap_date(123, "20260221", "after")
        assert result == "20260222"

        # Find date after 20260220 (should be 20260222)
        result = await db_manager.get_nearest_recap_date(123, "20260220", "after")
        assert result == "20260222"

    @pytest.mark.asyncio
    async def test_get_nearest_recap_date_none_before(self, db_manager):
        """Test finding nearest date when none exist before."""
        await db_manager.upsert_recap_metadata(123, "20260220", 10, 1.0, 1000)

        result = await db_manager.get_nearest_recap_date(123, "20260215", "before")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_nearest_recap_date_none_after(self, db_manager):
        """Test finding nearest date when none exist after."""
        await db_manager.upsert_recap_metadata(123, "20260220", 10, 1.0, 1000)

        result = await db_manager.get_nearest_recap_date(123, "20260225", "after")
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_chats_isolated(self, db_manager):
        """Test that recap data is isolated per chat."""
        # Insert for different chats
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000)
        await db_manager.upsert_recap_metadata(456, "20260221", 200, 20.0, 100000)

        # Verify isolation
        record_123 = await db_manager.get_recap_file(123, "20260221")
        record_456 = await db_manager.get_recap_file(456, "20260221")

        assert record_123.frame_count == 100
        assert record_456.frame_count == 200

        # Nearest dates should not cross chats
        result = await db_manager.get_nearest_recap_date(123, "20260220", "after")
        assert result == "20260221"

    # ==================== New tests for parts ====================

    @pytest.mark.asyncio
    async def test_get_recap_parts_empty(self, db_manager):
        """Test get_recap_parts returns empty list when no records exist."""
        parts = await db_manager.get_recap_parts(123, "20260221", False)
        assert parts == []

    @pytest.mark.asyncio
    async def test_get_recap_parts_single(self, db_manager):
        """Test get_recap_parts returns single part after upsert."""
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000, part_number=1, is_rt=False)

        parts = await db_manager.get_recap_parts(123, "20260221", False)
        assert len(parts) == 1
        assert parts[0].part_number == 1
        assert parts[0].is_rt is False
        assert parts[0].frame_count == 100

    @pytest.mark.asyncio
    async def test_get_recap_parts_ordered_by_part_number(self, db_manager):
        """Test get_recap_parts returns rows ordered by part_number ascending."""
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000, part_number=1, is_rt=False)
        await db_manager.split_recap_part(123, "20260221", 1, False)
        await db_manager.upsert_recap_metadata(123, "20260221", 50, 5.0, 25000, part_number=2, is_rt=False)

        parts = await db_manager.get_recap_parts(123, "20260221", False)
        assert len(parts) == 2
        assert parts[0].part_number == 1
        assert parts[1].part_number == 2

    @pytest.mark.asyncio
    async def test_split_recap_part_nullifies_file_id(self, db_manager):
        """Test split_recap_part nullifies file_id on current part."""
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000)
        await db_manager.update_recap_file_id(123, "20260221", 1, False, "cached_file_id")

        # Verify file_id is set
        parts_before = await db_manager.get_recap_parts(123, "20260221", False)
        assert parts_before[0].file_id == "cached_file_id"

        await db_manager.split_recap_part(123, "20260221", 1, False)

        parts_after = await db_manager.get_recap_parts(123, "20260221", False)
        assert len(parts_after) == 2
        assert parts_after[0].file_id is None  # Nullified
        assert parts_after[1].part_number == 2
        assert parts_after[1].frame_count == 0  # Fresh row

    @pytest.mark.asyncio
    async def test_rt_and_non_rt_rows_do_not_collide(self, db_manager):
        """Test that RT and non-RT rows for the same (chat_id, date) are independent."""
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000, part_number=1, is_rt=False)
        await db_manager.upsert_recap_metadata(123, "20260221", 80, 8.0, 40000, part_number=1, is_rt=True)

        non_rt_parts = await db_manager.get_recap_parts(123, "20260221", False)
        rt_parts = await db_manager.get_recap_parts(123, "20260221", True)

        assert len(non_rt_parts) == 1
        assert len(rt_parts) == 1
        assert non_rt_parts[0].frame_count == 100
        assert rt_parts[0].frame_count == 80
        assert non_rt_parts[0].is_rt is False
        assert rt_parts[0].is_rt is True

    @pytest.mark.asyncio
    async def test_get_nearest_recap_date_distinct_with_multiple_parts(self, db_manager):
        """Test get_nearest_recap_date returns distinct dates even when multiple parts exist."""
        # Insert multiple parts for the same date
        await db_manager.upsert_recap_metadata(123, "20260218", 100, 10.0, 50000, part_number=1)
        await db_manager.split_recap_part(123, "20260218", 1, False)
        await db_manager.upsert_recap_metadata(123, "20260218", 50, 5.0, 25000, part_number=2)

        await db_manager.upsert_recap_metadata(123, "20260220", 100, 10.0, 50000)

        # Should only return 20260218 once, not duplicate
        result = await db_manager.get_nearest_recap_date(123, "20260219", "before")
        assert result == "20260218"

    @pytest.mark.asyncio
    async def test_get_recap_file_returns_highest_part(self, db_manager):
        """Test get_recap_file returns the row with highest part_number."""
        await db_manager.upsert_recap_metadata(123, "20260221", 100, 10.0, 50000, part_number=1)
        await db_manager.split_recap_part(123, "20260221", 1, False)
        await db_manager.upsert_recap_metadata(123, "20260221", 50, 5.0, 25000, part_number=2)

        record = await db_manager.get_recap_file(123, "20260221")
        assert record is not None
        assert record.part_number == 2


class TestAutoSentAtMigration:
    def test_auto_sent_at_column_exists_after_migration(self, db_manager):
        """After DB init, recap_files has an auto_sent_at column."""
        cursor = db_manager.connection.execute("PRAGMA table_info(recap_files);")
        cols = [row["name"] for row in cursor.fetchall()]
        assert "auto_sent_at" in cols

    @pytest.mark.asyncio
    async def test_get_recap_parts_returns_auto_sent_at_field(self, db_manager):
        """get_recap_parts returns RecapFileRecord with auto_sent_at attribute."""
        parts = await db_manager.get_recap_parts(123, "20260101", False)
        # If no parts yet, just check that when we add one, it has auto_sent_at
        await db_manager.upsert_recap_metadata(123, "20260101", 10, 1.0, 500)
        parts = await db_manager.get_recap_parts(123, "20260101", False)
        assert hasattr(parts[0], "auto_sent_at")
        assert parts[0].auto_sent_at is None  # not yet marked

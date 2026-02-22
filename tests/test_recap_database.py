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
        await db_manager.update_recap_file_id(123, "20260221", "file_123")

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

        await db_manager.update_recap_file_id(123, "20260221", "telegram_file_id_xyz")

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
import pytest
from pathlib import Path
from datetime import datetime, timezone

from signaldeck.storage.database import Database
from signaldeck.storage.models import Signal, ActivityEntry, Bookmark


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    yield database
    await database.close()


async def _seed(db):
    """Insert a signal and activity entry for testing."""
    now = datetime.now(timezone.utc)
    sig = Signal(
        frequency=101_100_000, bandwidth=200_000, modulation="FM",
        protocol="broadcast", first_seen=now, last_seen=now,
        hit_count=1, avg_strength=-30.0, confidence=0.8,
    )
    sig_id = await db.upsert_signal(sig)
    entry = ActivityEntry(
        signal_id=sig_id, timestamp=now, duration=0.05,
        strength=-30.0, decoder_used=None, result_type="broadcast",
        summary="101.100 MHz [broadcast] -30.0 dBFS",
    )
    await db.insert_activity(entry)
    return sig_id


@pytest.mark.asyncio
class TestDatabaseClear:
    async def test_clear_signals(self, db):
        await _seed(db)
        assert len(await db.get_all_signals()) == 1
        await db.clear_signals()
        assert len(await db.get_all_signals()) == 0

    async def test_clear_activity(self, db):
        await _seed(db)
        assert len(await db.get_recent_activity()) == 1
        await db.clear_activity()
        assert len(await db.get_recent_activity()) == 0

    async def test_clear_bookmarks(self, db):
        await db.insert_bookmark(Bookmark(frequency=101_100_000, label="Test FM", modulation="FM", decoder=None, priority=3, camp_on_active=False))
        bookmarks = await db.get_all_bookmarks()
        assert len(bookmarks) == 1
        await db.clear_bookmarks()
        assert len(await db.get_all_bookmarks()) == 0

    async def test_clear_all(self, db):
        await _seed(db)
        await db.insert_bookmark(Bookmark(frequency=101_100_000, label="Test", modulation="FM", decoder=None, priority=3, camp_on_active=False))
        await db.clear_all()
        assert len(await db.get_all_signals()) == 0
        assert len(await db.get_recent_activity()) == 0
        assert len(await db.get_all_bookmarks()) == 0

    async def test_get_stats(self, db):
        await _seed(db)
        stats = await db.get_stats()
        assert stats["signals"] == 1
        assert stats["activity"] == 1
        assert stats["bookmarks"] == 0
        assert "db_size" in stats
        assert stats["db_size"] > 0

    async def test_get_stats_empty(self, db):
        stats = await db.get_stats()
        assert stats["signals"] == 0
        assert stats["activity"] == 0

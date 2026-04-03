import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from signaldeck.storage.database import Database
from signaldeck.storage.models import Signal, ActivityEntry


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    yield database
    await database.close()


async def test_initialize_creates_tables(db: Database):
    """Database initialization creates all required tables."""
    tables = await db.list_tables()
    assert "signals" in tables
    assert "activity_log" in tables
    assert "bookmarks" in tables
    assert "recordings" in tables
    assert "learned_patterns" in tables
    assert "decoder_results" in tables


async def test_insert_and_get_signal(db: Database):
    """Can insert a signal and retrieve it by frequency."""
    signal = Signal(
        frequency=162_400_000.0,
        bandwidth=12500.0,
        modulation="FM",
        protocol=None,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        hit_count=1,
        avg_strength=-45.0,
        confidence=0.0,
    )
    signal_id = await db.upsert_signal(signal)
    assert signal_id > 0

    retrieved = await db.get_signal_by_frequency(162_400_000.0, tolerance_hz=1000)
    assert retrieved is not None
    assert retrieved.frequency == 162_400_000.0
    assert retrieved.modulation == "FM"


async def test_upsert_signal_updates_existing(db: Database):
    """Upserting a signal at the same frequency updates hit_count and last_seen."""
    now = datetime.now(timezone.utc)
    signal = Signal(
        frequency=162_400_000.0,
        bandwidth=12500.0,
        modulation="FM",
        protocol=None,
        first_seen=now,
        last_seen=now,
        hit_count=1,
        avg_strength=-45.0,
        confidence=0.0,
    )
    id1 = await db.upsert_signal(signal)
    signal.avg_strength = -40.0
    id2 = await db.upsert_signal(signal)
    assert id1 == id2

    retrieved = await db.get_signal_by_frequency(162_400_000.0, tolerance_hz=1000)
    assert retrieved.hit_count == 2
    assert retrieved.avg_strength == -40.0


async def test_insert_activity(db: Database):
    """Can log an activity entry and retrieve recent entries."""
    signal = Signal(
        frequency=162_400_000.0,
        bandwidth=12500.0,
        modulation="FM",
        protocol=None,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        hit_count=1,
        avg_strength=-45.0,
        confidence=0.0,
    )
    signal_id = await db.upsert_signal(signal)

    entry = ActivityEntry(
        signal_id=signal_id,
        timestamp=datetime.now(timezone.utc),
        duration=5.0,
        strength=-45.0,
        decoder_used=None,
        result_type="unknown",
        summary="Signal detected at 162.4 MHz",
    )
    activity_id = await db.insert_activity(entry)
    assert activity_id > 0

    recent = await db.get_recent_activity(limit=10)
    assert len(recent) == 1
    assert recent[0].signal_id == signal_id


async def test_get_all_signals(db: Database):
    """Can retrieve all known signals."""
    for freq in [88_100_000.0, 162_400_000.0, 460_500_000.0]:
        signal = Signal(
            frequency=freq, bandwidth=12500.0, modulation="FM",
            protocol=None, first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc), hit_count=1,
            avg_strength=-50.0, confidence=0.0,
        )
        await db.upsert_signal(signal)

    signals = await db.get_all_signals()
    assert len(signals) == 3

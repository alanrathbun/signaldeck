from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app, get_db
from signaldeck.storage.models import Signal, ActivityEntry

@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024, "sweep_ranges": []},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }
    return create_app(config)

@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

async def test_list_signals_empty(client):
    resp = await client.get("/api/signals")
    assert resp.status_code == 200
    assert resp.json() == []

async def test_list_signals_with_data(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    await db.upsert_signal(Signal(frequency=98_500_000.0, bandwidth=200000.0, modulation="FM",
        protocol="broadcast_fm", first_seen=now, last_seen=now, hit_count=1, avg_strength=-30.0, confidence=0.9))
    resp = await client.get("/api/signals")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["frequency_mhz"] == 98.5

async def test_get_activity_empty(client):
    resp = await client.get("/api/activity")
    assert resp.status_code == 200
    assert resp.json() == []

async def test_get_activity_with_data(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    sig_id = await db.upsert_signal(Signal(frequency=162_400_000.0, bandwidth=12500.0, modulation="FM",
        protocol=None, first_seen=now, last_seen=now, hit_count=1, avg_strength=-45.0, confidence=0.0))
    await db.insert_activity(ActivityEntry(signal_id=sig_id, timestamp=now, duration=5.0, strength=-45.0,
        decoder_used=None, result_type="unknown", summary="Signal at 162.4 MHz"))
    resp = await client.get("/api/activity")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["signal_id"] == sig_id

async def test_get_activity_with_limit(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    sig_id = await db.upsert_signal(Signal(frequency=100e6, bandwidth=200e3, modulation="FM",
        protocol=None, first_seen=now, last_seen=now, hit_count=1, avg_strength=-40.0, confidence=0.0))
    for i in range(20):
        await db.insert_activity(ActivityEntry(signal_id=sig_id, timestamp=now, duration=1.0, strength=-40.0,
            decoder_used=None, result_type="unknown", summary=f"Entry {i}"))
    resp = await client.get("/api/activity?limit=5")
    assert len(resp.json()) == 5

async def test_enrichment_endpoint(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    sig_id = await db.upsert_signal(Signal(frequency=162_550_000.0, bandwidth=12500.0, modulation="FM",
        protocol="NOAA", first_seen=now, last_seen=now, hit_count=5, avg_strength=-45.0, confidence=0.8))
    await db.insert_activity(ActivityEntry(signal_id=sig_id, timestamp=now, duration=2.0, strength=-45.0,
        decoder_used="noaa", result_type="weather", summary="NOAA weather broadcast"))
    resp = await client.get("/api/signals/enrichment")
    assert resp.status_code == 200
    data = resp.json()
    # Keyed by frequency in Hz as string
    key = "162550000"
    assert key in data
    assert data[key]["first_seen"] is not None
    assert data[key]["hit_count"] == 5
    assert data[key]["confidence"] == 0.8
    assert data[key]["last_activity"]["decoder"] == "noaa"
    assert data[key]["last_activity"]["type"] == "weather"

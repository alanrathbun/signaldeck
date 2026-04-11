import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app
from signaldeck.storage.models import Signal, ActivityEntry


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": []},
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


async def _seed(client):
    """Insert data via the database directly."""
    from signaldeck.api.server import get_db
    db = get_db()
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


@pytest.mark.asyncio
class TestDataManagement:
    async def test_delete_signals(self, client):
        await _seed(client)
        resp = await client.delete("/api/data/signals")
        assert resp.status_code == 200
        resp = await client.get("/api/signals")
        assert len(resp.json()) == 0

    async def test_delete_activity(self, client):
        await _seed(client)
        resp = await client.delete("/api/data/activity")
        assert resp.status_code == 200
        resp = await client.get("/api/activity")
        assert len(resp.json()) == 0

    async def test_delete_bookmarks(self, client):
        await client.post("/api/bookmarks", json={
            "frequency_hz": 101_100_000, "label": "Test FM"
        })
        resp = await client.delete("/api/data/bookmarks")
        assert resp.status_code == 200
        resp = await client.get("/api/bookmarks")
        assert len(resp.json()) == 0

    async def test_delete_all(self, client):
        await _seed(client)
        resp = await client.delete("/api/data/all")
        assert resp.status_code == 200
        resp = await client.get("/api/signals")
        assert len(resp.json()) == 0

    async def test_get_status(self, client):
        await _seed(client)
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["db_stats"]["signals"] == 1

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    (d / "signaldeck-2026-04-03T10-00-00.log").write_text(
        "10:00:01 [signaldeck] INFO: Server started\n"
        "10:00:02 [signaldeck] WARNING: Low disk space\n"
    )
    (d / "signaldeck-2026-04-03T11-00-00.log").write_text(
        "11:00:01 [signaldeck] INFO: Scan started\n"
    )
    return d


@pytest.fixture
def app(tmp_path, log_dir):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": [{"label": "Test", "start_mhz": 88, "end_mhz": 108}]},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG", "log_dir": str(log_dir)},
        "_session_log_file": str(log_dir / "signaldeck-2026-04-03T11-00-00.log"),
    }
    return create_app(config)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
class TestLogEndpoints:
    async def test_list_logs(self, client):
        resp = await client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "signaldeck-2026-04-03T11-00-00.log"
        assert "size" in data[0]

    async def test_get_current_log(self, client):
        resp = await client.get("/api/logs/current")
        assert resp.status_code == 200
        assert "Scan started" in resp.json()["content"]

    async def test_get_specific_log(self, client):
        resp = await client.get("/api/logs/signaldeck-2026-04-03T10-00-00.log")
        assert resp.status_code == 200
        assert "Server started" in resp.json()["content"]

    async def test_get_nonexistent_log(self, client):
        resp = await client.get("/api/logs/nonexistent.log")
        assert resp.status_code == 404

    async def test_delete_logs(self, client, log_dir):
        resp = await client.delete("/api/logs")
        assert resp.status_code == 200
        remaining = list(log_dir.glob("*.log"))
        assert len(remaining) == 1
        assert "11-00-00" in remaining[0].name

    async def test_path_traversal_blocked(self, client):
        resp = await client.get("/api/logs/../../etc/passwd")
        assert resp.status_code == 404

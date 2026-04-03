import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": [{"label": "Test", "start_mhz": 88, "end_mhz": 108}]},
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


async def test_list_bookmarks_empty(client):
    resp = await client.get("/api/bookmarks")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_bookmark(client):
    payload = {
        "frequency_hz": 162550000.0,
        "label": "NOAA WX",
        "modulation": "NFM",
        "priority": 5,
    }
    resp = await client.post("/api/bookmarks", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["label"] == "NOAA WX"
    assert "id" in data
    assert isinstance(data["id"], int)


async def test_list_bookmarks_after_create(client):
    payload = {
        "frequency_hz": 156800000.0,
        "label": "Marine Ch16",
        "modulation": "NFM",
        "priority": 4,
        "notes": "Distress channel",
    }
    create_resp = await client.post("/api/bookmarks", json=payload)
    assert create_resp.status_code == 201
    bk_id = create_resp.json()["id"]

    list_resp = await client.get("/api/bookmarks")
    assert list_resp.status_code == 200
    bookmarks = list_resp.json()
    assert len(bookmarks) == 1
    bk = bookmarks[0]
    assert bk["id"] == bk_id
    assert bk["label"] == "Marine Ch16"
    assert bk["frequency_hz"] == 156800000.0
    assert bk["frequency_mhz"] == 156.8
    assert bk["notes"] == "Distress channel"
    assert bk["priority"] == 4
    assert "created_at" in bk


async def test_delete_bookmark(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 121500000.0,
        "label": "Aviation Guard",
        "modulation": "AM",
    })
    assert create_resp.status_code == 201
    bk_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/bookmarks/{bk_id}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"deleted": True}

    list_resp = await client.get("/api/bookmarks")
    assert list_resp.json() == []


async def test_delete_nonexistent_bookmark_returns_404(client):
    resp = await client.delete("/api/bookmarks/99999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Bookmark not found"


async def test_create_bookmark_validation_missing_required_fields(client):
    # Missing required fields: frequency_hz and label
    resp = await client.post("/api/bookmarks", json={"modulation": "FM"})
    assert resp.status_code == 422

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


async def test_patch_bookmark_updates_label(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 162_400_000.0,
        "label": "NOAA Weather",
        "modulation": "NFM",
        "priority": 5,
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/bookmarks/{bk_id}",
        json={"label": "NOAA WX (renamed)"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"id": bk_id, "updated": True}

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["label"] == "NOAA WX (renamed)"
    # Other fields preserved
    assert row["modulation"] == "NFM"
    assert row["priority"] == 5


async def test_patch_bookmark_partial_update(client):
    """PATCH with only priority leaves other fields unchanged."""
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 146_520_000.0,
        "label": "2m Calling",
        "modulation": "FM",
        "decoder": "aprs",
        "priority": 3,
        "notes": "do not touch",
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 5})
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"id": bk_id, "updated": True}

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["priority"] == 5
    assert row["label"] == "2m Calling"
    assert row["modulation"] == "FM"
    assert row["decoder"] == "aprs"
    assert row["notes"] == "do not touch"


async def test_patch_bookmark_missing_returns_404(client):
    resp = await client.patch("/api/bookmarks/99999", json={"label": "nope"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Bookmark not found"


async def test_patch_bookmark_rejects_empty_label(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 121_500_000.0,
        "label": "Aviation Guard",
        "modulation": "AM",
    })
    bk_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"label": ""})
    # Pydantic min_length=1 rejects with 422
    assert resp.status_code == 422


async def test_patch_bookmark_rejects_priority_out_of_range(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 156_800_000.0,
        "label": "Marine Ch16",
        "modulation": "NFM",
    })
    bk_id = create_resp.json()["id"]

    # Too high
    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 10})
    assert resp.status_code == 422
    # Too low
    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 0})
    assert resp.status_code == 422


async def test_patch_bookmark_clears_notes_with_empty_string(client):
    """PATCH with notes='' stores an empty string (not null)."""
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 100_300_000.0,
        "label": "Classic FM",
        "modulation": "FM",
        "notes": "has some notes",
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"notes": ""})
    assert patch_resp.status_code == 200

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["notes"] == ""


async def test_patch_bookmark_empty_body_is_noop(client):
    """PATCH with an empty body is a successful no-op on existing rows.

    The backend's Database.update_bookmark treats empty kwargs as an
    existence check — returns True if the row exists (even though nothing
    is modified), False otherwise. At the HTTP layer that maps to 200 on
    an existing id and 404 on a missing id.
    """
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 446_000_000.0,
        "label": "Empty-patch target",
        "modulation": "NFM",
        "priority": 2,
        "notes": "unchanged by empty patch",
    })
    bk_id = create_resp.json()["id"]

    # Empty body on an existing id -> 200 no-op
    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={})
    assert resp.status_code == 200
    assert resp.json() == {"id": bk_id, "updated": True}

    # Verify the row was NOT modified
    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["label"] == "Empty-patch target"
    assert row["priority"] == 2
    assert row["notes"] == "unchanged by empty patch"

    # Empty body on a missing id -> 404
    resp = await client.patch("/api/bookmarks/99999", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Bookmark not found"

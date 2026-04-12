import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "scanner": {},
    }
    return create_app(config)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_create_group(client):
    resp = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Fire"
    assert "id" in data


async def test_list_groups(client):
    await client.post("/api/bookmark-groups", json={"name": "Fire"})
    await client.post("/api/bookmark-groups", json={"name": "Airport"})
    resp = await client.get("/api/bookmark-groups")
    assert resp.status_code == 200
    groups = resp.json()
    assert len(groups) == 2
    names = [g["name"] for g in groups]
    assert "Airport" in names
    assert "Fire" in names
    assert "member_count" in groups[0]


async def test_rename_group(client):
    create = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    gid = create.json()["id"]
    resp = await client.patch(f"/api/bookmark-groups/{gid}", json={"name": "Fire Dispatch"})
    assert resp.status_code == 200
    groups = (await client.get("/api/bookmark-groups")).json()
    assert groups[0]["name"] == "Fire Dispatch"


async def test_delete_group(client):
    create = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    gid = create.json()["id"]
    resp = await client.delete(f"/api/bookmark-groups/{gid}")
    assert resp.status_code == 200
    groups = (await client.get("/api/bookmark-groups")).json()
    assert len(groups) == 0


async def test_set_group_members(client):
    g = (await client.post("/api/bookmark-groups", json={"name": "Fire"})).json()
    b1 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 154175000, "label": "BCFD Disp", "modulation": "FMN"
    })).json()
    b2 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 155310000, "label": "BCFD Fire 1", "modulation": "FMN"
    })).json()
    resp = await client.put(
        f"/api/bookmark-groups/{g['id']}/members",
        json={"bookmark_ids": [b1["id"], b2["id"]]},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    resp = await client.get(f"/api/bookmark-groups/{g['id']}/members")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_add_and_remove_member(client):
    g = (await client.post("/api/bookmark-groups", json={"name": "Fire"})).json()
    b1 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 154175000, "label": "BCFD Disp", "modulation": "FMN"
    })).json()
    resp = await client.post(
        f"/api/bookmark-groups/{g['id']}/members",
        json={"bookmark_id": b1["id"]},
    )
    assert resp.status_code == 200
    resp = await client.delete(f"/api/bookmark-groups/{g['id']}/members/{b1['id']}")
    assert resp.status_code == 200
    members = (await client.get(f"/api/bookmark-groups/{g['id']}/members")).json()
    assert len(members) == 0

# Bookmark Scanning & Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bookmark groups (named collections) and a three-mode scanner (dwell, activity, manual) to the Bookmarks page, plus fix the Tune button so it stays on Bookmarks instead of navigating to Live.

**Architecture:** Groups are stored in two new SQLite tables (bookmark_groups + bookmark_group_members join table). The scan logic lives entirely in the frontend (Alpine.js timers + state), using the existing `tuneAndListen()` path. Activity scan polls a new `/api/gqrx/squelch-open` endpoint that compares signal strength to squelch threshold via the existing gqrx rigctl client.

**Tech Stack:** Python/FastAPI (backend), Alpine.js (frontend), aiosqlite (storage), gqrx rigctl (squelch detection)

---

### Task 1: Fix Tune button page navigation (bug fix)

**Files:**
- Modify: `signaldeck/web/index.html:367`

- [ ] **Step 1: Fix the Tune button click handler**

In `signaldeck/web/index.html`, line 367, change:

```html
<button class="btn btn-sm btn-primary" @click="navigate('live'); tuneAndListen(bm.frequency_hz, bm.modulation)">Tune</button>
```

to:

```html
<button class="btn btn-sm btn-primary" @click="tuneAndListen(bm.frequency_hz, bm.modulation)">Tune</button>
```

- [ ] **Step 2: Add row-active highlight to bookmark rows**

In `signaldeck/web/index.html`, the bookmark `<tr>` at line 352 currently has no active-row logic. Change:

```html
<template x-for="bm in bookmarks" :key="bm.id">
                <tr>
```

to:

```html
<template x-for="bm in bookmarks" :key="bm.id">
                <tr :class="audioFreqMhz && Math.abs(bm.frequency_hz - audioFreqMhz * 1e6) < 1000 ? 'row-active' : ''">
```

This reuses the same `row-active` class and 1 kHz tolerance used on the Live page (line 249).

- [ ] **Step 3: Test manually**

Open the dashboard, go to Bookmarks, click Tune on a bookmark. Verify:
- Page stays on Bookmarks (does NOT switch to Live)
- The tuned row gets the `row-active` highlight
- Audio plays

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/index.html
git commit -m "fix(bookmarks): tune button stays on bookmarks page, add row-active highlight"
```

---

### Task 2: BookmarkGroup model and database schema

**Files:**
- Modify: `signaldeck/storage/models.py`
- Modify: `signaldeck/storage/database.py`
- Create: `tests/test_bookmark_groups.py`

- [ ] **Step 1: Write the failing test for group creation**

Create `tests/test_bookmark_groups.py`:

```python
import pytest
from datetime import datetime, timezone
from signaldeck.storage.database import Database
from signaldeck.storage.models import Bookmark


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_create_bookmark_group(db):
    gid = await db.create_bookmark_group("Fire")
    assert isinstance(gid, int)
    groups = await db.get_all_bookmark_groups()
    assert len(groups) == 1
    assert groups[0].name == "Fire"
    assert groups[0].id == gid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py::test_create_bookmark_group -v`
Expected: FAIL — `create_bookmark_group` does not exist.

- [ ] **Step 3: Add BookmarkGroup model**

In `signaldeck/storage/models.py`, add after the `Bookmark` class:

```python
@dataclass
class BookmarkGroup:
    name: str
    id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Add group tables to schema and implement create/get methods**

In `signaldeck/storage/database.py`, add to `_SCHEMA` (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS bookmark_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmark_group_members (
    group_id INTEGER NOT NULL,
    bookmark_id INTEGER NOT NULL,
    PRIMARY KEY (group_id, bookmark_id),
    FOREIGN KEY (group_id) REFERENCES bookmark_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE
);
```

Add import of `BookmarkGroup` at the top alongside `Signal, ActivityEntry`:

```python
from signaldeck.storage.models import Signal, ActivityEntry, BookmarkGroup
```

Add methods to the `Database` class:

```python
    async def create_bookmark_group(self, name: str) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO bookmark_groups (name, created_at) VALUES (?, ?)",
            (name, datetime.now(timezone.utc).isoformat()),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_all_bookmark_groups(self) -> list[BookmarkGroup]:
        cursor = await self._conn.execute(
            "SELECT * FROM bookmark_groups ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [
            BookmarkGroup(
                id=row["id"], name=row["name"],
                created_at=_str_to_dt(row["created_at"]),
            )
            for row in rows
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py::test_create_bookmark_group -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add signaldeck/storage/models.py signaldeck/storage/database.py tests/test_bookmark_groups.py
git commit -m "feat(groups): add BookmarkGroup model, schema, create/list methods"
```

---

### Task 3: Group CRUD database methods (rename, delete)

**Files:**
- Modify: `signaldeck/storage/database.py`
- Modify: `tests/test_bookmark_groups.py`

- [ ] **Step 1: Write failing tests for rename and delete**

Add to `tests/test_bookmark_groups.py`:

```python
@pytest.mark.asyncio
async def test_rename_bookmark_group(db):
    gid = await db.create_bookmark_group("Fire")
    ok = await db.rename_bookmark_group(gid, "Fire Dispatch")
    assert ok is True
    groups = await db.get_all_bookmark_groups()
    assert groups[0].name == "Fire Dispatch"


@pytest.mark.asyncio
async def test_rename_nonexistent_group(db):
    ok = await db.rename_bookmark_group(999, "Nope")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_bookmark_group(db):
    gid = await db.create_bookmark_group("Fire")
    ok = await db.delete_bookmark_group(gid)
    assert ok is True
    groups = await db.get_all_bookmark_groups()
    assert len(groups) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_group(db):
    ok = await db.delete_bookmark_group(999)
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py -k "rename or delete" -v`
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Implement rename and delete**

Add to `Database` class in `signaldeck/storage/database.py`:

```python
    async def rename_bookmark_group(self, group_id: int, new_name: str) -> bool:
        cursor = await self._conn.execute(
            "UPDATE bookmark_groups SET name = ? WHERE id = ?",
            (new_name, group_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_bookmark_group(self, group_id: int) -> bool:
        # Members are cascade-deleted by FK constraint.
        # Enable FK enforcement for this connection if not already on.
        await self._conn.execute("PRAGMA foreign_keys = ON")
        cursor = await self._conn.execute(
            "DELETE FROM bookmark_groups WHERE id = ?", (group_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/storage/database.py tests/test_bookmark_groups.py
git commit -m "feat(groups): add rename and delete methods with cascade"
```

---

### Task 4: Group membership database methods

**Files:**
- Modify: `signaldeck/storage/database.py`
- Modify: `tests/test_bookmark_groups.py`

- [ ] **Step 1: Write failing tests for membership**

Add to `tests/test_bookmark_groups.py`:

```python
async def _make_bookmark(db, freq, label):
    """Helper to insert a bookmark and return its ID."""
    bm = Bookmark(
        frequency=freq, label=label, modulation="FMN",
        decoder=None, priority=3, camp_on_active=False,
    )
    return await db.insert_bookmark(bm)


@pytest.mark.asyncio
async def test_set_group_members(db):
    gid = await db.create_bookmark_group("Fire")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")
    b2 = await _make_bookmark(db, 155310000, "BCFD Fire 1")
    b3 = await _make_bookmark(db, 151355000, "BCFD Fire 2")

    await db.set_group_members(gid, [b1, b2])
    members = await db.get_group_member_ids(gid)
    assert sorted(members) == sorted([b1, b2])

    # Replace members — b2 removed, b3 added
    await db.set_group_members(gid, [b1, b3])
    members = await db.get_group_member_ids(gid)
    assert sorted(members) == sorted([b1, b3])


@pytest.mark.asyncio
async def test_add_remove_group_member(db):
    gid = await db.create_bookmark_group("Airport")
    b1 = await _make_bookmark(db, 122700000, "UNICOM")
    b2 = await _make_bookmark(db, 128750000, "Departure")

    assert await db.add_group_member(gid, b1) is True
    assert await db.add_group_member(gid, b2) is True
    # Adding duplicate is idempotent
    assert await db.add_group_member(gid, b1) is True
    members = await db.get_group_member_ids(gid)
    assert sorted(members) == sorted([b1, b2])

    assert await db.remove_group_member(gid, b1) is True
    members = await db.get_group_member_ids(gid)
    assert members == [b2]


@pytest.mark.asyncio
async def test_get_groups_for_bookmark(db):
    g1 = await db.create_bookmark_group("Fire")
    g2 = await db.create_bookmark_group("Emergency")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")

    await db.add_group_member(g1, b1)
    await db.add_group_member(g2, b1)

    groups = await db.get_groups_for_bookmark(b1)
    names = sorted([g.name for g in groups])
    assert names == ["Emergency", "Fire"]


@pytest.mark.asyncio
async def test_get_group_member_count(db):
    gid = await db.create_bookmark_group("Fire")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")
    b2 = await _make_bookmark(db, 155310000, "BCFD Fire 1")
    await db.set_group_members(gid, [b1, b2])

    groups = await db.get_all_bookmark_groups_with_counts()
    assert len(groups) == 1
    assert groups[0]["name"] == "Fire"
    assert groups[0]["member_count"] == 2


@pytest.mark.asyncio
async def test_cascade_delete_group_clears_members(db):
    gid = await db.create_bookmark_group("Fire")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")
    await db.add_group_member(gid, b1)
    await db.delete_bookmark_group(gid)
    # Membership rows should be gone
    members = await db.get_group_member_ids(gid)
    assert members == []


@pytest.mark.asyncio
async def test_cascade_delete_bookmark_clears_membership(db):
    gid = await db.create_bookmark_group("Fire")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")
    await db.add_group_member(gid, b1)
    await db.delete_bookmark(b1)
    members = await db.get_group_member_ids(gid)
    assert members == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py -k "member or cascade or count" -v`
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Implement membership methods**

Add to `Database` class in `signaldeck/storage/database.py`:

```python
    async def get_group_member_ids(self, group_id: int) -> list[int]:
        cursor = await self._conn.execute(
            "SELECT bookmark_id FROM bookmark_group_members WHERE group_id = ? ORDER BY bookmark_id",
            (group_id,),
        )
        rows = await cursor.fetchall()
        return [row["bookmark_id"] for row in rows]

    async def set_group_members(self, group_id: int, bookmark_ids: list[int]) -> None:
        await self._conn.execute(
            "DELETE FROM bookmark_group_members WHERE group_id = ?", (group_id,)
        )
        for bid in bookmark_ids:
            await self._conn.execute(
                "INSERT INTO bookmark_group_members (group_id, bookmark_id) VALUES (?, ?)",
                (group_id, bid),
            )
        await self._conn.commit()

    async def add_group_member(self, group_id: int, bookmark_id: int) -> bool:
        await self._conn.execute(
            "INSERT OR IGNORE INTO bookmark_group_members (group_id, bookmark_id) VALUES (?, ?)",
            (group_id, bookmark_id),
        )
        await self._conn.commit()
        return True

    async def remove_group_member(self, group_id: int, bookmark_id: int) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM bookmark_group_members WHERE group_id = ? AND bookmark_id = ?",
            (group_id, bookmark_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_groups_for_bookmark(self, bookmark_id: int) -> list[BookmarkGroup]:
        cursor = await self._conn.execute(
            """SELECT g.* FROM bookmark_groups g
               JOIN bookmark_group_members m ON g.id = m.group_id
               WHERE m.bookmark_id = ?
               ORDER BY g.name""",
            (bookmark_id,),
        )
        rows = await cursor.fetchall()
        return [
            BookmarkGroup(id=row["id"], name=row["name"],
                          created_at=_str_to_dt(row["created_at"]))
            for row in rows
        ]

    async def get_all_bookmark_groups_with_counts(self) -> list[dict]:
        cursor = await self._conn.execute(
            """SELECT g.id, g.name, g.created_at, COUNT(m.bookmark_id) as member_count
               FROM bookmark_groups g
               LEFT JOIN bookmark_group_members m ON g.id = m.group_id
               GROUP BY g.id
               ORDER BY g.name"""
        )
        rows = await cursor.fetchall()
        return [
            {"id": row["id"], "name": row["name"],
             "created_at": row["created_at"],
             "member_count": row["member_count"]}
            for row in rows
        ]
```

Also enable foreign keys in `initialize()` — add after the `PRAGMA busy_timeout` line:

```python
        await self._conn.execute("PRAGMA foreign_keys = ON")
```

And remove the duplicate `PRAGMA foreign_keys = ON` from `delete_bookmark_group` since it's now set globally at init.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bookmark_groups.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add signaldeck/storage/database.py tests/test_bookmark_groups.py
git commit -m "feat(groups): add membership methods (set, add, remove, cascade)"
```

---

### Task 5: Bookmark groups API endpoints

**Files:**
- Create: `signaldeck/api/routes/bookmark_groups.py`
- Modify: `signaldeck/api/server.py`
- Create: `tests/test_bookmark_groups_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_bookmark_groups_api.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app
from signaldeck.storage.database import Database


@pytest.fixture
async def client(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "scanner": {},
    }
    app = create_app(config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_group(client):
    resp = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Fire"
    assert "id" in data


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_rename_group(client):
    create = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    gid = create.json()["id"]
    resp = await client.patch(f"/api/bookmark-groups/{gid}", json={"name": "Fire Dispatch"})
    assert resp.status_code == 200
    groups = (await client.get("/api/bookmark-groups")).json()
    assert groups[0]["name"] == "Fire Dispatch"


@pytest.mark.asyncio
async def test_delete_group(client):
    create = await client.post("/api/bookmark-groups", json={"name": "Fire"})
    gid = create.json()["id"]
    resp = await client.delete(f"/api/bookmark-groups/{gid}")
    assert resp.status_code == 200
    groups = (await client.get("/api/bookmark-groups")).json()
    assert len(groups) == 0


@pytest.mark.asyncio
async def test_set_group_members(client):
    # Create group and bookmarks
    g = (await client.post("/api/bookmark-groups", json={"name": "Fire"})).json()
    b1 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 154175000, "label": "BCFD Disp", "modulation": "FMN"
    })).json()
    b2 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 155310000, "label": "BCFD Fire 1", "modulation": "FMN"
    })).json()

    # Set members
    resp = await client.put(
        f"/api/bookmark-groups/{g['id']}/members",
        json={"bookmark_ids": [b1["id"], b2["id"]]},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    # Get members
    resp = await client.get(f"/api/bookmark-groups/{g['id']}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2


@pytest.mark.asyncio
async def test_add_and_remove_member(client):
    g = (await client.post("/api/bookmark-groups", json={"name": "Fire"})).json()
    b1 = (await client.post("/api/bookmarks", json={
        "frequency_hz": 154175000, "label": "BCFD Disp", "modulation": "FMN"
    })).json()

    # Add
    resp = await client.post(
        f"/api/bookmark-groups/{g['id']}/members",
        json={"bookmark_id": b1["id"]},
    )
    assert resp.status_code == 200

    # Remove
    resp = await client.delete(f"/api/bookmark-groups/{g['id']}/members/{b1['id']}")
    assert resp.status_code == 200

    members = (await client.get(f"/api/bookmark-groups/{g['id']}/members")).json()
    assert len(members) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bookmark_groups_api.py -v`
Expected: FAIL — route module does not exist.

- [ ] **Step 3: Create the bookmark_groups route file**

Create `signaldeck/api/routes/bookmark_groups.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from signaldeck.api.server import get_db

router = APIRouter(tags=["bookmark-groups"])


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class MemberSet(BaseModel):
    bookmark_ids: list[int]


class MemberAdd(BaseModel):
    bookmark_id: int


@router.get("/bookmark-groups")
async def list_groups():
    db = get_db()
    return await db.get_all_bookmark_groups_with_counts()


@router.post("/bookmark-groups", status_code=201)
async def create_group(data: GroupCreate):
    db = get_db()
    try:
        gid = await db.create_bookmark_group(data.name)
    except Exception:
        raise HTTPException(status_code=409, detail="Group name already exists")
    return {"id": gid, "name": data.name}


@router.patch("/bookmark-groups/{group_id}")
async def rename_group(group_id: int, data: GroupRename):
    db = get_db()
    ok = await db.rename_bookmark_group(group_id, data.name)
    if not ok:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"id": group_id, "updated": True}


@router.delete("/bookmark-groups/{group_id}")
async def delete_group(group_id: int):
    db = get_db()
    ok = await db.delete_bookmark_group(group_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"deleted": True}


@router.get("/bookmark-groups/{group_id}/members")
async def get_members(group_id: int):
    db = get_db()
    member_ids = await db.get_group_member_ids(group_id)
    bookmarks = await db.get_all_bookmarks()
    bm_map = {b.id: b for b in bookmarks}
    return [
        {"bookmark_id": mid, "label": bm_map[mid].label,
         "frequency_hz": bm_map[mid].frequency,
         "modulation": bm_map[mid].modulation}
        for mid in member_ids if mid in bm_map
    ]


@router.put("/bookmark-groups/{group_id}/members")
async def set_members(group_id: int, data: MemberSet):
    db = get_db()
    await db.set_group_members(group_id, data.bookmark_ids)
    return {"count": len(data.bookmark_ids)}


@router.post("/bookmark-groups/{group_id}/members")
async def add_member(group_id: int, data: MemberAdd):
    db = get_db()
    await db.add_group_member(group_id, data.bookmark_id)
    return {"added": True}


@router.delete("/bookmark-groups/{group_id}/members/{bookmark_id}")
async def remove_member(group_id: int, bookmark_id: int):
    db = get_db()
    ok = await db.remove_group_member(group_id, bookmark_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"removed": True}
```

- [ ] **Step 4: Register the router in server.py**

In `signaldeck/api/server.py`, add after the existing router imports (around line 133):

```python
    from signaldeck.api.routes.bookmark_groups import router as groups_router
```

And add after the existing `app.include_router` calls (around line 142):

```python
    app.include_router(groups_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bookmark_groups_api.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add signaldeck/api/routes/bookmark_groups.py signaldeck/api/server.py tests/test_bookmark_groups_api.py
git commit -m "feat(groups): add bookmark groups API endpoints"
```

---

### Task 6: Squelch-open API endpoint

**Files:**
- Modify: `signaldeck/api/routes/scanner.py`
- Create: `tests/test_squelch_endpoint.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_squelch_endpoint.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
async def client(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "scanner": {},
    }
    app = create_app(config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_squelch_open_no_gqrx(client):
    """When no gqrx client is available, return error."""
    resp = await client.get("/api/gqrx/squelch-open")
    assert resp.status_code == 503
    assert "not connected" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_squelch_open_true(client):
    """When signal is above squelch threshold, open=true."""
    from signaldeck.api.routes.scanner import _scanner_state
    mock_client = AsyncMock()
    mock_client.get_signal_strength = AsyncMock(return_value=-35.0)
    mock_client.get_squelch = AsyncMock(return_value=-60.0)
    _scanner_state["_gqrx_client"] = mock_client
    try:
        resp = await client.get("/api/gqrx/squelch-open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open"] is True
        assert data["strength_dbfs"] == -35.0
        assert data["squelch_dbfs"] == -60.0
    finally:
        _scanner_state.pop("_gqrx_client", None)


@pytest.mark.asyncio
async def test_squelch_open_false(client):
    """When signal is below squelch threshold, open=false."""
    from signaldeck.api.routes.scanner import _scanner_state
    mock_client = AsyncMock()
    mock_client.get_signal_strength = AsyncMock(return_value=-80.0)
    mock_client.get_squelch = AsyncMock(return_value=-60.0)
    _scanner_state["_gqrx_client"] = mock_client
    try:
        resp = await client.get("/api/gqrx/squelch-open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open"] is False
    finally:
        _scanner_state.pop("_gqrx_client", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_squelch_endpoint.py -v`
Expected: FAIL — endpoint does not exist.

- [ ] **Step 3: Add the squelch endpoint to scanner routes**

In `signaldeck/api/routes/scanner.py`, add the endpoint:

```python
@router.get("/gqrx/squelch-open")
async def gqrx_squelch_open():
    gqrx_client = _scanner_state.get("_gqrx_client")
    if gqrx_client is None:
        raise HTTPException(status_code=503, detail="gqrx not connected")
    try:
        strength = await gqrx_client.get_signal_strength()
        squelch = await gqrx_client.get_squelch()
        return {
            "open": strength > squelch,
            "strength_dbfs": strength,
            "squelch_dbfs": squelch,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"gqrx error: {e}")
```

Add `HTTPException` to the imports if not already present:

```python
from fastapi import APIRouter, HTTPException
```

- [ ] **Step 4: Store gqrx_client reference in scanner_state from main.py**

In `signaldeck/main.py`, find the block around line 315-326 where `_scanner_state` is populated after gqrx connects. Add one line to store the client reference:

```python
                        _scanner_state["_gqrx_client"] = gqrx_device._client
```

Add it right after `_scanner_state["tuner_device"] = gd.label` (around line 324).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_squelch_endpoint.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add signaldeck/api/routes/scanner.py signaldeck/main.py tests/test_squelch_endpoint.py
git commit -m "feat(scan): add GET /api/gqrx/squelch-open endpoint for activity scanning"
```

---

### Task 7: Frontend — group bar and manage modal (HTML)

**Files:**
- Modify: `signaldeck/web/index.html`
- Modify: `signaldeck/web/css/style.css`

- [ ] **Step 1: Add group bar above the bookmark table**

In `signaldeck/web/index.html`, after the bookmarks page header (after line 334 — after the `</div>` closing the `page-header`), add:

```html
      <!-- Group Bar -->
      <div class="card group-bar" style="margin-bottom: 1rem; padding: 0.75rem 1rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
          <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-secondary);">Groups:</span>
          <template x-for="g in bookmarkGroups" :key="g.id">
            <button class="badge badge-group" :class="managingGroupId === g.id ? 'badge-group-active' : ''"
                    @click="openManageGroup(g)"
                    x-text="g.name + ' (' + g.member_count + ')'"></button>
          </template>
          <button class="btn btn-sm" @click="showCreateGroup = true" x-show="!showCreateGroup">+ Group</button>
          <div x-show="showCreateGroup" x-cloak style="display: inline-flex; gap: 0.25rem; align-items: center;">
            <input type="text" x-model="newGroupName" placeholder="Group name" class="input-sm"
                   @keydown.enter="createGroup()" @keydown.escape="showCreateGroup = false; newGroupName = ''"
                   style="width: 140px;">
            <button class="btn btn-sm btn-primary" @click="createGroup()">Add</button>
            <button class="btn btn-sm" @click="showCreateGroup = false; newGroupName = ''">Cancel</button>
          </div>
        </div>
      </div>
```

- [ ] **Step 2: Add the manage group modal**

In `signaldeck/web/index.html`, add before the closing `</section>` of the bookmarks page (before line 380):

```html
      <!-- Manage Group Modal -->
      <div class="modal-overlay" x-show="managingGroupId !== null" x-cloak @click.self="managingGroupId = null">
        <div class="modal-card" style="max-width: 600px; max-height: 80vh; display: flex; flex-direction: column;">
          <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <h3 x-show="!editingGroupName" x-text="managingGroupName" style="margin: 0;"></h3>
              <button x-show="!editingGroupName" class="btn btn-sm" @click="editingGroupName = true; editGroupNameVal = managingGroupName">Rename</button>
              <div x-show="editingGroupName" x-cloak style="display: flex; gap: 0.25rem; align-items: center;">
                <input type="text" x-model="editGroupNameVal" class="input-sm" style="width: 180px;"
                       @keydown.enter="renameGroup()" @keydown.escape="editingGroupName = false">
                <button class="btn btn-sm btn-primary" @click="renameGroup()">Save</button>
                <button class="btn btn-sm" @click="editingGroupName = false">Cancel</button>
              </div>
            </div>
            <button class="btn btn-sm" @click="managingGroupId = null">&times;</button>
          </div>

          <!-- Filter bar -->
          <div style="padding: 0.5rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;">
            <input type="text" x-model="groupFilterText" placeholder="Search label..." class="input-sm" style="width: 160px;">
            <input type="number" x-model.number="groupFilterFreqMin" placeholder="Min MHz" class="input-sm" step="0.001" style="width: 100px;">
            <input type="number" x-model.number="groupFilterFreqMax" placeholder="Max MHz" class="input-sm" step="0.001" style="width: 100px;">
            <select x-model="groupFilterMod" class="input-sm" style="width: 100px;">
              <option value="">All mods</option>
              <template x-for="m in availableModulations" :key="m">
                <option :value="m" x-text="m"></option>
              </template>
            </select>
            <button class="btn btn-sm btn-primary" @click="selectAllFilteredForGroup()">Select all matching</button>
            <button class="btn btn-sm" @click="clearGroupSelections()">Clear all</button>
          </div>

          <!-- Bookmark checklist -->
          <div style="overflow-y: auto; flex: 1; border: 1px solid var(--border); border-radius: 4px;">
            <table class="data-table" style="margin: 0;">
              <thead><tr><th style="width: 40px;"></th><th>Frequency</th><th>Label</th><th>Mod</th></tr></thead>
              <tbody>
                <template x-for="bm in filteredBookmarksForGroup" :key="bm.id">
                  <tr>
                    <td><input type="checkbox" :checked="groupSelectedIds.includes(bm.id)"
                               @change="toggleGroupMember(bm.id)"></td>
                    <td x-text="formatFreq(bm.frequency_hz)"></td>
                    <td x-text="bm.label"></td>
                    <td><span class="badge" :class="modBadge(bm.modulation)" x-text="bm.modulation"></span></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <!-- Footer -->
          <div style="padding: 0.75rem 0 0; display: flex; justify-content: space-between;">
            <button class="btn btn-sm btn-danger" @click="deleteGroupConfirm()">Delete Group</button>
            <div style="display: flex; gap: 0.5rem;">
              <button class="btn btn-sm" @click="managingGroupId = null">Cancel</button>
              <button class="btn btn-sm btn-primary" @click="saveGroupMembers()">Save</button>
            </div>
          </div>
        </div>
      </div>
```

- [ ] **Step 3: Add CSS for group badges**

In `signaldeck/web/css/style.css`, add:

```css
/* Bookmark group pills */
.badge-group {
  cursor: pointer;
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.8rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  transition: background 0.15s;
}
.badge-group:hover {
  background: var(--accent);
  color: #fff;
}
.badge-group-active {
  background: var(--accent);
  color: #fff;
}
.input-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.85rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-primary);
}
```

- [ ] **Step 4: Test manually**

Open the dashboard → Bookmarks. Verify:
- Group bar shows with "+ Group" button
- Can create a group (shows pill with count 0)
- Clicking a group pill opens the manage modal
- Modal shows filter bar + bookmark checklist

(Functionality wired up in Task 8)

- [ ] **Step 5: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/css/style.css
git commit -m "feat(groups): add group bar and manage modal HTML/CSS"
```

---

### Task 8: Frontend — group management JavaScript

**Files:**
- Modify: `signaldeck/web/js/app.js`

- [ ] **Step 1: Add group state properties**

In `signaldeck/web/js/app.js`, add after the bookmark modal state block (after line 68, after `savingBookmark: false,`):

```javascript
    // --- Bookmark Groups ---
    bookmarkGroups: [],
    showCreateGroup: false,
    newGroupName: '',
    managingGroupId: null,
    managingGroupName: '',
    editingGroupName: false,
    editGroupNameVal: '',
    groupSelectedIds: [],
    groupFilterText: '',
    groupFilterFreqMin: null,
    groupFilterFreqMax: null,
    groupFilterMod: '',
```

- [ ] **Step 2: Add computed property for filtered bookmarks in group modal**

Add to the methods section (near the other computed getters):

```javascript
    get filteredBookmarksForGroup() {
      return this.bookmarks.filter(bm => {
        if (this.groupFilterText && !bm.label.toLowerCase().includes(this.groupFilterText.toLowerCase())) return false;
        const freqMhz = bm.frequency_hz / 1e6;
        if (this.groupFilterFreqMin && freqMhz < this.groupFilterFreqMin) return false;
        if (this.groupFilterFreqMax && freqMhz > this.groupFilterFreqMax) return false;
        if (this.groupFilterMod && bm.modulation !== this.groupFilterMod) return false;
        return true;
      });
    },

    get availableModulations() {
      const mods = new Set(this.bookmarks.map(b => b.modulation).filter(Boolean));
      return [...mods].sort();
    },
```

- [ ] **Step 3: Add group management methods**

Add to the methods section:

```javascript
    // --- Bookmark Group Methods ---

    async fetchGroups() {
      const data = await this.apiFetch('/api/bookmark-groups', { _silent: true });
      if (data) this.bookmarkGroups = data;
    },

    async createGroup() {
      if (!this.newGroupName.trim()) return;
      const result = await this.apiFetch('/api/bookmark-groups', {
        method: 'POST',
        body: JSON.stringify({ name: this.newGroupName.trim() }),
      });
      if (result) {
        this.showCreateGroup = false;
        this.newGroupName = '';
        this.fetchGroups();
      }
    },

    async openManageGroup(group) {
      this.managingGroupId = group.id;
      this.managingGroupName = group.name;
      this.editingGroupName = false;
      this.groupFilterText = '';
      this.groupFilterFreqMin = null;
      this.groupFilterFreqMax = null;
      this.groupFilterMod = '';
      // Fetch current members
      const members = await this.apiFetch(`/api/bookmark-groups/${group.id}/members`, { _silent: true });
      this.groupSelectedIds = members ? members.map(m => m.bookmark_id) : [];
    },

    toggleGroupMember(bmId) {
      const idx = this.groupSelectedIds.indexOf(bmId);
      if (idx >= 0) {
        this.groupSelectedIds.splice(idx, 1);
      } else {
        this.groupSelectedIds.push(bmId);
      }
    },

    selectAllFilteredForGroup() {
      for (const bm of this.filteredBookmarksForGroup) {
        if (!this.groupSelectedIds.includes(bm.id)) {
          this.groupSelectedIds.push(bm.id);
        }
      }
    },

    clearGroupSelections() {
      this.groupSelectedIds = [];
    },

    async saveGroupMembers() {
      if (this.managingGroupId === null) return;
      await this.apiFetch(`/api/bookmark-groups/${this.managingGroupId}/members`, {
        method: 'PUT',
        body: JSON.stringify({ bookmark_ids: this.groupSelectedIds }),
      });
      this.showToast('Group updated', 'success');
      this.managingGroupId = null;
      this.fetchGroups();
    },

    async renameGroup() {
      if (!this.editGroupNameVal.trim() || this.managingGroupId === null) return;
      await this.apiFetch(`/api/bookmark-groups/${this.managingGroupId}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: this.editGroupNameVal.trim() }),
      });
      this.managingGroupName = this.editGroupNameVal.trim();
      this.editingGroupName = false;
      this.fetchGroups();
    },

    async deleteGroupConfirm() {
      if (this.managingGroupId === null) return;
      if (!confirm(`Delete group "${this.managingGroupName}"?`)) return;
      await this.apiFetch(`/api/bookmark-groups/${this.managingGroupId}`, {
        method: 'DELETE',
      });
      this.managingGroupId = null;
      this.showToast('Group deleted', 'success');
      this.fetchGroups();
    },
```

- [ ] **Step 4: Fetch groups on init and on bookmark page navigation**

In `signaldeck/web/js/app.js`, find the `init()` method where `this.fetchBookmarks()` is called (around line 222). Add right after it:

```javascript
      this.fetchGroups();
```

Also find the `navigate()` method's switch statement for page-specific fetches (around line 273). In the `'bookmarks'` case, add `this.fetchGroups();` alongside the existing `this.fetchBookmarks();`.

- [ ] **Step 5: Test manually**

Open dashboard → Bookmarks. Test:
- Create a group "Benton Fire"
- Click the group pill — manage modal opens
- Filter by label "BCFD" — only BCFD bookmarks show
- "Select all matching" checks them all
- Save — pill shows correct count
- Rename the group
- Delete the group

- [ ] **Step 6: Commit**

```bash
git add signaldeck/web/js/app.js
git commit -m "feat(groups): add group management JavaScript (create, manage, rename, delete)"
```

---

### Task 9: Frontend — scan toolbar HTML

**Files:**
- Modify: `signaldeck/web/index.html`
- Modify: `signaldeck/web/css/style.css`

- [ ] **Step 1: Add scan toolbar after the group bar**

In `signaldeck/web/index.html`, after the group bar `</div>` and before the bookmark table `<div class="card">`, add:

```html
      <!-- Scan Toolbar -->
      <div class="card scan-toolbar" style="margin-bottom: 1rem; padding: 0.75rem 1rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
          <!-- Scope -->
          <label style="font-size: 0.85rem; display: flex; align-items: center; gap: 0.25rem;">
            Scan:
            <select x-model="scanScope" class="input-sm" style="width: 160px;">
              <option value="all">All Bookmarks</option>
              <template x-for="g in bookmarkGroups" :key="g.id">
                <option :value="g.id" x-text="g.name"></option>
              </template>
            </select>
          </label>

          <!-- Mode -->
          <label style="font-size: 0.85rem; display: flex; align-items: center; gap: 0.25rem;">
            Mode:
            <select x-model="bkScanMode" class="input-sm" style="width: 120px;">
              <option value="dwell">Dwell</option>
              <option value="activity">Activity</option>
              <option value="manual">Manual</option>
            </select>
          </label>

          <!-- Dwell time (only in dwell mode) -->
          <label x-show="bkScanMode === 'dwell'" x-cloak style="font-size: 0.85rem; display: flex; align-items: center; gap: 0.25rem;">
            Dwell:
            <select x-model.number="scanDwellMs" class="input-sm" style="width: 80px;">
              <option value="3000">3s</option>
              <option value="5000">5s</option>
              <option value="10000">10s</option>
              <option value="15000">15s</option>
              <option value="30000">30s</option>
            </select>
          </label>

          <!-- Navigation buttons -->
          <div style="display: flex; gap: 0.25rem;">
            <button class="btn btn-sm" @click="scanJumpFirst()" title="First">|&lt;</button>
            <button class="btn btn-sm" @click="scanPrev()" title="Previous">&lt;</button>
            <button class="btn btn-sm btn-primary" x-show="bkScanMode !== 'manual'"
                    @click="bkScanActive ? stopScan() : startScan()"
                    x-text="bkScanActive ? 'Stop' : 'Start'"></button>
            <button class="btn btn-sm" @click="scanNext()" title="Next">&gt;</button>
            <button class="btn btn-sm" @click="scanJumpLast()" title="Last">&gt;|</button>
          </div>

          <!-- Progress indicator -->
          <span x-show="bkScanActive || scanIndex >= 0" x-cloak style="font-size: 0.85rem; color: var(--text-secondary);">
            <span x-text="scanCurrentLabel"></span>
            <span x-show="scanList.length > 0" x-text="' (' + (scanIndex + 1) + '/' + scanList.length + ')'"></span>
          </span>
        </div>
      </div>
```

- [ ] **Step 2: Add scan toolbar CSS**

In `signaldeck/web/css/style.css`, add:

```css
/* Scan toolbar */
.scan-toolbar .btn-sm {
  min-width: 32px;
  text-align: center;
}
```

- [ ] **Step 3: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/css/style.css
git commit -m "feat(scan): add scan toolbar HTML/CSS to bookmarks page"
```

---

### Task 10: Frontend — scan logic JavaScript

**Files:**
- Modify: `signaldeck/web/js/app.js`

- [ ] **Step 1: Add scan state properties**

In `signaldeck/web/js/app.js`, add after the bookmark group state properties:

```javascript
    // --- Bookmark Scanning ---
    bkScanActive: false,
    bkScanMode: 'dwell',       // 'dwell' | 'activity' | 'manual'
    scanScope: 'all',          // 'all' | group ID (number)
    scanDwellMs: 5000,
    scanIndex: -1,
    _scanTimer: null,
    _scanSquelchPoll: null,
```

- [ ] **Step 2: Add scanList computed property and scanCurrentLabel**

Add to the getters/computed section:

```javascript
    get scanList() {
      let list = [...this.bookmarks];
      if (this.scanScope !== 'all') {
        const gid = parseInt(this.scanScope);
        const group = this.bookmarkGroups.find(g => g.id === gid);
        if (group && group._memberIds) {
          list = list.filter(bm => group._memberIds.includes(bm.id));
        }
      }
      // Sort by frequency ascending
      list.sort((a, b) => a.frequency_hz - b.frequency_hz);
      return list;
    },

    get scanCurrentLabel() {
      const list = this.scanList;
      if (this.scanIndex >= 0 && this.scanIndex < list.length) {
        return list[this.scanIndex].label;
      }
      return '';
    },
```

- [ ] **Step 3: Add scan control methods**

Add to the methods section:

```javascript
    // --- Bookmark Scan Methods ---

    async _loadScanScopeMembers() {
      // Pre-fetch group member IDs so scanList can filter
      if (this.scanScope === 'all') return;
      const gid = parseInt(this.scanScope);
      const group = this.bookmarkGroups.find(g => g.id === gid);
      if (!group) return;
      const members = await this.apiFetch(`/api/bookmark-groups/${gid}/members`, { _silent: true });
      if (members) group._memberIds = members.map(m => m.bookmark_id);
    },

    async startScan() {
      await this._loadScanScopeMembers();
      const list = this.scanList;
      if (list.length === 0) {
        this.showToast('No bookmarks to scan', 'warning');
        return;
      }
      this.bkScanActive = true;
      if (this.scanIndex < 0 || this.scanIndex >= list.length) this.scanIndex = 0;
      this.scanTuneCurrent();

      if (this.bkScanMode === 'dwell') {
        this._scanTimer = setTimeout(() => this._dwellAdvance(), this.scanDwellMs);
      } else if (this.bkScanMode === 'activity') {
        this._scanSquelchPoll = setInterval(() => this._activityPoll(), 500);
      }
    },

    stopScan() {
      this.bkScanActive = false;
      if (this._scanTimer) { clearTimeout(this._scanTimer); this._scanTimer = null; }
      if (this._scanSquelchPoll) { clearInterval(this._scanSquelchPoll); this._scanSquelchPoll = null; }
    },

    scanTuneCurrent() {
      const list = this.scanList;
      if (this.scanIndex < 0 || this.scanIndex >= list.length) return;
      const bm = list[this.scanIndex];
      this.tuneAndListen(bm.frequency_hz, bm.modulation);
    },

    async scanNext() {
      await this._loadScanScopeMembers();
      const list = this.scanList;
      if (list.length === 0) return;
      if (this.bkScanMode === 'manual') this.bkScanActive = true;
      this.scanIndex = (this.scanIndex + 1) % list.length;
      this.scanTuneCurrent();
      this._restartScanTimer();
    },

    async scanPrev() {
      await this._loadScanScopeMembers();
      const list = this.scanList;
      if (list.length === 0) return;
      if (this.bkScanMode === 'manual') this.bkScanActive = true;
      this.scanIndex = (this.scanIndex - 1 + list.length) % list.length;
      this.scanTuneCurrent();
      this._restartScanTimer();
    },

    async scanJumpFirst() {
      await this._loadScanScopeMembers();
      const list = this.scanList;
      if (list.length === 0) return;
      this.scanIndex = 0;
      this.scanTuneCurrent();
      this._restartScanTimer();
    },

    async scanJumpLast() {
      await this._loadScanScopeMembers();
      const list = this.scanList;
      if (list.length === 0) return;
      this.scanIndex = list.length - 1;
      this.scanTuneCurrent();
      this._restartScanTimer();
    },

    _restartScanTimer() {
      if (!this.bkScanActive || this.bkScanMode !== 'dwell') return;
      if (this._scanTimer) clearTimeout(this._scanTimer);
      this._scanTimer = setTimeout(() => this._dwellAdvance(), this.scanDwellMs);
    },

    _dwellAdvance() {
      if (!this.bkScanActive) return;
      const list = this.scanList;
      this.scanIndex = (this.scanIndex + 1) % list.length;
      this.scanTuneCurrent();
      this._scanTimer = setTimeout(() => this._dwellAdvance(), this.scanDwellMs);
    },

    async _activityPoll() {
      if (!this.bkScanActive) return;
      try {
        const data = await this.apiFetch('/api/gqrx/squelch-open', { _silent: true });
        if (!data) return;
        if (!data.open) {
          // Squelch closed — advance after brief settle time
          await new Promise(r => setTimeout(r, 300));
          if (!this.bkScanActive) return;
          const list = this.scanList;
          this.scanIndex = (this.scanIndex + 1) % list.length;
          this.scanTuneCurrent();
        }
        // If squelch is open, stay on current frequency (do nothing)
      } catch (e) {
        // Ignore polling errors
      }
    },
```

- [ ] **Step 4: Clean up scan timers when navigating away or stopping audio**

Find the `navigate()` method. Add at the top of it (before the existing page logic):

```javascript
      // Stop bookmark scan when leaving bookmarks page
      if (this.bkScanActive && page !== 'bookmarks') {
        this.stopScan();
      }
```

- [ ] **Step 5: Test manually**

Open dashboard → Bookmarks. Test each mode:

**Dwell mode:**
- Select scope "All Bookmarks", mode "Dwell", dwell 3s
- Click Start — should cycle through bookmarks every 3 seconds
- Progress shows current label and position
- Click Stop — stays on current bookmark
- Prev/Next buttons work during scan

**Activity mode:**
- Select mode "Activity", click Start
- Should advance through silent frequencies quickly
- Should pause on any frequency with an open signal
- Click Stop

**Manual mode:**
- Select mode "Manual"
- Start/Stop button is hidden
- Click Next/Prev to step through bookmarks

- [ ] **Step 6: Commit**

```bash
git add signaldeck/web/js/app.js
git commit -m "feat(scan): add bookmark scan logic (dwell, activity, manual modes)"
```

---

### Task 11: Final integration test and cleanup

**Files:**
- All modified files from previous tasks

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q`
Expected: all pass, no regressions

- [ ] **Step 2: Manual integration test**

Test the full flow in the browser:
1. Go to Bookmarks page
2. Create a group "Benton Fire" 
3. Click the group pill, filter by "BCFD", select all matching, save
4. Set scan scope to "Benton Fire", mode to Dwell 5s, click Start
5. Verify it cycles through only the group's bookmarks
6. Switch to Activity mode — verify it holds on active signals
7. Switch to Manual mode — verify Next/Prev work
8. Click Tune on a random bookmark — verify page stays on Bookmarks
9. Verify the tuned row shows `row-active` highlight

- [ ] **Step 3: Restart signaldeck service**

```bash
systemctl --user restart signaldeck.service
```

- [ ] **Step 4: Commit all remaining changes (if any)**

Check `git status` — if clean, nothing to do. If there are uncommitted tweaks from testing, commit them.

```bash
git add -A && git commit -m "fix: integration tweaks from bookmark scanning testing"
```

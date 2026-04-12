import pytest
from signaldeck.storage.database import Database
from signaldeck.storage.models import Bookmark


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    yield d
    await d.close()


async def _make_bookmark(db, freq, label):
    bm = Bookmark(
        frequency=freq, label=label, modulation="FMN",
        decoder=None, priority=3, camp_on_active=False,
    )
    return await db.insert_bookmark(bm)


@pytest.mark.asyncio
async def test_create_bookmark_group(db):
    gid = await db.create_bookmark_group("Fire")
    assert isinstance(gid, int)
    groups = await db.get_all_bookmark_groups()
    assert len(groups) == 1
    assert groups[0].name == "Fire"
    assert groups[0].id == gid


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


@pytest.mark.asyncio
async def test_set_group_members(db):
    gid = await db.create_bookmark_group("Fire")
    b1 = await _make_bookmark(db, 154175000, "BCFD Disp")
    b2 = await _make_bookmark(db, 155310000, "BCFD Fire 1")
    b3 = await _make_bookmark(db, 151355000, "BCFD Fire 2")
    await db.set_group_members(gid, [b1, b2])
    members = await db.get_group_member_ids(gid)
    assert sorted(members) == sorted([b1, b2])
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
    assert await db.add_group_member(gid, b1) is True  # idempotent
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

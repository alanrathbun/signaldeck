"""Tests for the remember_tokens SQLite layer in Database."""
import pytest

from signaldeck.storage.database import Database


@pytest.fixture
async def db(tmp_path):
    """Fresh Database instance using a file-backed sqlite in tmp_path."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


async def test_remember_tokens_table_exists(db):
    tables = await db.list_tables()
    assert "remember_tokens" in tables


async def test_insert_and_get_remember_token(db):
    token_id = await db.insert_remember_token(
        token_hash="abc123" * 10 + "abcd",  # 64 chars
        user_agent="iPhone Safari",
        ip_first_seen="100.93.40.9",
        label="iPhone Safari",
    )
    assert token_id > 0

    row = await db.get_remember_token_by_hash("abc123" * 10 + "abcd")
    assert row is not None
    assert row["id"] == token_id
    assert row["user_agent"] == "iPhone Safari"
    assert row["ip_first_seen"] == "100.93.40.9"
    assert row["label"] == "iPhone Safari"
    assert row["created_at"] is not None
    assert row["last_used_at"] is not None


async def test_get_remember_token_by_hash_missing_returns_none(db):
    row = await db.get_remember_token_by_hash("nonexistent-hash")
    assert row is None


async def test_update_remember_token_last_used(db):
    token_id = await db.insert_remember_token(
        token_hash="hash1",
        user_agent="ua",
        ip_first_seen="1.2.3.4",
        label="test",
    )
    row_before = await db.get_remember_token_by_hash("hash1")
    import asyncio
    await asyncio.sleep(0.01)  # Ensure timestamp would differ
    await db.update_remember_token_last_used("hash1")
    row_after = await db.get_remember_token_by_hash("hash1")
    assert row_after["last_used_at"] >= row_before["last_used_at"]


async def test_list_remember_tokens_returns_all_without_hash(db):
    await db.insert_remember_token(
        token_hash="hash1", user_agent="ua1", ip_first_seen="1.1.1.1", label="one"
    )
    await db.insert_remember_token(
        token_hash="hash2", user_agent="ua2", ip_first_seen="2.2.2.2", label="two"
    )
    rows = await db.list_remember_tokens()
    assert len(rows) == 2
    assert {r["label"] for r in rows} == {"one", "two"}
    # token_hash must NOT be exposed in list output
    for r in rows:
        assert "token_hash" not in r


async def test_rename_remember_token(db):
    token_id = await db.insert_remember_token(
        token_hash="hash1", user_agent="ua", ip_first_seen="1.1.1.1", label="old"
    )
    ok = await db.rename_remember_token(token_id, "new label")
    assert ok is True
    row = await db.get_remember_token_by_hash("hash1")
    assert row["label"] == "new label"


async def test_rename_remember_token_missing_returns_false(db):
    ok = await db.rename_remember_token(999999, "nope")
    assert ok is False


async def test_revoke_remember_token(db):
    token_id = await db.insert_remember_token(
        token_hash="hash1", user_agent="ua", ip_first_seen="1.1.1.1", label="doomed"
    )
    ok = await db.revoke_remember_token(token_id)
    assert ok is True
    row = await db.get_remember_token_by_hash("hash1")
    assert row is None


async def test_revoke_remember_token_missing_returns_false(db):
    ok = await db.revoke_remember_token(999999)
    assert ok is False


async def test_token_hash_unique_constraint(db):
    await db.insert_remember_token(
        token_hash="dup", user_agent="a", ip_first_seen="1.1.1.1", label="first"
    )
    with pytest.raises(Exception):
        await db.insert_remember_token(
            token_hash="dup", user_agent="b", ip_first_seen="2.2.2.2", label="second"
        )

"""Tests for AuthManager's remember-me token methods."""
import asyncio
import hashlib

import pytest

from signaldeck.api.auth import AuthManager
from signaldeck.storage.database import Database


@pytest.fixture
async def mgr(tmp_path):
    cred_path = str(tmp_path / "credentials.yaml")
    m = AuthManager(credentials_path=cred_path)
    m.initialize()
    return m


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    yield database
    await database.close()


async def test_create_remember_token_returns_raw_and_persists_hash(mgr, db):
    raw = await mgr.create_remember_token(
        db, user_agent="Mozilla/5.0 iPhone Safari", ip="100.93.40.9"
    )
    assert isinstance(raw, str)
    assert len(raw) >= 32  # token_urlsafe(32) -> ~43 chars

    # The DB row should exist under the SHA-256 of the raw token.
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = await db.get_remember_token_by_hash(expected_hash)
    assert row is not None
    assert row["ip_first_seen"] == "100.93.40.9"
    # Label is auto-generated from UA
    assert row["label"] is not None
    assert len(row["label"]) > 0


async def test_create_remember_token_accepts_explicit_label(mgr, db):
    raw = await mgr.create_remember_token(
        db, user_agent="ua", ip="1.1.1.1", label="Custom Device"
    )
    row = await db.get_remember_token_by_hash(
        hashlib.sha256(raw.encode()).hexdigest()
    )
    assert row["label"] == "Custom Device"


async def test_verify_remember_token_accepts_valid(mgr, db):
    raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
    assert await mgr.verify_remember_token(db, raw) is True


async def test_verify_remember_token_rejects_unknown(mgr, db):
    assert await mgr.verify_remember_token(db, "fake-token") is False
    assert await mgr.verify_remember_token(db, "") is False


async def test_verify_remember_token_updates_last_used(mgr, db):
    raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
    h = hashlib.sha256(raw.encode()).hexdigest()

    row_before = await db.get_remember_token_by_hash(h)
    await asyncio.sleep(0.01)
    await mgr.verify_remember_token(db, raw)
    row_after = await db.get_remember_token_by_hash(h)
    assert row_after["last_used_at"] > row_before["last_used_at"]


async def test_verify_remember_token_does_not_update_on_failure(mgr, db):
    # Create a real token so the table has at least one row
    real_raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
    real_h = hashlib.sha256(real_raw.encode()).hexdigest()
    before = (await db.get_remember_token_by_hash(real_h))["last_used_at"]

    await asyncio.sleep(0.01)
    # Verify a fake token — should not touch any row
    await mgr.verify_remember_token(db, "not-a-real-token")
    after = (await db.get_remember_token_by_hash(real_h))["last_used_at"]
    assert after == before


async def test_label_auto_generation_iphone(mgr, db):
    raw = await mgr.create_remember_token(
        db,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                   "Mobile/15E148 Safari/604.1",
        ip="1.1.1.1",
    )
    row = await db.get_remember_token_by_hash(hashlib.sha256(raw.encode()).hexdigest())
    assert "iPhone" in row["label"]


async def test_label_auto_generation_fallback(mgr, db):
    raw = await mgr.create_remember_token(
        db, user_agent="some-completely-unknown-client/1.0", ip="1.1.1.1"
    )
    row = await db.get_remember_token_by_hash(hashlib.sha256(raw.encode()).hexdigest())
    assert row["label"] is not None
    # Fallback is first 40 chars of UA
    assert row["label"].startswith("some-completely-unknown-client")


async def test_raw_token_never_in_database(mgr, db):
    raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
    # Query the raw table directly — the raw token must not appear anywhere
    cursor = await db._conn.execute("SELECT token_hash FROM remember_tokens")
    rows = await cursor.fetchall()
    for row in rows:
        assert row[0] != raw
        # The hash is 64-char hex
        assert len(row[0]) == 64
        int(row[0], 16)  # Must be valid hex


async def test_verify_remember_token_returns_false_on_db_error(mgr):
    """A DB error during verify must fail-closed (return False)."""
    class BrokenDB:
        async def get_remember_token_by_hash(self, _):
            raise RuntimeError("simulated database failure")

    result = await mgr.verify_remember_token(BrokenDB(), "anytoken")
    assert result is False


async def test_label_auto_generation_opera(mgr, db):
    raw = await mgr.create_remember_token(
        db,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/109.0.0.0 Safari/537.36 OPR/95.0.0.0",
        ip="1.1.1.1",
    )
    row = await db.get_remember_token_by_hash(hashlib.sha256(raw.encode()).hexdigest())
    assert row["label"] == "Windows Opera"

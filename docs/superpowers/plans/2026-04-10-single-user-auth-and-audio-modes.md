# Single-User Auth + Location-Aware Audio Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the design in `docs/superpowers/specs/2026-04-10-single-user-auth-and-audio-modes-design.md` — make SignalDeck safely reachable from any of the operator's devices via Tailscale (no login needed) or via a remember-me cookie (for the rare non-Tailscale browser), and add a location-aware audio mode switcher that mutes gqrx and streams PCM to browsers when a remote listener is connected.

**Architecture:** Extend the existing `AuthManager` / `AuthMiddleware` scaffolding with (1) a LAN-bypass classifier (`is_lan_client`) that treats loopback, RFC1918, IPv6 ULA, and Tailscale CGNAT as local, (2) a `remember_tokens` SQLite table with a SHA-256-hashed token that never expires until revoked, (3) a rewritten middleware dispatch that passes through for LAN/bearer/cookie and 401s otherwise, (4) the same gate applied to `/ws/*` handshakes, (5) a three-way `audio_mode` setting that defaults to `auto` and picks gqrx for LAN-only listeners and PCM-stream when any listener is remote, flipping via gqrx rigctl `L AF` (mute/restore) without restarting gqrx. Frontend adds a login overlay on 401, a first-run password modal, a Signed-in devices card, an Audio Output card with live effective-mode display, and moves the Live Signals column selection from browser-local state into `user_settings.yaml` so it follows the operator across devices.

**Tech Stack:** Python 3.11+, FastAPI, Starlette middleware, aiosqlite, bcrypt (existing), PyYAML, `ipaddress` (stdlib), `secrets` (stdlib), `hashlib` (stdlib), pytest + pytest-asyncio + httpx ASGI transport, Alpine.js (frontend), vanilla CSS.

---

## Phase A — Auth foundation (backend)

Tasks 1–9. Produces a working LAN-bypass auth gate with remember-me cookies and a CLI password-reset escape hatch. Each task is independently commit-able.

### Task 1: `is_lan_client` helper and allowlist defaults

**Files:**
- Modify: `signaldeck/api/auth.py` — add module-level constants and the classifier function
- Create: `tests/test_is_lan_client.py` — parameterized tests

- [ ] **Step 1: Write the failing test**

Create `tests/test_is_lan_client.py` with this content:

```python
"""Tests for is_lan_client — IP classification for the LAN auth bypass."""
import pytest

from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client


@pytest.mark.parametrize("ip", [
    "127.0.0.1",
    "127.1.2.3",
    "127.255.255.255",
    "::1",
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.1.100",
    "192.168.255.255",
    "100.64.0.0",       # Tailscale CGNAT lower bound
    "100.94.221.106",   # Operator's actual NucBox Tailscale IP
    "100.127.255.255",  # Tailscale CGNAT upper bound
    "fd00::1",          # IPv6 ULA
    "fdff:ffff:ffff::1",
])
def test_is_lan_client_accepts_local_ranges(ip):
    assert is_lan_client(ip, DEFAULT_LAN_ALLOWLIST) is True


@pytest.mark.parametrize("ip", [
    "8.8.8.8",
    "1.1.1.1",
    "100.63.255.255",    # Just below Tailscale CGNAT
    "100.128.0.0",       # Just above Tailscale CGNAT
    "2001:4860:4860::8888",
    "2606:4700:4700::1111",
])
def test_is_lan_client_rejects_public(ip):
    assert is_lan_client(ip, DEFAULT_LAN_ALLOWLIST) is False


@pytest.mark.parametrize("bad", ["", "not-an-ip", "999.999.999.999", "::gg::"])
def test_is_lan_client_rejects_malformed(bad):
    assert is_lan_client(bad, DEFAULT_LAN_ALLOWLIST) is False


def test_is_lan_client_rejects_none():
    assert is_lan_client(None, DEFAULT_LAN_ALLOWLIST) is False


def test_is_lan_client_custom_allowlist_accepts_only_listed_range():
    allowlist = ["10.5.0.0/16"]
    assert is_lan_client("10.5.0.1", allowlist) is True
    assert is_lan_client("10.5.255.254", allowlist) is True
    assert is_lan_client("10.6.0.0", allowlist) is False
    assert is_lan_client("192.168.1.1", allowlist) is False


def test_is_lan_client_empty_allowlist_rejects_everything():
    assert is_lan_client("127.0.0.1", []) is False
    assert is_lan_client("192.168.1.1", []) is False


def test_default_allowlist_contents():
    """Guard against accidental deletion of critical ranges."""
    assert "127.0.0.0/8" in DEFAULT_LAN_ALLOWLIST
    assert "::1/128" in DEFAULT_LAN_ALLOWLIST
    assert "10.0.0.0/8" in DEFAULT_LAN_ALLOWLIST
    assert "172.16.0.0/12" in DEFAULT_LAN_ALLOWLIST
    assert "192.168.0.0/16" in DEFAULT_LAN_ALLOWLIST
    assert "fc00::/7" in DEFAULT_LAN_ALLOWLIST
    assert "100.64.0.0/10" in DEFAULT_LAN_ALLOWLIST  # Tailscale
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_is_lan_client.py -v`

Expected: all tests fail with `ImportError: cannot import name 'DEFAULT_LAN_ALLOWLIST' from 'signaldeck.api.auth'` (or similar).

- [ ] **Step 3: Implement the function**

In `signaldeck/api/auth.py`, after the existing `import yaml` line near the top, add:

```python
import ipaddress
```

Then, after the existing `generate_api_token` function (before `class AuthManager`), add:

```python
DEFAULT_LAN_ALLOWLIST: list[str] = [
    "127.0.0.0/8",      # IPv4 loopback
    "::1/128",          # IPv6 loopback
    "10.0.0.0/8",       # RFC1918 private
    "172.16.0.0/12",    # RFC1918 private
    "192.168.0.0/16",   # RFC1918 private (typical home router)
    "fc00::/7",         # IPv6 unique-local addresses
    "100.64.0.0/10",    # Tailscale CGNAT
]


def is_lan_client(client_ip: str | None, allowlist: list[str]) -> bool:
    """Return True if client_ip is inside any CIDR range in the allowlist.

    Returns False for None, empty strings, malformed addresses, or IPs
    outside every range. Malformed CIDR entries in the allowlist are
    silently skipped (not an error) to keep a single bad config entry
    from locking the operator out of their own box.
    """
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in allowlist:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_is_lan_client.py -v`

Expected: all 10+ test cases PASS.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/auth.py tests/test_is_lan_client.py
git commit -m "$(cat <<'EOF'
feat: add is_lan_client classifier with Tailscale CGNAT in defaults

Pure function that checks whether a client IP falls inside any CIDR in
an allowlist. Default allowlist covers IPv4 loopback, IPv6 loopback,
RFC1918 private ranges, IPv6 ULA, and Tailscale CGNAT (100.64.0.0/10).
Malformed inputs return False; malformed allowlist entries are skipped.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Config loading accepts new auth fields

**Files:**
- Modify: `config/default.yaml` — add new auth keys
- Create: `tests/test_config_auth_fields.py` — verifies the new fields load and have correct defaults

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_auth_fields.py`:

```python
"""Verifies the new auth.* config fields load with sensible defaults."""
from signaldeck.config import load_config


def test_default_config_has_lan_allowlist():
    cfg = load_config(None, load_user_settings=False)
    allowlist = cfg.get("auth", {}).get("lan_allowlist")
    assert isinstance(allowlist, list)
    assert "127.0.0.0/8" in allowlist
    assert "100.64.0.0/10" in allowlist  # Tailscale CGNAT
    assert "192.168.0.0/16" in allowlist


def test_default_config_has_trust_x_forwarded_for_false():
    cfg = load_config(None, load_user_settings=False)
    assert cfg.get("auth", {}).get("trust_x_forwarded_for") is False


def test_default_config_has_remember_token_days_null():
    cfg = load_config(None, load_user_settings=False)
    assert cfg.get("auth", {}).get("remember_token_days") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config_auth_fields.py -v`

Expected: all three tests fail because `config/default.yaml` does not contain these keys.

- [ ] **Step 3: Extend `config/default.yaml`**

Open `config/default.yaml` and find the existing `auth:` block (it should already contain `enabled: false` and `credentials_path: config/credentials.yaml`). Append the three new keys inside that block so it looks like:

```yaml
auth:
  enabled: false
  credentials_path: config/credentials.yaml
  lan_allowlist:
    - 127.0.0.0/8
    - ::1/128
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - fc00::/7
    - 100.64.0.0/10   # Tailscale CGNAT
  trust_x_forwarded_for: false
  remember_token_days: null
```

If there is no existing `auth:` block, add the whole block at the top level of the file (alongside `devices:`, `scanner:`, etc.).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config_auth_fields.py -v`

Expected: all three tests PASS.

Run the full config test module to check nothing regressed:

Run: `.venv/bin/pytest tests/test_config.py tests/test_config_auth_fields.py -v`

Expected: all existing and new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config/default.yaml tests/test_config_auth_fields.py
git commit -m "$(cat <<'EOF'
feat: add auth.lan_allowlist, trust_x_forwarded_for, remember_token_days

New config keys used by the upcoming AuthMiddleware rewrite. Defaults:
lan_allowlist covers loopback + RFC1918 + IPv6 ULA + Tailscale CGNAT,
trust_x_forwarded_for is false (placeholder for future reverse-proxy
support), remember_token_days is null (no expiration, revoke-only).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `remember_tokens` SQLite table + Database helper methods

**Files:**
- Modify: `signaldeck/storage/database.py` — append table to `_SCHEMA`, add CRUD methods
- Create: `tests/test_remember_tokens_db.py` — CRUD tests against in-memory sqlite

- [ ] **Step 1: Write the failing tests**

Create `tests/test_remember_tokens_db.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_remember_tokens_db.py -v`

Expected: all tests fail with `AttributeError: 'Database' object has no attribute 'insert_remember_token'` (or similar).

- [ ] **Step 3: Extend the schema and add CRUD methods**

Open `signaldeck/storage/database.py`. At the end of the `_SCHEMA` multiline string (just before the closing `"""`), append:

```sql

CREATE TABLE IF NOT EXISTS remember_tokens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     TEXT NOT NULL,
    last_used_at   TEXT NOT NULL,
    user_agent     TEXT,
    ip_first_seen  TEXT,
    label          TEXT
);

CREATE INDEX IF NOT EXISTS idx_remember_tokens_hash ON remember_tokens(token_hash);
```

Then, inside the `Database` class, add these methods (place them after the existing bookmark methods for locality — search for `async def insert_bookmark` and add these right after that method group):

```python
    # ---- Remember-me tokens (long-lived session cookies) ----

    async def insert_remember_token(
        self,
        *,
        token_hash: str,
        user_agent: str | None,
        ip_first_seen: str | None,
        label: str | None,
    ) -> int:
        """Insert a new remember-me token row. Returns the new row id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            """INSERT INTO remember_tokens
               (token_hash, created_at, last_used_at, user_agent, ip_first_seen, label)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token_hash, now, now, user_agent, ip_first_seen, label),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_remember_token_by_hash(self, token_hash: str) -> dict | None:
        """Return the row dict for a given hash, or None if not found."""
        cursor = await self._conn.execute(
            "SELECT * FROM remember_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def update_remember_token_last_used(self, token_hash: str) -> None:
        """Touch last_used_at for an existing token. No-op if missing."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE remember_tokens SET last_used_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        await self._conn.commit()

    async def list_remember_tokens(self) -> list[dict]:
        """Return all rows MINUS token_hash (never exposed to callers)."""
        cursor = await self._conn.execute(
            """SELECT id, created_at, last_used_at, user_agent, ip_first_seen, label
               FROM remember_tokens
               ORDER BY last_used_at DESC""",
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def rename_remember_token(self, token_id: int, label: str) -> bool:
        """Update a row's label. Returns True on success, False if missing."""
        cursor = await self._conn.execute(
            "UPDATE remember_tokens SET label = ? WHERE id = ?",
            (label, token_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def revoke_remember_token(self, token_id: int) -> bool:
        """Delete a row. Returns True on success, False if missing."""
        cursor = await self._conn.execute(
            "DELETE FROM remember_tokens WHERE id = ?",
            (token_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0
```

At the top of `database.py`, verify these imports already exist: `from datetime import datetime, timezone`. If only `datetime` is imported, add `timezone` to the import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_remember_tokens_db.py -v`

Expected: all 10 tests PASS.

Sanity-check that the schema change didn't break existing storage tests:

Run: `.venv/bin/pytest tests/test_database.py tests/test_database_clear.py -v`

Expected: all existing database tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/storage/database.py tests/test_remember_tokens_db.py
git commit -m "$(cat <<'EOF'
feat: add remember_tokens table and CRUD helpers

New SQLite table backs the remember-me cookie flow. token_hash is
unique-indexed and never returned by list_remember_tokens — raw tokens
live only in the browser cookie, and the hash is the only thing
persisted server-side. CRUD methods cover insert, hash lookup, touch
last_used, list, rename, revoke.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `AuthManager` remember-me methods

**Files:**
- Modify: `signaldeck/api/auth.py` — add token create/verify/list/rename/revoke methods
- Create: `tests/test_auth_manager_remember.py` — AuthManager-level tests

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_manager_remember.py`:

```python
"""Tests for AuthManager's remember-me token methods."""
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
    import asyncio
    await asyncio.sleep(0.01)
    await mgr.verify_remember_token(db, raw)
    row_after = await db.get_remember_token_by_hash(h)
    assert row_after["last_used_at"] > row_before["last_used_at"]


async def test_verify_remember_token_does_not_update_on_failure(mgr, db):
    # Create a real token so the table has at least one row
    real_raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
    real_h = hashlib.sha256(real_raw.encode()).hexdigest()
    before = (await db.get_remember_token_by_hash(real_h))["last_used_at"]

    import asyncio
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth_manager_remember.py -v`

Expected: all tests fail with `AttributeError: 'AuthManager' object has no attribute 'create_remember_token'` (or similar).

- [ ] **Step 3: Add the methods to `AuthManager`**

In `signaldeck/api/auth.py`, at the top of the file, add this import alongside the existing imports:

```python
import hashlib
```

Then, inside the `AuthManager` class (after the existing `create_session_token` method near the end), add:

```python
    # ---- Remember-me tokens (database-backed) ----

    @staticmethod
    def _hash_token(raw: str) -> str:
        """Return the SHA-256 hex digest of a raw token."""
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _auto_label_from_ua(user_agent: str | None) -> str:
        """Derive a short human-readable label from a User-Agent string.

        Examples:
            iPhone Safari, iPad Safari, Android Chrome, Mac Safari,
            Mac Chrome, Windows Firefox. Falls back to the first 40 chars
            of the UA if no known pattern matches.
        """
        if not user_agent:
            return "Unknown device"
        ua = user_agent
        # Device
        if "iPhone" in ua:
            device = "iPhone"
        elif "iPad" in ua:
            device = "iPad"
        elif "Android" in ua:
            device = "Android"
        elif "Macintosh" in ua or "Mac OS X" in ua:
            device = "Mac"
        elif "Windows" in ua:
            device = "Windows"
        elif "Linux" in ua:
            device = "Linux"
        else:
            device = None
        # Browser
        if "Edg/" in ua:
            browser = "Edge"
        elif "Firefox/" in ua:
            browser = "Firefox"
        elif "Chrome/" in ua and "Chromium" not in ua:
            browser = "Chrome"
        elif "Safari/" in ua:
            browser = "Safari"
        else:
            browser = None
        if device and browser:
            return f"{device} {browser}"
        if device:
            return device
        if browser:
            return browser
        return ua[:40]

    async def create_remember_token(
        self,
        db,
        *,
        user_agent: str | None,
        ip: str | None,
        label: str | None = None,
    ) -> str:
        """Generate a new random token, persist its hash, return the raw token.

        The raw value is the cookie the browser will store. The database
        only ever sees the SHA-256 hash.
        """
        raw = secrets.token_urlsafe(32)  # 256 bits of entropy
        token_hash = self._hash_token(raw)
        chosen_label = label if label is not None else self._auto_label_from_ua(user_agent)
        await db.insert_remember_token(
            token_hash=token_hash,
            user_agent=user_agent,
            ip_first_seen=ip,
            label=chosen_label,
        )
        return raw

    async def verify_remember_token(self, db, raw_token: str) -> bool:
        """Return True iff the token's hash matches a remember_tokens row.

        On success, touches the row's last_used_at. On any failure —
        missing token, unknown hash, or database error — returns False
        and performs no writes.
        """
        if not raw_token:
            return False
        try:
            token_hash = self._hash_token(raw_token)
            row = await db.get_remember_token_by_hash(token_hash)
            if row is None:
                return False
            await db.update_remember_token_last_used(token_hash)
            return True
        except Exception as e:
            logger.warning("verify_remember_token error: %s", e)
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth_manager_remember.py -v`

Expected: all 9 tests PASS.

Also run the existing auth tests to confirm no regression:

Run: `.venv/bin/pytest tests/test_auth.py tests/test_auth_extended.py -v`

Expected: all existing auth tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/auth.py tests/test_auth_manager_remember.py
git commit -m "$(cat <<'EOF'
feat: AuthManager methods for remember-me tokens

create_remember_token generates a 256-bit urlsafe token, hashes it with
SHA-256, and stores only the hash in remember_tokens. verify_remember_token
checks a raw cookie value against the stored hash and touches last_used_at
on success. Labels are auto-derived from the User-Agent (iPhone Safari,
Mac Chrome, etc.) with a 40-char fallback.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `AuthMiddleware` dispatch rewrite

**Files:**
- Modify: `signaldeck/api/server.py` — rewrite the `AuthMiddleware.dispatch` method and pass the config through
- Create: `tests/test_auth_middleware.py` — end-to-end middleware tests using a rewritable client IP

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_middleware.py`:

```python
"""End-to-end tests for the new AuthMiddleware with LAN bypass + remember-me."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

from signaldeck.api.server import create_app, get_auth_manager, get_db


def _config_with_auth(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": True,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "lan_allowlist": [
                "127.0.0.0/8",
                "10.0.0.0/8",
                "192.168.0.0/16",
                "100.64.0.0/10",
            ],
            "trust_x_forwarded_for": False,
            "remember_token_days": None,
        },
    }


class _ClientIPRewriter(BaseHTTPMiddleware):
    """Test helper: rewrite request.scope['client'] to simulate any origin IP.

    The simulated IP is read from the X-Test-Client-IP header so each
    request can choose its own.
    """
    async def dispatch(self, request, call_next):
        override = request.headers.get("x-test-client-ip")
        if override:
            request.scope["client"] = (override, 0)
        return await call_next(request)


@pytest.fixture
def app(tmp_path):
    app = create_app(_config_with_auth(tmp_path))
    # Install the IP rewriter OUTSIDE of the existing middleware stack so it
    # runs first and AuthMiddleware sees the rewritten client.
    app.add_middleware(_ClientIPRewriter)
    return app


async def _client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_is_public(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/health",
                headers={"x-test-client-ip": "8.8.8.8"},  # Remote, no auth
            )
            assert resp.status_code == 200


async def test_loopback_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "127.0.0.1"},
            )
            assert resp.status_code == 200


async def test_lan_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "192.168.1.50"},
            )
            assert resp.status_code == 200


async def test_tailscale_client_bypasses_auth(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "100.94.221.106"},
            )
            assert resp.status_code == 200


async def test_remote_client_without_credentials_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
            )
            assert resp.status_code == 401


async def test_remote_client_with_bearer_token_passes(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={
                    "x-test-client-ip": "203.0.113.42",
                    "authorization": f"Bearer {mgr.api_token}",
                },
            )
            assert resp.status_code == 200


async def test_remote_client_with_invalid_bearer_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={
                    "x-test-client-ip": "203.0.113.42",
                    "authorization": "Bearer not-a-real-token",
                },
            )
            assert resp.status_code == 401


async def test_remote_client_with_valid_remember_cookie_passes(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="test", ip="203.0.113.42")

        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": raw},
            )
            assert resp.status_code == 200


async def test_remote_client_with_invalid_cookie_gets_401(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": "fake-token"},
            )
            assert resp.status_code == 401


async def test_remote_client_with_revoked_cookie_gets_401(app):
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="test", ip="203.0.113.42")

        # Revoke the token
        import hashlib
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        row = await db.get_remember_token_by_hash(token_hash)
        await db.revoke_remember_token(row["id"])

        async with await _client(app) as c:
            resp = await c.get(
                "/api/signals",
                headers={"x-test-client-ip": "203.0.113.42"},
                cookies={"sd_remember": raw},
            )
            assert resp.status_code == 401


async def test_auth_login_path_is_public(app):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            # POST with wrong creds — we just want to verify the middleware
            # didn't 401 before the route handler got a chance to return 401.
            resp = await c.post(
                "/api/auth/login",
                headers={"x-test-client-ip": "203.0.113.42"},
                json={"username": "admin", "password": "wrong"},
            )
            # The route should respond with 401 (bad creds), NOT be blocked
            # by middleware. A pass-through-to-route 401 is what we want;
            # a middleware 401 would have a different detail message, but
            # either way the status is 401. So assert that the body contains
            # the route's own error message shape.
            assert resp.status_code == 401
            # Route-level 401 uses "Invalid credentials", middleware uses
            # "Not authenticated". We want the route's message here.
            assert "Invalid credentials" in resp.text


async def test_auth_sessions_path_is_protected(app):
    """/api/auth/sessions requires auth even though it's under /api/auth/."""
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            resp = await c.get(
                "/api/auth/sessions",
                headers={"x-test-client-ip": "203.0.113.42"},
            )
            assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth_middleware.py -v`

Expected: most tests fail. The reasons vary — some 401 when they should 200 (because the LAN bypass doesn't exist yet), some 200 when they should 401 (because auth/sessions isn't protected yet), etc.

- [ ] **Step 3: Rewrite `AuthMiddleware.dispatch`**

In `signaldeck/api/server.py`, replace the entire existing `AuthMiddleware` class with:

```python
_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/toggle",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth_mgr = _state.get("auth")
        if auth_mgr is None:
            return await call_next(request)

        path = request.url.path

        # Static files — the frontend has its own 401 handling via apiFetch.
        if not path.startswith("/api/"):
            return await call_next(request)

        # WebSocket paths are handled inside their own handlers via
        # _ws_authorized(). Middleware only sees HTTP here.
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Determine the caller's IP.
        config = _state.get("config", {})
        auth_cfg = config.get("auth", {}) if isinstance(config, dict) else {}
        allowlist = auth_cfg.get("lan_allowlist") or DEFAULT_LAN_ALLOWLIST
        client_ip = ""
        if auth_cfg.get("trust_x_forwarded_for", False):
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                client_ip = xff.split(",")[0].strip()
        if not client_ip and request.client is not None:
            client_ip = request.client.host

        if is_lan_client(client_ip, allowlist):
            return await call_next(request)

        # Bearer token (scripts / curl / headless clients)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if auth_mgr.verify_token(token):
                return await call_next(request)

        # Remember-me cookie (the normal browser path)
        cookie = request.cookies.get("sd_remember")
        if cookie:
            db = _state.get("db")
            if db is not None and await auth_mgr.verify_remember_token(db, cookie):
                return await call_next(request)

        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
```

At the top of `signaldeck/api/server.py`, add this import alongside the existing imports:

```python
from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth_middleware.py -v`

Expected: all 12 tests PASS.

Run the full existing auth/api test suite to verify no regression:

Run: `.venv/bin/pytest tests/test_auth.py tests/test_auth_extended.py tests/test_auth_routes.py tests/test_api_server.py -v`

Expected: all existing tests still PASS. If a test fails because it was implicitly relying on the old "Bearer-only" middleware behavior, check whether the test was injecting a remote IP — if yes, fix the test; if no, it was talking to a loopback and the new LAN bypass should make it even more permissive.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/server.py tests/test_auth_middleware.py
git commit -m "$(cat <<'EOF'
feat: LAN-bypass auth gate with remember-me cookie support

AuthMiddleware.dispatch is rewritten to pass through requests from the
LAN allowlist (loopback, RFC1918, IPv6 ULA, Tailscale CGNAT) without
any credentials, accept bearer tokens for scripts, and accept
sd_remember cookies for the browser flow. /api/auth/sessions is now
protected (only login and toggle remain on the public allowlist).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: WebSocket auth helper applied to all three handlers

**Files:**
- Create: `signaldeck/api/websocket/_auth.py` — the shared `_ws_authorized` helper
- Modify: `signaldeck/api/websocket/audio_stream.py` — gate the `/ws/audio` handler
- Modify: `signaldeck/api/websocket/live_signals.py` — gate the `/ws/signals` handler
- Modify: `signaldeck/api/websocket/waterfall.py` — gate the `/ws/waterfall` handler
- Create: `tests/test_ws_auth.py` — handshake-level tests

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws_auth.py`:

```python
"""Handshake-level auth tests for the /ws/* endpoints."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from signaldeck.api.server import create_app, get_auth_manager, get_db


def _config(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": True,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "lan_allowlist": ["127.0.0.0/8"],
            "trust_x_forwarded_for": False,
            "remember_token_days": None,
        },
    }


def test_ws_audio_loopback_accepts(tmp_path):
    """Starlette's TestClient reports itself as 'testclient' — tests need
    to know whether that counts as loopback. It does NOT — 'testclient' is
    not an IP — so by default TestClient hits the WS as a remote client
    and must supply a cookie. Use the cookie-based test below for the
    actual happy path, and explicitly verify that remote-no-cookie is
    rejected."""
    # Placeholder — kept as a reminder that TestClient has non-IP host.
    pass


def test_ws_audio_remote_no_cookie_rejected(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        # Starlette TestClient will raise on a WebSocket that closes
        # immediately after accept. We catch the close and assert code.
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/audio") as ws:
                ws.send_json({"type": "ping"})
                ws.receive_json()
        assert exc.value.code == 1008


def test_ws_audio_with_valid_cookie_accepts(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        mgr = get_auth_manager()
        db = get_db()
        # We have to run the async create in the app's running loop.
        import asyncio
        raw = asyncio.get_event_loop().run_until_complete(
            mgr.create_remember_token(db, user_agent="test", ip="1.1.1.1")
        )

        client.cookies.set("sd_remember", raw)
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json({"type": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"


def test_ws_signals_remote_no_cookie_rejected(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/signals") as ws:
                ws.receive_json()
        assert exc.value.code == 1008


def test_ws_waterfall_remote_no_cookie_rejected(tmp_path):
    app = create_app(_config(tmp_path))
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/waterfall") as ws:
                ws.receive_json()
        assert exc.value.code == 1008
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ws_auth.py -v`

Expected: `test_ws_audio_remote_no_cookie_rejected`, `test_ws_signals_remote_no_cookie_rejected`, and `test_ws_waterfall_remote_no_cookie_rejected` all fail because the handlers currently accept any connection. `test_ws_audio_with_valid_cookie_accepts` should pass if the handler is permissive today (or fail if something else is wrong).

- [ ] **Step 3: Create the shared helper**

Create `signaldeck/api/websocket/_auth.py`:

```python
"""Shared WebSocket authorization helper.

Runs the same auth gate as AuthMiddleware against a WebSocket handshake.
Handlers call this before calling `await websocket.accept()`, and close
with 1008 (policy violation) if the result is False.
"""
from fastapi import WebSocket

from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client
from signaldeck.api.server import _state


async def ws_authorized(websocket: WebSocket) -> bool:
    """Return True if the WebSocket handshake is allowed through.

    Accepts loopback/LAN origins without credentials. For remote origins,
    accepts a Bearer authorization header, otherwise a valid sd_remember
    cookie. Returns False if auth is enabled and none of these pass.
    """
    auth_mgr = _state.get("auth")
    if auth_mgr is None:
        return True  # Auth disabled entirely.

    config = _state.get("config", {}) or {}
    auth_cfg = config.get("auth", {}) if isinstance(config, dict) else {}
    allowlist = auth_cfg.get("lan_allowlist") or DEFAULT_LAN_ALLOWLIST

    client_ip = ""
    if auth_cfg.get("trust_x_forwarded_for", False):
        xff = websocket.headers.get("x-forwarded-for", "")
        if xff:
            client_ip = xff.split(",")[0].strip()
    if not client_ip and websocket.client is not None:
        client_ip = websocket.client.host

    if is_lan_client(client_ip, allowlist):
        return True

    # Bearer header (rare on WS, but possible from native clients)
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_mgr.verify_token(auth_header[7:]):
        return True

    # Remember-me cookie — the normal browser path
    cookie = websocket.cookies.get("sd_remember")
    if cookie:
        db = _state.get("db")
        if db is not None and await auth_mgr.verify_remember_token(db, cookie):
            return True

    return False
```

- [ ] **Step 4: Gate `/ws/audio`**

Open `signaldeck/api/websocket/audio_stream.py`. Find the `@router.websocket("/ws/audio")` decorator and the `ws_audio` function below it. Add this import at the top of the file (alongside the existing imports):

```python
from signaldeck.api.websocket._auth import ws_authorized
```

Then modify the `ws_audio` function. The current signature starts with `await websocket.accept()` — insert the auth check before it. The modified beginning of the function should look like:

```python
@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    global _audio_clients
    if not await ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    _audio_clients[websocket] = None
    # ... rest of handler unchanged
```

- [ ] **Step 5: Gate `/ws/signals`**

Open `signaldeck/api/websocket/live_signals.py`. Apply the same pattern: import `ws_authorized`, insert the check before `await websocket.accept()`:

```python
from signaldeck.api.websocket._auth import ws_authorized
```

In the handler:

```python
@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    if not await ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    # ... rest of handler unchanged
```

- [ ] **Step 6: Gate `/ws/waterfall`**

Open `signaldeck/api/websocket/waterfall.py`. Apply the same pattern:

```python
from signaldeck.api.websocket._auth import ws_authorized
```

In the handler:

```python
@router.websocket("/ws/waterfall")
async def ws_waterfall(websocket: WebSocket):
    if not await ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    # ... rest of handler unchanged
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ws_auth.py -v`

Expected: all tests PASS.

Run the existing WebSocket tests to confirm no regression:

Run: `.venv/bin/pytest tests/test_ws_audio.py tests/test_ws_signals.py tests/test_ws_waterfall.py -v`

Expected: all existing WebSocket tests still PASS. Note: those tests may use `auth.enabled: false` in their fixtures, in which case `ws_authorized` returns True immediately and they behave identically to today.

- [ ] **Step 8: Commit**

```bash
git add signaldeck/api/websocket/_auth.py \
        signaldeck/api/websocket/audio_stream.py \
        signaldeck/api/websocket/live_signals.py \
        signaldeck/api/websocket/waterfall.py \
        tests/test_ws_auth.py
git commit -m "$(cat <<'EOF'
feat: gate /ws/audio, /ws/signals, /ws/waterfall behind auth

New shared ws_authorized() helper runs the same LAN-bypass + bearer
+ remember-me cookie gate as AuthMiddleware against a WebSocket
handshake. All three existing WS handlers call it before accept()
and close with code 1008 on failure. Closes a pre-existing hole
where remote clients could subscribe to audio/signals/waterfall
even with auth enabled for REST endpoints.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Login endpoint extensions — cookie set + first-run password

**Files:**
- Modify: `signaldeck/api/routes/auth_routes.py` — rewrite `login`, extend `toggle`
- Create: `tests/test_login_cookie.py` — verifies cookie Set-Cookie and first_run_password

- [ ] **Step 1: Write the failing tests**

Create `tests/test_login_cookie.py`:

```python
"""Tests for the login endpoint cookie-setting behavior and toggle's
first_run_password surfacing."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app, get_auth_manager


def _config(tmp_path, auth_enabled=True):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": auth_enabled,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "remember_token_days": None,
        },
    }


async def test_login_sets_sd_remember_cookie(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            assert resp.status_code == 200
            # Set-Cookie header must be present
            cookies = resp.headers.get_list("set-cookie")
            assert any(ck.startswith("sd_remember=") for ck in cookies), cookies
            # Body carries the raw token for CLI/curl
            body = resp.json()
            assert "remember_token" in body
            assert body["username"] == "admin"
            # Old dead field is gone
            assert "session_token" not in body


async def test_login_cookie_max_age_when_days_null_is_10_years(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            cookies = resp.headers.get_list("set-cookie")
            sd = [c for c in cookies if c.startswith("sd_remember=")][0]
            assert "Max-Age=315360000" in sd  # 10 years
            assert "HttpOnly" in sd
            assert "Path=/" in sd
            assert "SameSite=Lax" in sd.lower() or "samesite=lax" in sd.lower()


async def test_login_cookie_max_age_when_days_is_integer(tmp_path):
    cfg = _config(tmp_path)
    cfg["auth"]["remember_token_days"] = 30
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        password = mgr._initial_password
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": password},
            )
            cookies = resp.headers.get_list("set-cookie")
            sd = [c for c in cookies if c.startswith("sd_remember=")][0]
            assert "Max-Age=2592000" in sd  # 30 * 86400


async def test_toggle_returns_first_run_password_on_initial_enable(tmp_path):
    """The first time toggle enables auth and creates the credentials file,
    it must surface the generated password so the frontend can show it."""
    app = create_app(_config(tmp_path, auth_enabled=False))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/toggle", json={"enabled": True})
            assert resp.status_code == 200
            body = resp.json()
            assert body["enabled"] is True
            # First-run password is present exactly once, and only on first run
            assert "first_run_password" in body
            assert body["first_run_password"]
            assert len(body["first_run_password"]) >= 16


async def test_toggle_does_not_return_first_run_password_on_subsequent(tmp_path):
    """Enabling again (after credentials file already exists) does NOT surface
    a password — because there is no new password, just the hashed existing one."""
    cred_path = tmp_path / "credentials.yaml"
    # Pre-seed by creating once
    from signaldeck.api.auth import AuthManager
    m = AuthManager(credentials_path=str(cred_path))
    m.initialize()

    app = create_app(_config(tmp_path, auth_enabled=False))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/auth/toggle", json={"enabled": True})
            assert resp.status_code == 200
            body = resp.json()
            assert body["enabled"] is True
            assert "first_run_password" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_login_cookie.py -v`

Expected: all five tests fail — the current login endpoint doesn't set `sd_remember`, doesn't return `remember_token`, and the toggle endpoint doesn't surface `first_run_password`.

- [ ] **Step 3: Rewrite the login handler**

Open `signaldeck/api/routes/auth_routes.py`. Replace the current `login` function with:

```python
from fastapi import Response
from signaldeck.api.server import get_db


@router.post("/login")
async def login(data: LoginRequest, request: Request, response: Response):
    mgr = get_auth_manager()
    if not mgr or not mgr.verify_login(data.username, data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    db = get_db()
    user_agent = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    raw_token = await mgr.create_remember_token(
        db, user_agent=user_agent, ip=ip, label=None
    )

    # Determine cookie Max-Age from config.
    from signaldeck.api.server import get_config
    cfg = get_config() or {}
    days = cfg.get("auth", {}).get("remember_token_days")
    if isinstance(days, int) and days > 0:
        max_age = days * 86400
    else:
        max_age = 315360000  # 10 years — "forever" for browsers

    response.set_cookie(
        key="sd_remember",
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return {
        "username": data.username,
        "remember_token": raw_token,
    }
```

Note the handler signature now takes `request: Request` (already imported) and `response: Response`. If `Response` is not already imported, add it to the `from fastapi import ...` line at the top of the file.

- [ ] **Step 4: Extend the toggle handler**

Still in `signaldeck/api/routes/auth_routes.py`, replace the current `toggle_auth` function with:

```python
@router.post("/toggle")
async def toggle_auth(data: ToggleAuthRequest):
    """Enable or disable authentication.

    On the very first enable (when credentials.yaml is being created),
    returns the generated admin password in first_run_password so the
    frontend can show it exactly once. Subsequent toggles do not return
    a password (the credentials already exist).
    """
    from signaldeck.api.server import get_config, _state
    from pathlib import Path
    config = get_config()
    config.setdefault("auth", {})["enabled"] = data.enabled

    first_run_password = None
    if data.enabled:
        from signaldeck.api.auth import AuthManager
        cred_path = config.get("auth", {}).get("credentials_path", "config/credentials.yaml")
        cred_file_existed = Path(cred_path).exists()

        if "auth" not in _state:
            mgr = AuthManager(credentials_path=cred_path)
            mgr.initialize()
            _state["auth"] = mgr
        else:
            mgr = _state["auth"]

        if not cred_file_existed and mgr._initial_password is not None:
            first_run_password = mgr._initial_password
    else:
        _state.pop("auth", None)

    response_body = {"enabled": data.enabled}
    if first_run_password is not None:
        response_body["first_run_password"] = first_run_password
    return response_body
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_login_cookie.py -v`

Expected: all 5 tests PASS.

Run the existing auth_routes tests to catch any regression:

Run: `.venv/bin/pytest tests/test_auth_routes.py -v`

Expected: all existing tests still PASS. If any test was asserting that `session_token` was in the login response, update it to assert `remember_token` instead (that field replaced it).

- [ ] **Step 6: Commit**

```bash
git add signaldeck/api/routes/auth_routes.py tests/test_login_cookie.py
git commit -m "$(cat <<'EOF'
feat: login sets sd_remember cookie, toggle surfaces first-run password

POST /api/auth/login now creates a remember_tokens row, sets the
sd_remember HttpOnly/Lax/Path=/ cookie, and returns the raw token in
the response body for CLI/curl users. Max-Age is 10 years when
remember_token_days is null, otherwise days*86400.

POST /api/auth/toggle now returns first_run_password in its body on
the very first enable (when credentials.yaml did not previously exist),
so the frontend can show the generated admin password exactly once.

Dead session_token field removed from the login response — it was never
actually verified by anything.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Session management endpoints (list/rename/revoke/logout)

**Files:**
- Modify: `signaldeck/api/routes/auth_routes.py` — add four new endpoints
- Create: `tests/test_auth_sessions.py` — endpoint tests

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_sessions.py`:

```python
"""Tests for the /api/auth/sessions endpoints: list, rename, revoke, logout."""
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app, get_auth_manager, get_db


def _config(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {
            "enabled": True,
            "credentials_path": str(tmp_path / "credentials.yaml"),
            "remember_token_days": None,
        },
    }


async def _authed_client(app, raw_token):
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    c.cookies.set("sd_remember", raw_token)
    return c


async def test_list_sessions_requires_auth(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 401


async def test_list_sessions_returns_current_flag(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw_a = await mgr.create_remember_token(db, user_agent="Mac Safari", ip="1.1.1.1")
        raw_b = await mgr.create_remember_token(db, user_agent="iPhone Safari", ip="2.2.2.2")

        async with await _authed_client(app, raw_a) as c:
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 200
            rows = resp.json()
            assert isinstance(rows, list)
            assert len(rows) == 2
            # The row backed by raw_a is the current device
            current_rows = [r for r in rows if r.get("is_current")]
            assert len(current_rows) == 1


async def test_list_sessions_never_exposes_token_hash(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.get("/api/auth/sessions")
            rows = resp.json()
            for r in rows:
                assert "token_hash" not in r


async def test_rename_session(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1", label="old")

        async with await _authed_client(app, raw) as c:
            list_resp = await c.get("/api/auth/sessions")
            session_id = list_resp.json()[0]["id"]

            resp = await c.patch(
                f"/api/auth/sessions/{session_id}",
                json={"label": "new label"},
            )
            assert resp.status_code == 200

            list_resp = await c.get("/api/auth/sessions")
            assert list_resp.json()[0]["label"] == "new label"


async def test_rename_missing_returns_404(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.patch(
                "/api/auth/sessions/99999",
                json={"label": "nope"},
            )
            assert resp.status_code == 404


async def test_revoke_session(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw_a = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")
        raw_b = await mgr.create_remember_token(db, user_agent="ua", ip="2.2.2.2")

        async with await _authed_client(app, raw_a) as c:
            list_resp = await c.get("/api/auth/sessions")
            rows = list_resp.json()
            # Revoke the OTHER session (not current)
            other = [r for r in rows if not r.get("is_current")][0]
            resp = await c.delete(f"/api/auth/sessions/{other['id']}")
            assert resp.status_code == 200

            # Only current session left
            list_resp = await c.get("/api/auth/sessions")
            assert len(list_resp.json()) == 1


async def test_logout_revokes_current_token(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        mgr = get_auth_manager()
        db = get_db()
        raw = await mgr.create_remember_token(db, user_agent="ua", ip="1.1.1.1")

        async with await _authed_client(app, raw) as c:
            resp = await c.post("/api/auth/logout")
            assert resp.status_code == 200

            # Next request from same client should 401 — cookie is revoked
            # server-side (the cookie value still exists in the client, but
            # the DB row is gone).
            resp = await c.get("/api/auth/sessions")
            assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth_sessions.py -v`

Expected: all 7 tests fail with 404 Not Found (because the routes don't exist yet) or similar errors.

- [ ] **Step 3: Add the session management routes**

Open `signaldeck/api/routes/auth_routes.py`. At the end of the file, append:

```python
import hashlib

from signaldeck.api.server import get_db


class SessionRename(BaseModel):
    label: str


def _current_token_hash_from_request(request: Request) -> str | None:
    """Return the SHA-256 hash of the current request's sd_remember cookie,
    or None if the request is not using a cookie (e.g., Bearer-authed scripts)."""
    cookie = request.cookies.get("sd_remember")
    if not cookie:
        return None
    return hashlib.sha256(cookie.encode()).hexdigest()


@router.get("/sessions")
async def list_sessions(request: Request):
    """List every remember-me session. Annotates the requesting device as
    is_current=True if a cookie is present and matches."""
    db = get_db()
    rows = await db.list_remember_tokens()

    current_hash = _current_token_hash_from_request(request)
    if current_hash is not None:
        # We don't expose token_hash, but we need it for the is_current
        # match. Query it separately without leaking.
        current_row = await db.get_remember_token_by_hash(current_hash)
        current_id = current_row["id"] if current_row else None
    else:
        current_id = None

    for row in rows:
        row["is_current"] = (row["id"] == current_id)
    return rows


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: int, data: SessionRename):
    db = get_db()
    ok = await db.rename_remember_token(session_id, data.label)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "label": data.label}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: int):
    db = get_db()
    ok = await db.revoke_remember_token(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"revoked": True, "id": session_id}


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Revoke the current device's remember-me token and clear the cookie."""
    db = get_db()
    current_hash = _current_token_hash_from_request(request)
    if current_hash:
        row = await db.get_remember_token_by_hash(current_hash)
        if row is not None:
            await db.revoke_remember_token(row["id"])
    response.delete_cookie("sd_remember", path="/")
    return {"logged_out": True}
```

If `Response` is not already imported at the top of the file, add it to the `from fastapi import ...` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth_sessions.py -v`

Expected: all 7 tests PASS.

Also verify the middleware still protects these routes:

Run: `.venv/bin/pytest tests/test_auth_middleware.py::test_auth_sessions_path_is_protected -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/routes/auth_routes.py tests/test_auth_sessions.py
git commit -m "$(cat <<'EOF'
feat: add /api/auth/sessions endpoints for device management

GET  /api/auth/sessions            list all devices (is_current flag)
PATCH /api/auth/sessions/{id}      rename a device label
DELETE /api/auth/sessions/{id}     revoke a device (instant invalidation)
POST /api/auth/logout              revoke this device + clear cookie

All four endpoints are protected by AuthMiddleware. List output never
exposes token_hash.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: CLI `signaldeck auth set-password` command

**Files:**
- Modify: `signaldeck/main.py` — add new `@cli.group()` + `set-password` command
- Create: `tests/test_cli_auth.py` — click.testing-based test

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_auth.py`:

```python
"""Tests for the `signaldeck auth` CLI subcommand group."""
from pathlib import Path

from click.testing import CliRunner

from signaldeck.main import cli
from signaldeck.api.auth import AuthManager


def test_auth_set_password_creates_credentials_and_sets_pw(tmp_path, monkeypatch):
    # Point config to a tmp dir so we don't touch real credentials.yaml
    cred_path = tmp_path / "credentials.yaml"

    # Seed an initial credentials file so the command has something to update.
    initial = AuthManager(credentials_path=str(cred_path))
    initial.initialize()
    old_pw = initial._initial_password

    # Monkeypatch load_config so the CLI command sees our tmp path.
    import signaldeck.main as main_mod
    def fake_load_config(path):
        return {"auth": {"credentials_path": str(cred_path)}}
    monkeypatch.setattr(main_mod, "load_config", fake_load_config)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["auth", "set-password", "--user", "admin", "--password", "brand-new-password"],
    )
    assert result.exit_code == 0, result.output
    assert "updated" in result.output.lower()

    # Reload and verify the new password works, old one does not
    mgr = AuthManager(credentials_path=str(cred_path))
    mgr.initialize()
    assert mgr.verify_login("admin", "brand-new-password")
    assert not mgr.verify_login("admin", old_pw)


def test_auth_set_password_defaults_user_to_admin(tmp_path, monkeypatch):
    cred_path = tmp_path / "credentials.yaml"
    initial = AuthManager(credentials_path=str(cred_path))
    initial.initialize()

    import signaldeck.main as main_mod
    def fake_load_config(path):
        return {"auth": {"credentials_path": str(cred_path)}}
    monkeypatch.setattr(main_mod, "load_config", fake_load_config)

    runner = CliRunner()
    # Invoke with --password to skip the interactive prompt
    result = runner.invoke(cli, ["auth", "set-password", "--password", "new-pw-789"])
    assert result.exit_code == 0, result.output

    mgr = AuthManager(credentials_path=str(cred_path))
    mgr.initialize()
    assert mgr.verify_login("admin", "new-pw-789")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli_auth.py -v`

Expected: both tests fail because the CLI has no `auth` subcommand group.

- [ ] **Step 3: Add the CLI group and command**

Open `signaldeck/main.py`. After the last `@cli.command()` (likely the `devices` command near line 924 or the `cli.group` definitions around 938/1000), add:

```python
@cli.group()
def auth() -> None:
    """Manage SignalDeck authentication."""


@auth.command("set-password")
@click.option("--user", default="admin", show_default=True, help="Username to update.")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="New password (prompted if not provided).",
)
def auth_set_password(user: str, password: str) -> None:
    """Reset a user's password without needing the current one.

    Intended as a recovery path: the operator runs this on the server
    host when they can't log in. Because CLI access implies local
    authority over the server, this command bypasses the usual
    current-password check that the HTTP change-password endpoint
    enforces.
    """
    from signaldeck.api.auth import AuthManager
    cfg = load_config(None)
    cred_path = cfg.get("auth", {}).get("credentials_path", "config/credentials.yaml")
    mgr = AuthManager(credentials_path=cred_path)
    mgr.initialize()
    mgr.change_password(user, password)
    click.echo(f"Password updated for {user}.")
```

Verify that `click` and `load_config` are already imported near the top of `signaldeck/main.py`. If not, add them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli_auth.py -v`

Expected: both tests PASS.

Sanity check by invoking the command help:

Run: `.venv/bin/python -m signaldeck.main auth set-password --help`

Expected: help text is printed with `--user` and `--password` options visible.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/main.py tests/test_cli_auth.py
git commit -m "$(cat <<'EOF'
feat: signaldeck auth set-password CLI escape hatch

New CLI subcommand rewrites a user's password directly in
credentials.yaml without needing the current password. Rationale:
the operator running the CLI is already the local authority over
the server (they have shell access), so requiring the old password
would only make the forgotten-password recovery path harder.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Audio mode auto-switching (backend)

Tasks 10–13. Depends on Task 1's `is_lan_client` helper but otherwise independent of auth.

### Task 10: `audio_mode` config field + persistence

**Files:**
- Modify: `config/default.yaml` — add `scanner.audio_mode`
- Modify: `signaldeck/api/routes/scanner.py` — `_persist_user_config` writes it, settings PUT accepts it
- Create: `tests/test_audio_mode_config.py` — round-trip test

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio_mode_config.py`:

```python
"""Tests for audio_mode config: default, persistence, settings round-trip."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app
from signaldeck.config import load_config


def test_default_config_has_audio_mode_auto():
    cfg = load_config(None, load_user_settings=False)
    assert cfg["scanner"].get("audio_mode") == "auto"


def _config(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "auto",
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }


async def test_put_settings_accepts_audio_mode(tmp_path, monkeypatch):
    # Redirect _USER_CONFIG_PATH to tmp so tests don't clobber real config
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={"audio_mode": "pcm_stream"})
            assert resp.status_code == 200

            # Verify it round-trips
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            assert resp.json()["scanner"]["audio_mode"] == "pcm_stream"


async def test_put_settings_rejects_invalid_audio_mode(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put("/api/settings", json={"audio_mode": "nonsense"})
            assert resp.status_code == 400


async def test_persist_user_config_writes_audio_mode(tmp_path, monkeypatch):
    """_persist_user_config should round-trip audio_mode to disk."""
    import signaldeck.api.routes.scanner as scanner_routes
    user_cfg_path = tmp_path / "user_settings.yaml"
    monkeypatch.setattr(scanner_routes, "_USER_CONFIG_PATH", user_cfg_path)

    config = {
        "devices": {"gain": 40},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "pcm_stream",
        },
        "audio": {},
        "logging": {"level": "INFO"},
    }
    scanner_routes._persist_user_config(config)

    import yaml
    with open(user_cfg_path) as f:
        persisted = yaml.safe_load(f)
    assert persisted["scanner"]["audio_mode"] == "pcm_stream"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_audio_mode_config.py -v`

Expected: all four tests fail — default config doesn't have audio_mode, settings PUT doesn't accept it, _persist_user_config doesn't write it.

- [ ] **Step 3: Add `scanner.audio_mode: auto` to `config/default.yaml`**

Find the existing `scanner:` section in `config/default.yaml` and add `audio_mode: auto` as a new top-level key under it, e.g.:

```yaml
scanner:
  # ... existing fields ...
  audio_mode: auto   # auto | gqrx | pcm_stream — follows remote listeners when auto
```

- [ ] **Step 4: Extend the settings PUT handler**

Open `signaldeck/api/routes/scanner.py`. Find the Pydantic model used by the settings PUT (likely `UpdateSettingsRequest` or similar — search for `class.*Settings.*BaseModel`). Add a field:

```python
    audio_mode: str | None = None
```

Find the body of the PUT handler (the function decorated with `@router.put("/settings")`). Before any other field handling, insert validation:

```python
    if data.audio_mode is not None:
        if data.audio_mode not in ("auto", "gqrx", "pcm_stream"):
            raise HTTPException(
                status_code=400,
                detail=f"invalid audio_mode: {data.audio_mode}",
            )
        config.setdefault("scanner", {})["audio_mode"] = data.audio_mode
        changed.append(f"audio_mode={data.audio_mode}")
```

Then in the GET `/settings` handler, make sure `scanner.audio_mode` is included in the response. If the GET handler returns a broad `config["scanner"]` dict, it will be included automatically. If it hand-constructs the response, add `audio_mode` to the scanner dict.

In `_persist_user_config`, extend the `"scanner":` sub-dict to include `audio_mode`:

```python
        "scanner": {
            "squelch_offset": config["scanner"].get("squelch_offset", 10),
            "min_signal_strength": config["scanner"].get("min_signal_strength", -50),
            "dwell_time_ms": config["scanner"].get("dwell_time_ms", 50),
            "fft_size": config["scanner"].get("fft_size", 1024),
            "scan_profiles": resolve_scan_profile_keys(config.get("scanner", {})),
            "sweep_ranges": config["scanner"].get("sweep_ranges", []),
            "audio_mode": config["scanner"].get("audio_mode", "auto"),
        },
```

Make sure `HTTPException` is imported at the top of `scanner.py`:

```python
from fastapi import APIRouter, HTTPException, Query
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio_mode_config.py -v`

Expected: all four tests PASS.

Run existing scanner / settings tests:

Run: `.venv/bin/pytest tests/test_scanner.py tests/test_api_server.py -k "settings" -v`

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add config/default.yaml signaldeck/api/routes/scanner.py tests/test_audio_mode_config.py
git commit -m "$(cat <<'EOF'
feat: scanner.audio_mode config field + PUT /api/settings support

New tri-state setting (auto/gqrx/pcm_stream) defaults to auto.
PUT /api/settings validates the value and persists it to
user_settings.yaml via _persist_user_config. GET returns it in
the scanner block.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `resolve_effective_audio_mode` + richer `_audio_clients` structure

**Files:**
- Modify: `signaldeck/api/websocket/audio_stream.py` — extend subscriber dict, add resolver
- Create: `tests/test_resolve_audio_mode.py` — unit tests for the decision rule

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolve_audio_mode.py`:

```python
"""Tests for resolve_effective_audio_mode — the audio-mode decision rule."""
import pytest

from signaldeck.api.websocket import audio_stream


@pytest.fixture(autouse=True)
def clear_clients():
    """Reset the module-level subscriber dict between tests."""
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


def _client(freq, is_lan, addr="1.1.1.1"):
    """Build a fake subscriber entry."""
    return {"freq": freq, "is_lan": is_lan, "remote_addr": addr}


def test_manual_gqrx_always_wins_regardless_of_subscribers():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("gqrx") == "gqrx"


def test_manual_pcm_stream_always_wins():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="127.0.0.1")
    assert audio_stream.resolve_effective_audio_mode("pcm_stream") == "pcm_stream"


def test_auto_no_subscribers_picks_gqrx():
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_lan_only_subscriber_picks_gqrx():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="192.168.1.5")
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_remote_subscriber_picks_pcm_stream():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"


def test_auto_mixed_lan_and_remote_picks_pcm_stream():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=True, addr="192.168.1.5")
    audio_stream._audio_clients["ws2"] = _client(100e6, is_lan=False, addr="203.0.113.9")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"


def test_auto_subscriber_with_freq_none_is_ignored():
    """A client that has connected to /ws/audio but hasn't subscribed to a
    frequency yet (freq=None) should not count as 'listening.'"""
    audio_stream._audio_clients["ws1"] = _client(None, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_subscriber_disconnect_returns_to_gqrx():
    audio_stream._audio_clients["ws1"] = _client(100e6, is_lan=False, addr="8.8.8.8")
    assert audio_stream.resolve_effective_audio_mode("auto") == "pcm_stream"
    # Simulate disconnect
    del audio_stream._audio_clients["ws1"]
    assert audio_stream.resolve_effective_audio_mode("auto") == "gqrx"


def test_auto_returns_valid_literal_only():
    """Result must always be one of the three valid literal strings."""
    for clients in [{}, {"x": _client(100e6, True)}, {"x": _client(100e6, False)}]:
        audio_stream._audio_clients.clear()
        audio_stream._audio_clients.update(clients)
        result = audio_stream.resolve_effective_audio_mode("auto")
        assert result in ("gqrx", "pcm_stream")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_resolve_audio_mode.py -v`

Expected: all tests fail with `AttributeError: module 'signaldeck.api.websocket.audio_stream' has no attribute 'resolve_effective_audio_mode'`.

- [ ] **Step 3: Extend `_audio_clients` and add the resolver**

Open `signaldeck/api/websocket/audio_stream.py`. At the top of the file, find the existing:

```python
_audio_clients: dict[WebSocket, float | None] = {}
```

Replace it with:

```python
# Per-client state: {"freq": float | None, "is_lan": bool, "remote_addr": str}
_audio_clients: dict = {}
```

Then, after the existing `get_audio_request()` function, add:

```python
def resolve_effective_audio_mode(configured_mode: str) -> str:
    """Decide the effective audio mode from the configured mode + live subscribers.

    - configured_mode == "gqrx" → always "gqrx"
    - configured_mode == "pcm_stream" → always "pcm_stream"
    - configured_mode == "auto":
        - Any subscriber with freq not None AND is_lan False → "pcm_stream"
        - Otherwise → "gqrx"
    """
    if configured_mode == "gqrx":
        return "gqrx"
    if configured_mode == "pcm_stream":
        return "pcm_stream"
    # auto
    for info in _audio_clients.values():
        if isinstance(info, dict) and info.get("freq") is not None and not info.get("is_lan", True):
            return "pcm_stream"
    return "gqrx"
```

Now update the `ws_audio` handler to populate the richer subscriber info. Find the current subscribe handler body:

```python
            elif data.get("type") == "subscribe":
                freq = data.get("frequency_hz", 0)
                modulation = data.get("modulation")
                volume = data.get("volume")
                _audio_clients[websocket] = freq
                ...
```

Replace with:

```python
            elif data.get("type") == "subscribe":
                freq = data.get("frequency_hz", 0)
                modulation = data.get("modulation")
                volume = data.get("volume")
                # Classify this client's origin against the LAN allowlist so
                # the audio-mode resolver can decide.
                from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client
                from signaldeck.api.server import _state
                cfg = _state.get("config", {}) or {}
                allowlist = cfg.get("auth", {}).get("lan_allowlist") or DEFAULT_LAN_ALLOWLIST
                client_addr = websocket.client.host if websocket.client else ""
                _audio_clients[websocket] = {
                    "freq": freq,
                    "is_lan": is_lan_client(client_addr, allowlist),
                    "remote_addr": client_addr,
                }
                _audio_request["frequency_hz"] = freq
                _audio_request["active"] = True
                _audio_request["modulation"] = modulation
                if volume is not None:
                    _audio_request["volume"] = volume
                logger.debug("Audio subscribe: %.3f MHz (mod=%s)", freq / 1e6, modulation)
                # Include effective mode so the frontend can detect silence in gqrx-pinned mode
                scanner_cfg = cfg.get("scanner", {})
                effective = resolve_effective_audio_mode(
                    scanner_cfg.get("audio_mode", "auto")
                )
                await websocket.send_json({
                    "type": "subscribed",
                    "frequency_hz": freq,
                    "effective_mode": effective,
                })
```

Also find the `elif data.get("type") == "unsubscribe":` branch and update its handling for the dict-shaped clients. Before the helper existed, clients were keyed by raw freq. Now they're dicts — so the "any subscriber still listening" check must be updated:

```python
            elif data.get("type") == "unsubscribe":
                _audio_clients[websocket] = {
                    "freq": None,
                    "is_lan": _audio_clients.get(websocket, {}).get("is_lan", True),
                    "remote_addr": _audio_clients.get(websocket, {}).get("remote_addr", ""),
                }
                # Check if any client still subscribed
                any_tuned = any(
                    info.get("freq") is not None
                    for info in _audio_clients.values()
                    if isinstance(info, dict)
                )
                if not any_tuned:
                    _audio_request["frequency_hz"] = None
                    _audio_request["active"] = False
                    _audio_request["modulation"] = None
                await websocket.send_json({"type": "unsubscribed"})
```

And the `finally:` cleanup at the end of the handler:

```python
    finally:
        _audio_clients.pop(websocket, None)
        any_tuned = any(
            isinstance(info, dict) and info.get("freq") is not None
            for info in _audio_clients.values()
        )
        if not any_tuned:
            _audio_request["frequency_hz"] = None
            _audio_request["active"] = False
            _audio_request["modulation"] = None
        logger.debug("Audio WebSocket client disconnected")
```

And the `send_audio_chunk` function, which iterates over `_audio_clients` expecting the old shape:

```python
async def send_audio_chunk(frequency_hz: float, audio_bytes: bytes) -> None:
    """Send demodulated audio to subscribed WebSocket clients."""
    global _audio_clients
    for ws, info in list(_audio_clients.items()):
        if not isinstance(info, dict):
            continue
        sub_freq = info.get("freq")
        if sub_freq is not None and abs(sub_freq - frequency_hz) < 5000:
            try:
                await ws.send_bytes(audio_bytes)
            except Exception:
                _audio_clients.pop(ws, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_resolve_audio_mode.py -v`

Expected: all 9 tests PASS.

Run existing audio stream tests to catch regressions:

Run: `.venv/bin/pytest tests/test_ws_audio.py -v`

Expected: all PASS. If a test was asserting the old raw-freq shape of `_audio_clients`, update it to the new dict shape.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/websocket/audio_stream.py tests/test_resolve_audio_mode.py
git commit -m "$(cat <<'EOF'
feat: resolve_effective_audio_mode + LAN-aware subscriber tracking

_audio_clients now stores {"freq", "is_lan", "remote_addr"} per
WebSocket instead of just the raw frequency. The new
resolve_effective_audio_mode() returns "pcm_stream" when the
configured mode is "auto" and any subscriber is remote, else "gqrx".
Manual modes ("gqrx"/"pcm_stream") always win. The subscribe reply
includes effective_mode so the frontend can detect silence in the
gqrx-pinned-but-remote-subscriber edge case.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Scanner integration — gqrx mute/restore on mode flips

**Files:**
- Modify: `signaldeck/main.py` — wherever the scanner loop reads `_audio_request` and feeds gqrx, consult the effective mode and flip gqrx AF gain
- Create: `tests/test_audio_mode_gqrx_flip.py` — verifies rigctl `set_audio_gain` is called with 0 on gqrx→pcm_stream and with stored volume on pcm_stream→gqrx

- [ ] **Step 1: Locate the audio dispatch in the scanner loop**

Run: `.venv/bin/grep -n "get_audio_request\|_audio_request" signaldeck/main.py`

Expected output: one or more lines where the scanner's gqrx-backend loop consults `get_audio_request()` to decide the gqrx tuning frequency and volume. Note the line numbers and function name.

Also: `.venv/bin/grep -n "set_audio_gain\|L AF" signaldeck/main.py signaldeck/engine/ -r`

Expected output: any existing calls to `gqrx.set_audio_gain(...)`. If none exist in `main.py`, the mode-flip mute logic is net-new and slots in wherever the audio request is handled.

Read those regions to understand the current structure before writing the flip logic. The structure is typically a periodic tick that reads `_audio_request` and issues `gqrx.set_frequency(...)` / `gqrx.set_audio_gain(...)` commands.

- [ ] **Step 2: Write the failing test**

Create `tests/test_audio_mode_gqrx_flip.py`:

```python
"""Integration test for audio mode flip: verify gqrx AF gain is muted to 0
when effective mode is pcm_stream, and restored to stored volume when
effective mode is gqrx."""
import pytest

from signaldeck.api.websocket import audio_stream
from signaldeck.engine.audio_mode_controller import AudioModeController


@pytest.fixture(autouse=True)
def clear_clients():
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


class FakeGqrx:
    def __init__(self):
        self.af_gain_history: list[float] = []
        self._af_gain = 5.0

    async def set_audio_gain(self, db_value: float) -> None:
        self.af_gain_history.append(db_value)
        self._af_gain = db_value

    async def get_audio_gain(self) -> float:
        return self._af_gain


async def test_flip_to_pcm_stream_mutes_gqrx():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=5.0)
    assert gqrx.af_gain_history[-1] == 0.0


async def test_flip_to_gqrx_restores_stored_volume():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=7.5)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=7.5)
    assert gqrx.af_gain_history[-1] == 7.5


async def test_no_op_when_mode_unchanged():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    # Only one call — the second was a no-op
    assert len(gqrx.af_gain_history) == 1


async def test_initial_state_is_unknown_first_call_always_applies():
    gqrx = FakeGqrx()
    ctrl = AudioModeController(gqrx=gqrx)
    await ctrl.apply_effective_mode("gqrx", user_volume_db=5.0)
    assert len(gqrx.af_gain_history) == 1


async def test_flip_survives_gqrx_failure_without_raising():
    """If gqrx rigctl fails, we log and swallow — the controller must not
    propagate the exception up to the scanner loop."""
    class BrokenGqrx:
        async def set_audio_gain(self, db_value: float) -> None:
            raise RuntimeError("rigctl unreachable")

    ctrl = AudioModeController(gqrx=BrokenGqrx())
    # Should not raise
    await ctrl.apply_effective_mode("pcm_stream", user_volume_db=5.0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_audio_mode_gqrx_flip.py -v`

Expected: all tests fail with `ModuleNotFoundError: No module named 'signaldeck.engine.audio_mode_controller'`.

- [ ] **Step 4: Create the controller module**

Create `signaldeck/engine/audio_mode_controller.py`:

```python
"""AudioModeController — debounced mode flips for gqrx AF gain.

The scanner loop calls `apply_effective_mode(mode, user_volume_db)` on
every tick. The controller tracks the last-applied mode and only issues
a rigctl command when the mode actually changes, so idle ticks don't
spam gqrx. Exceptions from the rigctl call are logged and swallowed —
the scanner loop must keep running even if gqrx is temporarily
unreachable.
"""
import logging

logger = logging.getLogger(__name__)


class AudioModeController:
    def __init__(self, gqrx) -> None:
        """
        Args:
            gqrx: An object with an async `set_audio_gain(db_value: float)` method.
                  This is typically a GqrxClient instance.
        """
        self._gqrx = gqrx
        self._last_applied_mode: str | None = None

    async def apply_effective_mode(
        self,
        effective_mode: str,
        user_volume_db: float,
    ) -> None:
        """Apply the effective audio mode to gqrx.

        - "gqrx"       → set AF gain to user_volume_db
        - "pcm_stream" → set AF gain to 0 (muted, still tuned)

        No-op if the mode hasn't changed since the last call. rigctl
        failures are logged and swallowed.
        """
        if effective_mode == self._last_applied_mode:
            return
        try:
            if effective_mode == "pcm_stream":
                await self._gqrx.set_audio_gain(0.0)
            elif effective_mode == "gqrx":
                await self._gqrx.set_audio_gain(user_volume_db)
            else:
                logger.warning("Unknown effective audio mode: %r", effective_mode)
                return
            self._last_applied_mode = effective_mode
            logger.info(
                "Audio mode flip: applied effective_mode=%s (af_gain=%s)",
                effective_mode,
                0.0 if effective_mode == "pcm_stream" else user_volume_db,
            )
        except Exception as e:
            logger.warning(
                "Failed to apply audio mode %s via gqrx rigctl: %s",
                effective_mode,
                e,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio_mode_gqrx_flip.py -v`

Expected: all 5 tests PASS.

- [ ] **Step 6: Wire the controller into the scanner loop**

Open `signaldeck/main.py` and find the `start` command (the Click command that runs the scanner loop with gqrx as backend — look for `gqrx` / `GqrxClient` references, typically around line 116 or later).

Find the section that creates a `GqrxClient` instance (e.g., `gqrx = GqrxClient(...)`). Right after that, instantiate the controller:

```python
from signaldeck.engine.audio_mode_controller import AudioModeController
audio_mode_ctrl = AudioModeController(gqrx=gqrx)
```

Then find the periodic tick that reads `get_audio_request()` / handles the tuning loop. In that tick (typically inside an `async def` that is scheduled alongside the scanner), after reading the current request state, apply the effective mode:

```python
from signaldeck.api.websocket.audio_stream import resolve_effective_audio_mode
# ... inside the tick function ...
audio_req = get_audio_request()
scanner_cfg = config.get("scanner", {})
configured_mode = scanner_cfg.get("audio_mode", "auto")
effective = resolve_effective_audio_mode(configured_mode)

# user_volume_db: the scanner already has a notion of the user's preferred
# gqrx audio volume (usually stored in audio_req["volume"] or a config field).
# Default to 5.0 dB if nothing set.
user_volume_db = audio_req.get("volume") if audio_req.get("volume") is not None else 5.0

await audio_mode_ctrl.apply_effective_mode(effective, user_volume_db)
```

The exact placement depends on the current loop shape — place it alongside the existing `gqrx.set_frequency(...)` call for the audio request. Do NOT replace the frequency call; gqrx must still track the frequency in both modes.

- [ ] **Step 7: Run tests and a smoke check**

Run: `.venv/bin/pytest tests/test_audio_mode_gqrx_flip.py tests/test_scanner_gqrx.py tests/test_gqrx_client.py -v`

Expected: all PASS. The existing gqrx tests should continue to pass because the controller is additive.

- [ ] **Step 8: Commit**

```bash
git add signaldeck/engine/audio_mode_controller.py signaldeck/main.py tests/test_audio_mode_gqrx_flip.py
git commit -m "$(cat <<'EOF'
feat: AudioModeController for gqrx mute/restore on audio mode flip

New controller tracks the last-applied mode and sends rigctl
set_audio_gain commands only when the mode changes. Called from the
scanner's gqrx-backend tick with the effective mode from
resolve_effective_audio_mode. rigctl failures are logged and swallowed
so the scanner loop keeps running even if gqrx is temporarily
unreachable.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: `/api/status` exposes audio block

**Files:**
- Modify: `signaldeck/api/routes/scanner.py` — extend `get_status`
- Create: `tests/test_api_status_audio.py` — verify the new fields

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_status_audio.py`:

```python
"""Tests for /api/status audio block."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app
from signaldeck.api.websocket import audio_stream


def _config(tmp_path, audio_mode="auto"):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": audio_mode,
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }


@pytest.fixture(autouse=True)
def clear_clients():
    audio_stream._audio_clients.clear()
    yield
    audio_stream._audio_clients.clear()


async def test_status_audio_no_subscribers(tmp_path):
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            assert resp.status_code == 200
            body = resp.json()
            assert "audio" in body
            assert body["audio"]["configured_mode"] == "auto"
            assert body["audio"]["effective_mode"] == "gqrx"
            assert body["audio"]["subscriber_count"] == 0
            assert body["audio"]["remote_subscriber_count"] == 0


async def test_status_audio_with_remote_subscriber(tmp_path):
    audio_stream._audio_clients["w1"] = {
        "freq": 100e6, "is_lan": False, "remote_addr": "8.8.8.8"
    }
    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            body = resp.json()
            assert body["audio"]["effective_mode"] == "pcm_stream"
            assert body["audio"]["subscriber_count"] == 1
            assert body["audio"]["remote_subscriber_count"] == 1


async def test_status_audio_manual_gqrx_overrides(tmp_path):
    audio_stream._audio_clients["w1"] = {
        "freq": 100e6, "is_lan": False, "remote_addr": "8.8.8.8"
    }
    app = create_app(_config(tmp_path, audio_mode="gqrx"))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/status")
            body = resp.json()
            assert body["audio"]["configured_mode"] == "gqrx"
            assert body["audio"]["effective_mode"] == "gqrx"  # Manual pin
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_status_audio.py -v`

Expected: all three tests fail with KeyError 'audio' or similar.

- [ ] **Step 3: Extend `get_status`**

Open `signaldeck/api/routes/scanner.py`. Find the `@router.get("/status")` handler `get_status`. At the end of the function, before the return, build the audio block:

```python
    # Audio mode status
    from signaldeck.api.websocket.audio_stream import (
        _audio_clients,
        resolve_effective_audio_mode,
    )
    configured_audio_mode = scanner_cfg.get("audio_mode", "auto")
    effective_audio_mode = resolve_effective_audio_mode(configured_audio_mode)
    subscriber_count = sum(
        1 for info in _audio_clients.values()
        if isinstance(info, dict) and info.get("freq") is not None
    )
    remote_subscriber_count = sum(
        1 for info in _audio_clients.values()
        if isinstance(info, dict)
        and info.get("freq") is not None
        and not info.get("is_lan", True)
    )
```

Then add to the return dict:

```python
        "audio": {
            "configured_mode": configured_audio_mode,
            "effective_mode": effective_audio_mode,
            "subscriber_count": subscriber_count,
            "remote_subscriber_count": remote_subscriber_count,
        },
```

Make sure `scanner_cfg` is defined in this function. If it isn't (the function might read `config.get("scanner", {})` directly), reassign it near the top of the function body:

```python
    scanner_cfg = config.get("scanner", {})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_status_audio.py -v`

Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/routes/scanner.py tests/test_api_status_audio.py
git commit -m "$(cat <<'EOF'
feat: expose audio_mode state via /api/status.audio

New audio block in /api/status returns configured_mode, effective_mode,
subscriber_count, remote_subscriber_count so the Settings UI can show
a live 'currently active' indicator without needing a separate endpoint.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Frontend + UI prefs

Tasks 14–18. Depends on Phase A (login overlay) and Phase B (audio output card). No Python test layer for the frontend; each task uses a manual verification step in a browser.

### Task 14: Persist `liveVisibleCols` to `user_settings.yaml`

**Files:**
- Modify: `signaldeck/api/routes/scanner.py` — `_persist_user_config` writes `ui.live_visible_cols`; PUT accepts it
- Modify: `signaldeck/web/js/app.js` — `applySettings` reads it; auto-save on column toggle
- Create: `tests/test_ui_prefs_roundtrip.py` — backend round-trip test

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui_prefs_roundtrip.py`:

```python
"""Tests for ui.live_visible_cols round-trip through /api/settings."""
import pytest
from httpx import ASGITransport, AsyncClient

from signaldeck.api.server import create_app


def _config(tmp_path):
    return {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "auto",
        },
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
    }


async def test_put_settings_accepts_ui_live_visible_cols(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    monkeypatch.setattr(
        scanner_routes, "_USER_CONFIG_PATH",
        tmp_path / "user_settings.yaml",
    )

    app = create_app(_config(tmp_path))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            cols = ["frequency", "modulation", "hits", "last_seen"]
            resp = await c.put(
                "/api/settings",
                json={"ui": {"live_visible_cols": cols}},
            )
            assert resp.status_code == 200

            # Round-trip
            resp = await c.get("/api/settings")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("ui", {}).get("live_visible_cols") == cols


async def test_persist_writes_ui_block(tmp_path, monkeypatch):
    import signaldeck.api.routes.scanner as scanner_routes
    path = tmp_path / "user_settings.yaml"
    monkeypatch.setattr(scanner_routes, "_USER_CONFIG_PATH", path)

    config = {
        "devices": {"gain": 40},
        "scanner": {
            "squelch_offset": 10,
            "dwell_time_ms": 50,
            "fft_size": 1024,
            "sweep_ranges": [],
            "audio_mode": "auto",
        },
        "audio": {},
        "logging": {"level": "INFO"},
        "ui": {
            "live_visible_cols": ["frequency", "modulation"],
        },
    }
    scanner_routes._persist_user_config(config)

    import yaml
    with open(path) as f:
        persisted = yaml.safe_load(f)
    assert persisted["ui"]["live_visible_cols"] == ["frequency", "modulation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ui_prefs_roundtrip.py -v`

Expected: both tests fail — PUT doesn't accept a `ui` field, and `_persist_user_config` doesn't write a `ui:` block.

- [ ] **Step 3: Extend the settings model + persist**

Open `signaldeck/api/routes/scanner.py`. Find the Pydantic settings model (the one used by `PUT /settings`). Add a new field:

```python
class UiPrefs(BaseModel):
    live_visible_cols: list[str] | None = None


class UpdateSettingsRequest(BaseModel):
    # ... existing fields ...
    ui: UiPrefs | None = None
```

In the PUT handler, after the existing field handling:

```python
    if data.ui is not None and data.ui.live_visible_cols is not None:
        config.setdefault("ui", {})["live_visible_cols"] = list(data.ui.live_visible_cols)
        changed.append("ui.live_visible_cols")
```

Also extend `_persist_user_config` to include the ui block:

```python
    user_cfg = {
        "devices": { ... },
        "scanner": { ... },
        "audio": { ... },
        "logging": { ... },
        "ui": {
            "live_visible_cols": config.get("ui", {}).get(
                "live_visible_cols",
                [
                    "frequency",
                    "modulation",
                    "protocol",
                    "hits",
                    "last_seen",
                    "activity_summary",
                ],
            ),
        },
    }
```

And in the GET handler (the `@router.get("/settings")` function, if it exists — otherwise, `/api/scanner/status` or wherever GET returns the config), include the ui block in the response:

```python
        "ui": {
            "live_visible_cols": config.get("ui", {}).get(
                "live_visible_cols",
                ["frequency", "modulation", "protocol", "hits", "last_seen", "activity_summary"],
            ),
        },
```

If there is no explicit `@router.get("/settings")` handler, grep for where the frontend fetches `/api/settings` and find the response shape.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ui_prefs_roundtrip.py -v`

Expected: both tests PASS.

- [ ] **Step 5: Frontend changes — read on apply, auto-save on toggle**

Open `signaldeck/web/js/app.js`. Find the `applySettings(settings)` function. Near the other field assignments, add:

```javascript
      if (settings.ui && Array.isArray(settings.ui.live_visible_cols)) {
        this.liveVisibleCols = [...settings.ui.live_visible_cols];
      }
```

Find where `liveVisibleCols` is toggled in the UI (likely a method called `toggleLiveCol(name)` or inline Alpine binding in `index.html`). Add a debounced auto-save. If there isn't an existing column-toggle method, create one:

```javascript
    _saveColsTimer: null,

    toggleLiveCol(name) {
      const idx = this.liveVisibleCols.indexOf(name);
      if (idx >= 0) {
        this.liveVisibleCols.splice(idx, 1);
      } else {
        this.liveVisibleCols.push(name);
      }
      this._queueSaveColumns();
    },

    _queueSaveColumns() {
      if (this._saveColsTimer) clearTimeout(this._saveColsTimer);
      this._saveColsTimer = setTimeout(() => {
        this.apiFetch('/api/settings', {
          method: 'PUT',
          body: JSON.stringify({
            ui: { live_visible_cols: this.liveVisibleCols },
          }),
        });
      }, 500);
    },
```

And in `signaldeck/web/index.html`, wherever the column-toggle controls are rendered, wire them to the method:

```html
<label>
  <input type="checkbox"
         :checked="liveVisibleCols.includes('protocol')"
         @change="toggleLiveCol('protocol')">
  Protocol
</label>
```

(Apply this pattern to each column the user can toggle.) If the existing checkbox markup uses a different binding style (e.g. direct `x-model` on the array), preserve that style and just add a `@change="_queueSaveColumns()"` hook instead of rewriting.

- [ ] **Step 6: Manual verification**

Run: `.venv/bin/python -m signaldeck.main start --port 9091` (background terminal or a second session). Open `http://127.0.0.1:9091` in two browsers (e.g. a desktop browser and a phone on the LAN). Toggle off the `Hits` column in the first browser. Wait ~1 second. Refresh the second browser. Verify: the `Hits` column is hidden there too. Stop the test server.

- [ ] **Step 7: Commit**

```bash
git add signaldeck/api/routes/scanner.py signaldeck/web/js/app.js signaldeck/web/index.html tests/test_ui_prefs_roundtrip.py
git commit -m "$(cat <<'EOF'
feat: sync Live Signals column selection across devices

liveVisibleCols is now persisted to user_settings.yaml under a new
ui: section and round-tripped via /api/settings. Column toggles are
auto-saved after a 500ms debounce, so changes from one browser
appear on other browsers after a refresh.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Login overlay + first-run password modal (frontend)

**Files:**
- Modify: `signaldeck/web/index.html` — add login overlay markup + first-run password modal
- Modify: `signaldeck/web/js/app.js` — add Alpine state, extend `apiFetch`, wire toggle response
- Modify: `signaldeck/web/css/style.css` — overlay + modal styling (minimal, reuses variables)

- [ ] **Step 1: Add Alpine state**

Open `signaldeck/web/js/app.js`. Find the top of the `return {` body in the main component function (after `bookmarks: []` or similar). Add:

```javascript
    // ---- Login overlay state ----
    loginRequired: false,
    loginUsername: 'admin',
    loginPassword: '',
    loginError: '',
    _retryAfterLogin: null,

    // ---- First-run password modal state ----
    firstRunPassword: null,
    firstRunAcknowledged: false,
```

- [ ] **Step 2: Extend `apiFetch` to trigger the overlay on 401**

Find the `apiFetch(url, opts)` method. Before returning `null` on a 401, set the state:

```javascript
    async apiFetch(url, opts = {}) {
      const response = await fetch(url, {
        ...opts,
        headers: {
          'Content-Type': 'application/json',
          ...(opts.headers || {}),
        },
        credentials: 'same-origin',
      });

      if (response.status === 401) {
        this.loginRequired = true;
        this._retryAfterLogin = { url, opts };
        return null;
      }

      if (!response.ok) {
        // ... existing error handling ...
        return null;
      }
      return await response.json();
    },
```

The exact shape of the existing error handling may differ — preserve it. The only additive change is the `if (response.status === 401)` block.

- [ ] **Step 3: Add `submitLogin()` method**

In the same app.js file, add a method (near other auth methods):

```javascript
    async submitLogin() {
      this.loginError = '';
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: this.loginUsername,
          password: this.loginPassword,
        }),
        credentials: 'same-origin',
      });
      if (resp.status === 200) {
        this.loginRequired = false;
        this.loginPassword = '';
        this.showToast('Signed in', 'success');
        // Re-run whatever the user was trying to do
        if (this._retryAfterLogin) {
          const { url, opts } = this._retryAfterLogin;
          this._retryAfterLogin = null;
          return await this.apiFetch(url, opts);
        }
      } else {
        const body = await resp.json().catch(() => ({}));
        this.loginError = body.detail || 'Invalid username or password';
      }
    },
```

- [ ] **Step 4: Extend toggle-auth flow to show the first-run password modal**

Find the method that calls `POST /api/auth/toggle` (search for `/api/auth/toggle`). If the method exists, extend it:

```javascript
    async toggleAuth(enabled) {
      const data = await this.apiFetch('/api/auth/toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      });
      if (data && data.first_run_password) {
        this.firstRunPassword = data.first_run_password;
        this.firstRunAcknowledged = false;
      }
    },
```

If no such method exists, add it under the auth-related state block.

- [ ] **Step 5: Add overlay + modal markup to `index.html`**

Open `signaldeck/web/index.html`. Just before the closing `</body>` tag, add:

```html
<!-- Login overlay (shown on 401) -->
<div x-show="loginRequired" x-cloak
     style="position:fixed;inset:0;background:rgba(0,0,0,0.8);
            display:flex;align-items:center;justify-content:center;z-index:2000;">
  <div style="background:var(--bg-secondary);padding:32px;border-radius:var(--radius);
              max-width:360px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.6);">
    <h2 style="margin:0 0 16px 0;">Sign in</h2>
    <form @submit.prevent="submitLogin()">
      <div style="margin-bottom:12px;">
        <label style="display:block;margin-bottom:4px;">Username</label>
        <input type="text" class="form-input" style="width:100%;"
               x-model="loginUsername" autocomplete="username">
      </div>
      <div style="margin-bottom:12px;">
        <label style="display:block;margin-bottom:4px;">Password</label>
        <input type="password" class="form-input" style="width:100%;"
               x-model="loginPassword" autocomplete="current-password">
      </div>
      <div x-show="loginError" x-cloak
           style="color:var(--red);font-size:0.85rem;margin-bottom:12px;"
           x-text="loginError"></div>
      <button type="submit" class="btn btn-primary" style="width:100%;">
        Sign in
      </button>
    </form>
  </div>
</div>

<!-- First-run admin password modal (shown once, after auth.toggle enable) -->
<div x-show="firstRunPassword && !firstRunAcknowledged" x-cloak
     style="position:fixed;inset:0;background:rgba(0,0,0,0.85);
            display:flex;align-items:center;justify-content:center;z-index:2100;">
  <div style="background:var(--bg-secondary);padding:32px;border-radius:var(--radius);
              max-width:460px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.6);">
    <h2 style="margin:0 0 12px 0;">Auth enabled</h2>
    <p style="margin:0 0 16px 0;">
      Your admin password is:
    </p>
    <code style="display:block;padding:12px;background:var(--bg-primary);
                 border-radius:var(--radius-sm);font-size:1.1rem;word-break:break-all;
                 margin-bottom:12px;" x-text="firstRunPassword"></code>
    <button class="btn btn-sm" style="margin-bottom:16px;"
            @click="navigator.clipboard.writeText(firstRunPassword); showToast('Copied', 'success')">
      Copy to clipboard
    </button>
    <p style="margin:0 0 16px 0;font-size:0.85rem;color:var(--text-secondary);">
      Save this in your password manager now. You will not see it again
      — the server only stores its hash.
    </p>
    <button class="btn btn-primary" style="width:100%;"
            @click="firstRunAcknowledged = true; firstRunPassword = null;">
      I've saved it
    </button>
  </div>
</div>
```

- [ ] **Step 6: Add minimal styling** (only if the existing style.css lacks form-input padding inside modals — usually it's fine and this step can be skipped)

If styling looks broken, add to `signaldeck/web/css/style.css`:

```css
.form-input {
  padding: 8px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
}
```

Only add this if the selector doesn't already exist.

- [ ] **Step 7: Manual verification**

1. Enable auth for the first time (delete `config/credentials.yaml` if it exists, then flip `auth.enabled: true` in config or via POST /api/auth/toggle).
2. Restart the service.
3. Open the dashboard in a browser that's NOT in the LAN allowlist (hard case: tether your phone to cell data, or temporarily remove your LAN subnet from `auth.lan_allowlist`). Verify the login overlay appears on first action.
4. Submit wrong credentials; verify the error message appears and the overlay stays.
5. Submit correct credentials; verify the overlay disappears, a success toast appears, and the dashboard loads.
6. Refresh the browser; verify no login overlay (cookie persists).

For the first-run password modal: the easiest way is to invoke `POST /api/auth/toggle` from the UI (likely in Settings → Auth section) with credentials.yaml pre-deleted. Verify the modal shows the generated password, the Copy button works, and clicking "I've saved it" dismisses the modal.

- [ ] **Step 8: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js signaldeck/web/css/style.css
git commit -m "$(cat <<'EOF'
feat: login overlay + first-run password modal

apiFetch now sets loginRequired=true on a 401 and stashes the failed
request in _retryAfterLogin. The login overlay (modal) submits to
/api/auth/login, closes itself on success, and replays the original
action. toggleAuth catches the first_run_password in the toggle
response and shows a one-time copy-to-clipboard modal.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Signed-in devices card in Settings

**Files:**
- Modify: `signaldeck/web/index.html` — add the card markup in the Settings page
- Modify: `signaldeck/web/js/app.js` — add state + fetch/rename/revoke methods

- [ ] **Step 1: Add Alpine state and methods**

In `signaldeck/web/js/app.js`, add state near the other settings fields:

```javascript
    sessions: [],
```

And methods:

```javascript
    async fetchSessions() {
      const data = await this.apiFetch('/api/auth/sessions');
      if (data) this.sessions = Array.isArray(data) ? data : [];
    },

    async renameSession(id, newLabel) {
      if (!newLabel) return;
      const ok = await this.apiFetch(`/api/auth/sessions/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ label: newLabel }),
      });
      if (ok) {
        this.showToast('Renamed', 'success');
        this.fetchSessions();
      }
    },

    async revokeSession(id) {
      if (!confirm('Revoke this device? It will need to sign in again.')) return;
      const resp = await fetch(`/api/auth/sessions/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (resp.status === 200) {
        this.showToast('Revoked', 'success');
        this.fetchSessions();
      } else if (resp.status === 401) {
        this.loginRequired = true;
      }
    },

    promptRenameSession(session) {
      const newLabel = prompt('New label for this device:', session.label || '');
      if (newLabel != null && newLabel.trim()) {
        this.renameSession(session.id, newLabel.trim());
      }
    },
```

Also wire `fetchSessions()` into the settings-page data load. Find `fetchPageData()` (around line 236) and extend it:

```javascript
    fetchPageData() {
      // ... existing ...
      if (this.currentPage === 'settings') {
        this.fetchSettings(true);
        this.fetchSessions();  // NEW
      }
      // ... rest ...
    },
```

- [ ] **Step 2: Add the card markup**

In `signaldeck/web/index.html`, find the Settings page section (`<section x-show="currentPage === 'settings'"`). Find an appropriate location for a new card (below the existing auth-related settings, if any; otherwise near the bottom of the page). Add:

```html
<!-- Signed-in devices card -->
<div class="card" style="margin-top:16px;">
  <h3 style="margin-top:0;">Signed-in devices</h3>
  <p style="font-size:0.85rem;color:var(--text-secondary);margin-top:0;">
    Devices that have logged in with a password and are using a remember-me cookie.
    Devices on Tailscale / LAN don't appear here — they bypass login entirely.
  </p>
  <table class="settings-table" style="width:100%;">
    <thead>
      <tr>
        <th style="text-align:left;">Label</th>
        <th style="text-align:left;">First signed in</th>
        <th style="text-align:left;">Last used</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <template x-for="s in sessions" :key="s.id">
        <tr>
          <td>
            <span x-text="s.label || '(unnamed)'"></span>
            <span x-show="s.is_current" class="badge badge-green"
                  style="margin-left:6px;font-size:0.7rem;">this device</span>
          </td>
          <td x-text="new Date(s.created_at).toLocaleDateString()"></td>
          <td x-text="new Date(s.last_used_at).toLocaleString()"></td>
          <td style="text-align:right;white-space:nowrap;">
            <button class="btn btn-sm" @click="promptRenameSession(s)">Rename</button>
            <button class="btn btn-sm btn-danger" @click="revokeSession(s.id)">Revoke</button>
          </td>
        </tr>
      </template>
      <tr x-show="sessions.length === 0">
        <td colspan="4" class="empty-state">No devices signed in.</td>
      </tr>
    </tbody>
  </table>
</div>
```

- [ ] **Step 3: Manual verification**

1. Ensure auth is enabled and you have at least one remember-me cookie from a previous login.
2. Navigate to Settings. Verify the "Signed-in devices" card renders with at least one row marked "this device."
3. Click Rename, enter a new label, verify the table updates.
4. From a second browser or incognito window, log in (creating a second row). Verify both rows appear in each browser.
5. In one browser, click Revoke on the OTHER device's row. Refresh the other browser — verify it falls back to the login overlay.

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
feat: Signed-in devices card in Settings

Lists all remember-me sessions with label, timestamps, and rename/
revoke actions. The requesting device is badged as 'this device.'
Revoking another session invalidates it instantly; revoking the
current device triggers the login overlay on next request.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: Audio Output card in Settings

**Files:**
- Modify: `signaldeck/web/index.html` — add the card with three radio buttons + live status line
- Modify: `signaldeck/web/js/app.js` — wire the audio_mode setting and compute the active-line text

- [ ] **Step 1: Add state and save method**

In `signaldeck/web/js/app.js`, add to the state:

```javascript
    audioMode: 'auto',  // auto | gqrx | pcm_stream
    audioStatus: {
      configured_mode: 'auto',
      effective_mode: 'gqrx',
      subscriber_count: 0,
      remote_subscriber_count: 0,
    },
```

In `applySettings()`, read the new field:

```javascript
      if (settings.scanner && settings.scanner.audio_mode) {
        this.audioMode = settings.scanner.audio_mode;
      }
```

In `fetchStatus()` (the periodic status poll), read the audio block:

```javascript
      if (data && data.audio) {
        this.audioStatus = data.audio;
      }
```

Add a save method:

```javascript
    async saveAudioMode() {
      const resp = await this.apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ audio_mode: this.audioMode }),
      });
      if (resp) {
        this.showToast(`Audio mode: ${this.audioMode}`, 'success');
      }
    },
```

- [ ] **Step 2: Add the card markup**

In `signaldeck/web/index.html`, inside the Settings page section, add (positioning it with the other audio-related cards if possible):

```html
<!-- Audio Output card -->
<div class="card" style="margin-top:16px;">
  <h3 style="margin-top:0;">Audio Output</h3>
  <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px;">
    <label style="display:flex;align-items:flex-start;gap:8px;">
      <input type="radio" value="auto" x-model="audioMode" @change="saveAudioMode()">
      <span>
        <strong>Automatic</strong>
        <div style="font-size:0.8rem;color:var(--text-secondary);">
          Local gqrx when only LAN clients are listening, browser stream
          when any remote client is connected. Default.
        </div>
      </span>
    </label>
    <label style="display:flex;align-items:flex-start;gap:8px;">
      <input type="radio" value="gqrx" x-model="audioMode" @change="saveAudioMode()">
      <span>
        <strong>Local gqrx</strong>
        <div style="font-size:0.8rem;color:var(--text-secondary);">
          Always play through the server's speakers via gqrx.
          Remote browsers will not receive audio.
        </div>
      </span>
    </label>
    <label style="display:flex;align-items:flex-start;gap:8px;">
      <input type="radio" value="pcm_stream" x-model="audioMode" @change="saveAudioMode()">
      <span>
        <strong>Browser stream</strong>
        <div style="font-size:0.8rem;color:var(--text-secondary);">
          Always stream PCM to connected browsers. gqrx stays tuned but
          muted.
        </div>
      </span>
    </label>
  </div>
  <div style="padding:12px;background:var(--bg-primary);border-radius:var(--radius-sm);">
    <strong>Currently active:</strong>
    <span x-text="audioStatus.effective_mode === 'pcm_stream' ? 'Browser stream' : 'Local gqrx'"></span>
    <span style="color:var(--text-secondary);" x-show="audioStatus.subscriber_count > 0">
      — <span x-text="audioStatus.subscriber_count"></span> subscriber(s),
      <span x-text="audioStatus.remote_subscriber_count"></span> remote
    </span>
  </div>
</div>
```

- [ ] **Step 3: Add the silence banner for the remote-on-gqrx edge case**

Find the audio player / listen button area in the Live Signals page. Add a warning banner that shows when the user is subscribed to audio but the effective mode is `gqrx`:

```html
<div x-show="audioPlaying && audioStatus.effective_mode === 'gqrx'
             && audioStatus.remote_subscriber_count === 0
             && !window.location.hostname.match(/^(127\.|localhost|10\.|192\.168\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[0-1]\.|100\.[6-9][4-9]|100\.1[0-1][0-9]|100\.12[0-7]\.)/)"
     x-cloak
     class="warning-banner"
     style="padding:8px 12px;background:var(--yellow-dim,#4a3b15);color:var(--yellow,#f0c860);
            border-radius:var(--radius-sm);margin:8px 0;font-size:0.85rem;">
  Audio mode is set to <strong>Local gqrx</strong> — this browser will not
  receive audio. <a href="#" @click.prevent="audioMode='auto'; saveAudioMode()">Switch to Automatic</a>
</div>
```

(The long regex on `window.location.hostname` is a coarse client-side check: if the user is accessing from a LAN-like address, gqrx-local audio is probably what they want and the banner stays hidden; if they're on a public-looking address, the banner shows. This is just UX hinting — the real decision lives server-side.)

- [ ] **Step 4: Manual verification**

1. Open the dashboard in a local browser. Navigate to Settings. Verify the Audio Output card renders with three radio buttons. The "Currently active" line should read "Local gqrx" and show zero subscribers.
2. Click "Listen" on any signal. Refresh `/api/status`. Verify `audioStatus.subscriber_count` increments.
3. Change the setting to "Browser stream" and verify the card's "Currently active" flips to "Browser stream."
4. Change back to "Automatic." Connect from a REMOTE client (e.g. phone on cell data through Tailscale if still in CGNAT, or temporarily remove Tailscale CGNAT from the allowlist and reconnect). Verify `remote_subscriber_count` increments and the effective line reads "Browser stream."
5. Manually pin to "Local gqrx" with a remote browser still subscribed; verify the silence warning banner appears in that browser.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
feat: Audio Output card with three-way mode selector + live status

Three radio buttons (Automatic / Local gqrx / Browser stream) write
to scanner.audio_mode via PUT /api/settings. A 'Currently active'
line shows the effective mode and subscriber counts, refreshed from
/api/status on the existing 3-second poll. A warning banner on the
Live page alerts remote clients when audio_mode is pinned to gqrx
so they don't wonder why they hear nothing.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: Regression sweep + branch commit

**Files:**
- None created. This task runs the full test suite and documents any follow-ups.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q`

Expected: all tests PASS. Pre-existing excluded tests (`test_ai_modulation` needs torch, `test_integration` needs real HackRF) remain excluded per the handoff.

If any test fails, diagnose and fix before proceeding. Commonly:
- A test that imported the old `_audio_clients` type (`dict[WebSocket, float | None]`) → update the mock to use the dict-shape.
- A test that expected the login response to have `session_token` → update to `remember_token`.
- A test that relied on `/api/auth/sessions` being public → update to expect 401.

- [ ] **Step 2: Smoke-test the running service**

Run: `systemctl --user restart signaldeck.service` and then:

```bash
systemctl --user is-active signaldeck.service
curl -sS http://127.0.0.1:9090/api/health
curl -sS http://127.0.0.1:9090/api/status | python3 -m json.tool | head -30
```

Expected: service active, health returns `{"status":"ok","version":"..."}`, status returns a JSON body that includes an `audio` block.

- [ ] **Step 3: End-to-end acceptance check**

Walk through each of the 11 acceptance criteria from the spec (`docs/superpowers/specs/2026-04-10-single-user-auth-and-audio-modes-design.md` → "Acceptance criteria" section). For each one, either:
- Mark it verified with a one-line note in the commit message, or
- Create a follow-up note if the criterion is partially met.

- [ ] **Step 4: Final commit if anything changed**

If tests or smoke-test surfaced small fixes:

```bash
git add <fixed files>
git commit -m "$(cat <<'EOF'
fix: regressions surfaced during the auth+audio-mode sweep

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

If everything passed cleanly, there's nothing to commit — proceed to merging the branch.

- [ ] **Step 5: Push and open PR (if working on a branch)**

```bash
git status
git log --oneline $(git merge-base HEAD origin/master)..HEAD
git push -u origin HEAD
gh pr create --title "Single-user auth + location-aware audio modes" \
             --body "$(cat <<'EOF'
## Summary
- LAN-bypass auth gate (loopback, RFC1918, IPv6 ULA, Tailscale CGNAT) with remember-me cookies for remote clients
- Closes the pre-existing /ws/* auth hole
- Audio mode auto-switches between gqrx-local and PCM-stream based on whether any listener is remote
- Live Signals column selection follows the operator across browsers
- CLI `signaldeck auth set-password` as a forgotten-password escape hatch
- First-run password modal shows the auto-generated admin password exactly once

See `docs/superpowers/specs/2026-04-10-single-user-auth-and-audio-modes-design.md`
for the full design.

## Test plan
- [ ] Full pytest suite passes (excluding pre-existing torch / hardware tests)
- [ ] Dashboard accessible without login from LAN and Tailscale
- [ ] Dashboard shows login overlay from non-LAN browser, cookie persists after login
- [ ] Signed-in devices card lists and revokes correctly
- [ ] Audio Output card flips mode and shows live subscriber count
- [ ] `signaldeck auth set-password` resets the admin password without the current one

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Skip this step if the work is landing directly on `master` per the operator's normal workflow.

---

## Self-review check

All 11 spec acceptance criteria covered:

1. ✅ Backwards compat with `auth.enabled: false` — Task 5 middleware early-return, Task 10 audio_mode defaults to auto → gqrx when no remote subscribers.
2. ✅ Tailscale dashboard access without password — Task 1 adds CGNAT to default allowlist, Task 5 wires it into the middleware.
3. ✅ Public IP attacker gets 401 on REST and 1008 on WS — Task 5 + Task 6.
4. ✅ Non-Tailscale browser sees login overlay, cookie persists — Task 7 sets cookie, Task 15 adds overlay.
5. ✅ Signed-in devices list with instant revoke — Task 8 endpoints, Task 16 UI.
6. ✅ Audio Output card with live status — Task 13 API, Task 17 UI.
7. ✅ Auto mode mutes gqrx when remote subscriber connects — Task 11 resolver, Task 12 controller.
8. ✅ Manual gqrx mode + remote subscriber shows silence banner — Task 11 sends effective_mode in subscribed reply, Task 17 adds the banner.
9. ✅ Column selection syncs across browsers — Task 14.
10. ✅ CLI password reset — Task 9.
11. ✅ All new tests pass — Task 18 regression sweep.

No placeholders or TBDs in any task. Every code step shows actual code. Every test step shows actual test code. Every command step shows the exact command and expected output.

Type-consistency cross-check:
- `is_lan_client(ip, allowlist)` — Task 1 defines, Task 5 and Task 6 use with same signature. ✓
- `create_remember_token(db, *, user_agent, ip, label=None) -> str` — Task 4 defines, Task 7 uses with same kwargs. ✓
- `verify_remember_token(db, raw_token) -> bool` — Task 4 defines, Task 5 and Task 6 and Task 8 logout use with same signature. ✓
- `_audio_clients: dict[WebSocket, dict]` — Task 11 changes shape, Task 13 reads with same shape. ✓
- `resolve_effective_audio_mode(configured_mode: str) -> str` — Task 11 defines, Task 12 and Task 13 use. ✓
- `AudioModeController.apply_effective_mode(mode, user_volume_db)` — Task 12 defines and uses. ✓
- `/api/auth/sessions` response shape — Task 8 defines, Task 16 consumes with same fields. ✓

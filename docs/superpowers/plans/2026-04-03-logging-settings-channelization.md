# Logging, Settings/Status Split & Frequency Channelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move logging from console to session log files with a viewer page, split Settings into read-only Status and editable Settings pages with new controls, and snap detected signals to standard FCC/ITU channel frequencies.

**Architecture:** Three independent subsystems that converge on the UI. (1) Dual-handler logging: FileHandler at INFO+ to `data/logs/`, StreamHandler at WARNING+ to console, with REST endpoints and a Logs viewer page. (2) Status/Settings split: new database clear/stats methods, new API endpoints for data management and auth controls, and two separate pages in the frontend. (3) Channelizer: pure function that snaps frequencies to nearest channel step, called in `on_signals()` before classification/storage/broadcast.

**Tech Stack:** Python asyncio, FastAPI, aiosqlite, Alpine.js, PyYAML

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `signaldeck/engine/channelizer.py` | Create | Channel spacing table + `channelize()` pure function |
| `tests/test_channelizer.py` | Create | Channel snapping tests for all 11 bands + edge cases |
| `signaldeck/main.py` | Modify | Dual-handler logging setup, channelizer call in `on_signals` |
| `signaldeck/api/routes/logs.py` | Create | Log file listing/viewing/deletion REST endpoints |
| `tests/test_api_logs.py` | Create | Log API endpoint tests |
| `signaldeck/storage/database.py` | Modify | Add `clear_signals()`, `clear_activity()`, `clear_bookmarks()`, `clear_recordings()`, `clear_all()`, `get_stats()` |
| `tests/test_database_clear.py` | Create | Tests for clear/stats methods |
| `signaldeck/api/routes/signals.py` | Modify | Add DELETE endpoints for data management |
| `tests/test_api_data_management.py` | Create | Data management endpoint tests |
| `signaldeck/api/routes/auth_routes.py` | Modify | Add toggle, regenerate-token, get-token endpoints |
| `tests/test_auth_extended.py` | Create | Tests for new auth endpoints |
| `signaldeck/api/routes/scanner.py` | Modify | Add `GET /api/status`, extend `PUT /api/settings` with audio/logging/device fields, persist new fields |
| `signaldeck/api/server.py` | Modify | Register logs router |
| `config/default.yaml` | Modify | Add `logging.log_dir` default |
| `signaldeck/web/index.html` | Modify | Split into Status + Settings + Logs pages, add new nav tabs, add new controls |
| `signaldeck/web/js/app.js` | Modify | Status/Settings/Logs page state, data management actions, device role dropdowns, log viewer logic |

---

## Task 1: Frequency Channelizer (Pure Function)

**Files:**
- Create: `signaldeck/engine/channelizer.py`
- Create: `tests/test_channelizer.py`

- [ ] **Step 1: Write channelizer tests**

```python
# tests/test_channelizer.py
import pytest
from signaldeck.engine.channelizer import channelize


class TestChannelize:
    """Test frequency channelization against FCC/ITU band plans."""

    # --- NOAA Weather (162.400-162.550 MHz, 25 kHz step) ---
    def test_noaa_exact(self):
        assert channelize(162_400_000) == 162_400_000

    def test_noaa_snaps_up(self):
        # 162.413 MHz -> nearest 25 kHz step = 162.425 MHz
        assert channelize(162_413_000) == 162_425_000

    def test_noaa_snaps_down(self):
        # 162.436 MHz -> nearest 25 kHz step = 162.425 MHz
        assert channelize(162_436_000) == 162_425_000

    # --- Marine VHF (156.000-162.000 MHz, 25 kHz step) ---
    def test_marine_vhf(self):
        assert channelize(156_012_000) == 156_000_000

    def test_marine_ch16(self):
        # Channel 16 = 156.800 MHz, exact
        assert channelize(156_800_000) == 156_800_000

    # --- FM Broadcast (88-108 MHz, 200 kHz step) ---
    def test_fm_broadcast_exact(self):
        assert channelize(101_100_000) == 101_100_000

    def test_fm_broadcast_snaps(self):
        # 99.050 MHz -> nearest 200 kHz = 99.100 MHz (odd multiples of 100 kHz in US)
        assert channelize(99_050_000) == 99_100_000

    def test_fm_broadcast_snaps_down(self):
        assert channelize(99_140_000) == 99_100_000

    # --- Airband (118-137 MHz, 25 kHz step) ---
    def test_airband(self):
        assert channelize(121_512_000) == 121_500_000

    # --- 2m Ham (144-148 MHz, 5 kHz step) ---
    def test_2m_ham(self):
        assert channelize(146_521_000) == 146_520_000

    def test_2m_ham_exact(self):
        assert channelize(146_520_000) == 146_520_000

    # --- VHF High (150-174 MHz, 12.5 kHz step) ---
    def test_vhf_high(self):
        # 155.007 MHz -> nearest 12.5 kHz = 155.0125 MHz
        assert channelize(155_007_000) == 155_012_500

    # --- ISM 433 (433.050-434.790 MHz, 25 kHz step) ---
    def test_ism_433(self):
        assert channelize(433_912_000) == 433_900_000

    # --- GMRS/FRS (462.000-467.000 MHz, 12.5 kHz step) ---
    def test_gmrs(self):
        assert channelize(462_567_000) == 462_562_500

    # --- VHF Low (30-88 MHz, 20 kHz step) ---
    def test_vhf_low(self):
        assert channelize(42_015_000) == 42_020_000

    # --- 70cm Ham (420-450 MHz, 5 kHz step) ---
    def test_70cm_ham(self):
        assert channelize(446_002_000) == 446_000_000

    # --- UHF Land Mobile (450-470 MHz, 12.5 kHz step) ---
    def test_uhf_land_mobile(self):
        assert channelize(460_007_000) == 460_012_500

    # --- Priority: specific bands override broader bands ---
    def test_noaa_overrides_marine(self):
        # 162.425 is in both NOAA (25 kHz) and Marine VHF (25 kHz) ranges
        # NOAA is higher priority (checked first)
        assert channelize(162_425_000) == 162_425_000

    def test_gmrs_overrides_uhf(self):
        # 462.5625 is in both GMRS (12.5 kHz) and UHF Land Mobile (12.5 kHz)
        # GMRS is higher priority
        assert channelize(462_562_500) == 462_562_500

    # --- Passthrough: outside all bands ---
    def test_passthrough_below_all_bands(self):
        assert channelize(1_000_000) == 1_000_000

    def test_passthrough_above_all_bands(self):
        assert channelize(900_000_000) == 900_000_000

    # --- Types ---
    def test_returns_float(self):
        result = channelize(101_100_000.0)
        assert isinstance(result, float)

    def test_accepts_int(self):
        result = channelize(101_100_000)
        assert isinstance(result, float)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_channelizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'signaldeck.engine.channelizer'`

- [ ] **Step 3: Implement the channelizer**

```python
# signaldeck/engine/channelizer.py
"""Snap detected frequencies to standard FCC/ITU channel spacing."""

# (priority, label, start_hz, end_hz, step_hz)
# More specific ranges first — checked in order, first match wins.
_CHANNEL_TABLE: list[tuple[int, str, float, float, float]] = [
    (1, "NOAA Weather", 162_400_000, 162_550_000, 25_000),
    (2, "Marine VHF", 156_000_000, 162_000_000, 25_000),
    (3, "ISM 433", 433_050_000, 434_790_000, 25_000),
    (4, "GMRS/FRS", 462_000_000, 467_000_000, 12_500),
    (5, "VHF Low", 30_000_000, 88_000_000, 20_000),
    (6, "FM Broadcast", 88_000_000, 108_000_000, 200_000),
    (7, "Airband", 118_000_000, 137_000_000, 25_000),
    (8, "2m Ham", 144_000_000, 148_000_000, 5_000),
    (9, "VHF High", 150_000_000, 174_000_000, 12_500),
    (10, "70cm Ham", 420_000_000, 450_000_000, 5_000),
    (11, "UHF Land Mobile", 450_000_000, 470_000_000, 12_500),
]


def channelize(frequency_hz: float) -> float:
    """Snap a frequency to the nearest standard channel for its band.

    Iterates the channel table (specific bands first). Returns the snapped
    frequency, or the original if no band matches.
    """
    freq = float(frequency_hz)
    for _prio, _label, start, end, step in _CHANNEL_TABLE:
        if start <= freq <= end:
            return round(round(freq / step) * step, 1)
    return freq
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_channelizer.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/engine/channelizer.py tests/test_channelizer.py
git commit -m "feat: add frequency channelizer with FCC/ITU band tables"
```

---

## Task 2: Integrate Channelizer into Signal Pipeline

**Files:**
- Modify: `signaldeck/main.py` (line 193-244, the `on_signals` callback)

- [ ] **Step 1: Add channelizer import and call in on_signals**

In `signaldeck/main.py`, add import at the top (after line 8):

```python
from signaldeck.engine.channelizer import channelize
```

In the `on_signals` callback (line 193), after the weak signal filter (line 198) and before the SignalInfo creation (line 200), add channelization:

Replace lines 200-204:
```python
                signal_info = SignalInfo(
                    frequency_hz=sig.frequency_hz,
                    bandwidth_hz=sig.bandwidth_hz,
                    peak_power=sig.peak_power,
                    modulation="unknown",
                )
```

With:
```python
                # Snap to nearest standard channel frequency
                freq_hz = channelize(sig.frequency_hz)
                signal_info = SignalInfo(
                    frequency_hz=freq_hz,
                    bandwidth_hz=sig.bandwidth_hz,
                    peak_power=sig.peak_power,
                    modulation="unknown",
                )
```

Also update the database signal creation (line 209) to use `freq_hz`:
```python
                db_signal = Signal(
                    frequency=freq_hz,
```

And the summary line (line 229):
```python
                    summary=f"{freq_hz / 1e6:.3f} MHz "
```

And the WebSocket broadcast (line 238):
```python
                    msg = msg_fn(
                        frequency_hz=freq_hz,
```

- [ ] **Step 2: Run full test suite to verify no regressions**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS (channelizer is a pure function; existing tests don't exercise `on_signals` directly)

- [ ] **Step 3: Commit**

```bash
git add signaldeck/main.py
git commit -m "feat: channelize frequencies in on_signals before classification/storage/broadcast"
```

---

## Task 3: Dual-Handler Logging Setup

**Files:**
- Modify: `signaldeck/main.py` (lines 11-16, the `setup_logging` function)
- Modify: `config/default.yaml` (add `log_dir`)

- [ ] **Step 1: Update default.yaml with log_dir**

Add `log_dir` under the `logging` section in `config/default.yaml`:

```yaml
logging:
  level: "INFO"
  log_dir: "data/logs"
```

- [ ] **Step 2: Rewrite setup_logging for dual handlers**

Replace the `setup_logging` function in `signaldeck/main.py` (lines 11-16):

```python
def setup_logging(level: str, log_dir: str = "data/logs") -> Path:
    """Configure dual-handler logging: file at INFO+, console at WARNING+.

    Returns the path to the current session log file.
    """
    from datetime import datetime as _dt

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = _dt.now().strftime("%Y-%m-%dT%H-%M-%S")
    log_file = log_path / f"signaldeck-{timestamp}.log"

    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # File handler — full detail at configured level
    fh = logging.FileHandler(log_file)
    fh.setLevel(getattr(logging, level.upper(), logging.INFO))
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(fh)

    # Console handler — only warnings and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(ch)

    return log_file
```

- [ ] **Step 3: Update the start command to use new setup_logging**

In `signaldeck/main.py`, find the `setup_logging` call (line 74):

```python
    setup_logging(cfg["logging"]["level"])
```

Replace with:

```python
    log_dir = cfg["logging"].get("log_dir", "data/logs")
    log_file = setup_logging(cfg["logging"]["level"], log_dir)
```

Store `log_file` in the config dict so the status endpoint can report it (add after the line above):

```python
    cfg["_session_log_file"] = str(log_file)
    cfg["_start_time"] = datetime.now(timezone.utc).isoformat()
```

(The `datetime` and `timezone` imports are already present from later in the file at the `on_signals` callback scope — move or duplicate them at the top if needed. Check actual imports.)

- [ ] **Step 4: Verify logging works by running the app briefly**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All PASS (tests use their own logging config via `tmp_config` fixture, won't conflict)

- [ ] **Step 5: Commit**

```bash
git add signaldeck/main.py config/default.yaml
git commit -m "feat: dual-handler logging — file at INFO+, console at WARNING+"
```

---

## Task 4: Log API Endpoints

**Files:**
- Create: `signaldeck/api/routes/logs.py`
- Create: `tests/test_api_logs.py`
- Modify: `signaldeck/api/server.py` (register router)

- [ ] **Step 1: Write log API tests**

```python
# tests/test_api_logs.py
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    # Create a couple of fake log files
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
        # Sorted by name descending (newest first)
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
        # Current session log should be preserved
        remaining = list(log_dir.glob("*.log"))
        assert len(remaining) == 1
        assert "11-00-00" in remaining[0].name

    async def test_path_traversal_blocked(self, client):
        resp = await client.get("/api/logs/../../etc/passwd")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_logs.py -v`
Expected: FAIL — import error or 404 (router not registered)

- [ ] **Step 3: Implement log API routes**

```python
# signaldeck/api/routes/logs.py
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from signaldeck.api.server import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


def _log_dir() -> Path:
    config = get_config()
    return Path(config.get("logging", {}).get("log_dir", "data/logs"))


def _session_log() -> str | None:
    config = get_config()
    return config.get("_session_log_file")


@router.get("")
async def list_logs():
    """List available log files, newest first."""
    log_path = _log_dir()
    if not log_path.exists():
        return []
    files = sorted(log_path.glob("signaldeck-*.log"), reverse=True)
    return [
        {
            "name": f.name,
            "size": f.stat().st_size,
            "created": f.stat().st_mtime,
        }
        for f in files
    ]


@router.get("/current")
async def get_current_log():
    """Return contents of the current session log."""
    session_log = _session_log()
    if not session_log or not Path(session_log).exists():
        raise HTTPException(status_code=404, detail="No active session log")
    return {"name": Path(session_log).name, "content": Path(session_log).read_text()}


@router.get("/{filename}")
async def get_log(filename: str):
    """Return contents of a specific log file."""
    log_path = _log_dir() / filename
    # Prevent path traversal
    if not log_path.resolve().is_relative_to(_log_dir().resolve()):
        raise HTTPException(status_code=404, detail="Log file not found")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"name": filename, "content": log_path.read_text()}


@router.delete("")
async def delete_logs():
    """Delete all log files except the current session log."""
    log_path = _log_dir()
    session_log = _session_log()
    session_name = Path(session_log).name if session_log else None
    deleted = 0
    for f in log_path.glob("signaldeck-*.log"):
        if f.name != session_name:
            f.unlink()
            deleted += 1
    return {"deleted": deleted}
```

- [ ] **Step 4: Register the logs router in server.py**

In `signaldeck/api/server.py`, after line 104 (`from signaldeck.api.routes.auth_routes import router as auth_router`), add:

```python
    from signaldeck.api.routes.logs import router as logs_router
```

After line 111 (`app.include_router(auth_router, prefix="/api")`), add:

```python
    app.include_router(logs_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api_logs.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add signaldeck/api/routes/logs.py tests/test_api_logs.py signaldeck/api/server.py
git commit -m "feat: add log file listing/viewing/deletion API endpoints"
```

---

## Task 5: Database Clear and Stats Methods

**Files:**
- Modify: `signaldeck/storage/database.py` (add methods after line 304)
- Create: `tests/test_database_clear.py`

- [ ] **Step 1: Write tests for clear and stats methods**

```python
# tests/test_database_clear.py
import pytest
from pathlib import Path
from datetime import datetime, timezone

from signaldeck.storage.database import Database
from signaldeck.storage.models import Signal, ActivityEntry


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    yield database
    await database.close()


async def _seed(db):
    """Insert a signal and activity entry for testing."""
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
    return sig_id


@pytest.mark.asyncio
class TestDatabaseClear:
    async def test_clear_signals(self, db):
        await _seed(db)
        assert len(await db.get_all_signals()) == 1
        await db.clear_signals()
        assert len(await db.get_all_signals()) == 0

    async def test_clear_activity(self, db):
        await _seed(db)
        assert len(await db.get_recent_activity()) == 1
        await db.clear_activity()
        assert len(await db.get_recent_activity()) == 0

    async def test_clear_bookmarks(self, db):
        await db.insert_bookmark({"frequency": 101_100_000, "label": "Test FM"})
        bookmarks = await db.get_all_bookmarks()
        assert len(bookmarks) == 1
        await db.clear_bookmarks()
        assert len(await db.get_all_bookmarks()) == 0

    async def test_clear_all(self, db):
        await _seed(db)
        await db.insert_bookmark({"frequency": 101_100_000, "label": "Test"})
        await db.clear_all()
        assert len(await db.get_all_signals()) == 0
        assert len(await db.get_recent_activity()) == 0
        assert len(await db.get_all_bookmarks()) == 0

    async def test_get_stats(self, db):
        await _seed(db)
        stats = await db.get_stats()
        assert stats["signals"] == 1
        assert stats["activity"] == 1
        assert stats["bookmarks"] == 0
        assert "db_size" in stats
        assert stats["db_size"] > 0

    async def test_get_stats_empty(self, db):
        stats = await db.get_stats()
        assert stats["signals"] == 0
        assert stats["activity"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database_clear.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'clear_signals'`

- [ ] **Step 3: Implement clear and stats methods**

Add these methods to the `Database` class in `signaldeck/storage/database.py`, after the `get_recent_activity` method (after line 304):

```python
    async def clear_signals(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM signals")
            await self._conn.commit()

    async def clear_activity(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM activity_log")
            await self._conn.commit()

    async def clear_bookmarks(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM bookmarks")
            await self._conn.commit()

    async def clear_recordings(self) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM recordings")
            await self._conn.commit()

    async def clear_all(self) -> None:
        async with self._lock:
            for table in ("signals", "activity_log", "bookmarks", "recordings",
                          "decoder_results", "learned_patterns"):
                await self._conn.execute(f"DELETE FROM {table}")
            await self._conn.commit()

    async def get_stats(self) -> dict:
        counts = {}
        for name, table in [("signals", "signals"), ("activity", "activity_log"),
                            ("bookmarks", "bookmarks"), ("recordings", "recordings")]:
            cursor = await self._conn.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            counts[name] = row[0]
        counts["db_size"] = Path(self._db_path).stat().st_size
        return counts
```

Also add `from pathlib import Path` at the top of `database.py` if not already imported (check line 1-8).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_database_clear.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/storage/database.py tests/test_database_clear.py
git commit -m "feat: add database clear_*/get_stats methods for data management"
```

---

## Task 6: Data Management API Endpoints

**Files:**
- Modify: `signaldeck/api/routes/signals.py`
- Create: `tests/test_api_data_management.py`

- [ ] **Step 1: Write data management API tests**

```python
# tests/test_api_data_management.py
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
        # Verify signals are gone
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

    async def test_get_stats(self, client):
        await _seed(client)
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["db_stats"]["signals"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_data_management.py -v`
Expected: FAIL — 404 (routes don't exist yet)

- [ ] **Step 3: Add data management endpoints to signals.py**

Add to `signaldeck/api/routes/signals.py`, after existing endpoints:

```python
from signaldeck.api.server import get_db, get_config


@router.delete("/data/signals")
async def clear_signals():
    db = get_db()
    await db.clear_signals()
    return {"status": "cleared", "table": "signals"}


@router.delete("/data/activity")
async def clear_activity():
    db = get_db()
    await db.clear_activity()
    return {"status": "cleared", "table": "activity_log"}


@router.delete("/data/bookmarks")
async def clear_bookmarks():
    db = get_db()
    await db.clear_bookmarks()
    return {"status": "cleared", "table": "bookmarks"}


@router.delete("/data/recordings")
async def clear_recordings():
    db = get_db()
    await db.clear_recordings()
    # Also delete audio files
    config = get_config()
    rec_dir = Path(config.get("audio", {}).get("recording_dir", "data/recordings"))
    deleted_files = 0
    if rec_dir.exists():
        for f in rec_dir.glob("*.wav"):
            f.unlink()
            deleted_files += 1
    return {"status": "cleared", "table": "recordings", "files_deleted": deleted_files}


@router.delete("/data/all")
async def clear_all_data():
    db = get_db()
    await db.clear_all()
    config = get_config()
    rec_dir = Path(config.get("audio", {}).get("recording_dir", "data/recordings"))
    if rec_dir.exists():
        for f in rec_dir.glob("*.wav"):
            f.unlink()
    return {"status": "cleared", "table": "all"}
```

Add `from pathlib import Path` to the imports at the top of `signals.py` if not already present.

- [ ] **Step 4: Add status endpoint to scanner.py**

Add to `signaldeck/api/routes/scanner.py`, after the `scanner_stop` endpoint (line 51):

```python
from signaldeck.api.server import get_db


@router.get("/status")
async def get_status():
    """Return system status for the Status page."""
    from signaldeck.api.websocket.live_signals import _clients as ws_clients
    config = get_config()
    db = get_db()
    db_stats = await db.get_stats()
    return {
        "scanner": _scanner_state,
        "db_stats": db_stats,
        "ws_clients": len(ws_clients),
        "session_log": config.get("_session_log_file"),
        "start_time": config.get("_start_time"),
    }
```

Update the existing import line in scanner.py — `get_db` needs to be imported. The file already imports `from signaldeck.api.server import get_config`. Change to:

```python
from signaldeck.api.server import get_config, get_db
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api_data_management.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add signaldeck/api/routes/signals.py signaldeck/api/routes/scanner.py tests/test_api_data_management.py
git commit -m "feat: add data management DELETE endpoints and GET /api/status"
```

---

## Task 7: Extended Auth API Endpoints

**Files:**
- Modify: `signaldeck/api/routes/auth_routes.py`
- Create: `tests/test_auth_extended.py`

- [ ] **Step 1: Write tests for new auth endpoints**

```python
# tests/test_auth_extended.py
import pytest
from httpx import AsyncClient, ASGITransport
from signaldeck.api.server import create_app


@pytest.fixture
def app(tmp_path):
    config = {
        "storage": {"database_path": str(tmp_path / "test.db")},
        "audio": {"recording_dir": str(tmp_path / "recordings")},
        "scanner": {"squelch_offset": 10, "dwell_time_ms": 50, "fft_size": 1024,
                     "sweep_ranges": []},
        "devices": {"auto_discover": False, "gain": 40},
        "logging": {"level": "DEBUG"},
        "auth": {"enabled": True, "credentials_path": str(tmp_path / "creds.yaml")},
    }
    return create_app(config)


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _get_token(client):
    """Login and return the API token."""
    # Auth manager creates default admin credentials on first run
    from signaldeck.api.server import get_auth_manager
    mgr = get_auth_manager()
    # Use the initial password generated on first run
    password = mgr._initial_password
    resp = await client.post("/api/auth/login", json={
        "username": "admin", "password": password
    })
    return resp.json()["api_token"]


@pytest.mark.asyncio
class TestAuthExtended:
    async def test_get_token(self, client):
        token = await _get_token(client)
        resp = await client.get("/api/auth/token",
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["api_token"] == token

    async def test_get_token_unauthenticated(self, client):
        resp = await client.get("/api/auth/token")
        assert resp.status_code == 401

    async def test_regenerate_token(self, client):
        token = await _get_token(client)
        resp = await client.post("/api/auth/regenerate-token",
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        new_token = resp.json()["api_token"]
        assert new_token != token
        # Old token should no longer work
        resp2 = await client.get("/api/auth/token",
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp2.status_code == 401

    async def test_toggle_auth_off(self, client):
        token = await _get_token(client)
        resp = await client.post("/api/auth/toggle",
                                 json={"enabled": False},
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_toggle_auth_on(self, client):
        token = await _get_token(client)
        # Turn off first
        await client.post("/api/auth/toggle",
                          json={"enabled": False},
                          headers={"Authorization": f"Bearer {token}"})
        # Turn back on
        resp = await client.post("/api/auth/toggle",
                                 json={"enabled": True},
                                 headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth_extended.py -v`
Expected: FAIL — 404 or 405 (endpoints don't exist)

- [ ] **Step 3: Add new auth endpoints**

Add to `signaldeck/api/routes/auth_routes.py`, after the `change_password` endpoint:

```python
from signaldeck.api.auth import generate_api_token


class ToggleAuthRequest(BaseModel):
    enabled: bool


@router.get("/token")
async def get_token():
    """Return the current API token. Requires authentication."""
    mgr = get_auth_manager()
    if not mgr:
        raise HTTPException(status_code=404, detail="Auth not configured")
    return {"api_token": mgr.api_token}


@router.post("/regenerate-token")
async def regenerate_token():
    """Generate a new API token. Invalidates the old one."""
    mgr = get_auth_manager()
    if not mgr:
        raise HTTPException(status_code=404, detail="Auth not configured")
    mgr.api_token = generate_api_token()
    mgr._save()
    return {"api_token": mgr.api_token}


@router.post("/toggle")
async def toggle_auth(data: ToggleAuthRequest):
    """Enable or disable authentication."""
    from signaldeck.api.server import get_config, _state
    config = get_config()
    config.setdefault("auth", {})["enabled"] = data.enabled

    if data.enabled and "auth" not in _state:
        # Re-initialize auth manager
        from signaldeck.api.auth import AuthManager
        cred_path = config.get("auth", {}).get("credentials_path", "config/credentials.yaml")
        mgr = AuthManager(credentials_path=cred_path)
        mgr.initialize()
        _state["auth"] = mgr
    elif not data.enabled:
        _state.pop("auth", None)

    return {"enabled": data.enabled}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auth_extended.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/routes/auth_routes.py tests/test_auth_extended.py
git commit -m "feat: add auth toggle, token regeneration, and token retrieval endpoints"
```

---

## Task 8: Extend Settings API (Audio, Logging, Device Roles)

**Files:**
- Modify: `signaldeck/api/routes/scanner.py` (extend `SettingsUpdate` and `PUT /settings`, extend `_persist_user_config`)

- [ ] **Step 1: Extend the SettingsUpdate model**

In `signaldeck/api/routes/scanner.py`, replace the `SettingsUpdate` class (lines 75-81):

```python
class SettingsUpdate(BaseModel):
    gain: float | None = None
    squelch_offset: float | None = None
    min_signal_strength: float | None = None
    dwell_time_ms: float | None = None
    fft_size: int | None = None
    scan_ranges: list[ScanRangeUpdate] | None = None
    # Audio settings
    sample_rate: int | None = None
    recording_dir: str | None = None
    # Logging settings
    log_level: str | None = None
    # Device role settings
    scanner_device: str | None = None  # serial of SoapySDR device or "none"
    tuner_device: str | None = None    # host:port of gqrx instance or "none"
```

- [ ] **Step 2: Add handling for new fields in update_settings**

In the `update_settings` function (line 84), after the `scan_ranges` block (line 119), add:

```python
    if data.sample_rate is not None:
        config.setdefault("audio", {})["sample_rate"] = data.sample_rate
        changed.append(f"sample_rate={data.sample_rate}")

    if data.recording_dir is not None:
        config.setdefault("audio", {})["recording_dir"] = data.recording_dir
        changed.append(f"recording_dir={data.recording_dir}")

    if data.log_level is not None:
        config.setdefault("logging", {})["level"] = data.log_level
        # Update the root logger level live
        logging.getLogger().setLevel(getattr(logging, data.log_level.upper(), logging.INFO))
        changed.append(f"log_level={data.log_level}")

    if data.scanner_device is not None:
        config.setdefault("devices", {})["scanner_device"] = data.scanner_device
        changed.append(f"scanner_device={data.scanner_device}")

    if data.tuner_device is not None:
        config.setdefault("devices", {})["tuner_device"] = data.tuner_device
        changed.append(f"tuner_device={data.tuner_device}")
```

- [ ] **Step 3: Extend _persist_user_config to save new fields**

Replace the `_persist_user_config` function (lines 131-151):

```python
def _persist_user_config(config: dict) -> None:
    """Write the user-customizable settings to a YAML file."""
    user_cfg = {
        "devices": {
            "gain": config.get("devices", {}).get("gain", 40),
            "scanner_device": config.get("devices", {}).get("scanner_device"),
            "tuner_device": config.get("devices", {}).get("tuner_device"),
        },
        "scanner": {
            "squelch_offset": config["scanner"].get("squelch_offset", 10),
            "min_signal_strength": config["scanner"].get("min_signal_strength", -50),
            "dwell_time_ms": config["scanner"].get("dwell_time_ms", 50),
            "fft_size": config["scanner"].get("fft_size", 1024),
            "sweep_ranges": config["scanner"].get("sweep_ranges", []),
        },
        "audio": {
            "sample_rate": config.get("audio", {}).get("sample_rate", 48000),
            "recording_dir": config.get("audio", {}).get("recording_dir", "data/recordings"),
        },
        "logging": {
            "level": config.get("logging", {}).get("level", "INFO"),
        },
    }
    # Remove None values from devices
    user_cfg["devices"] = {k: v for k, v in user_cfg["devices"].items() if v is not None}
    try:
        _USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_USER_CONFIG_PATH, "w") as f:
            yaml.dump(user_cfg, f, default_flow_style=False, sort_keys=False)
        logger.info("Settings persisted to %s", _USER_CONFIG_PATH)
    except Exception as e:
        logger.error("Failed to persist settings: %s", e)
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/routes/scanner.py
git commit -m "feat: extend settings API with audio, logging, and device role fields"
```

---

## Task 9: Frontend — Status Page

**Files:**
- Modify: `signaldeck/web/index.html`
- Modify: `signaldeck/web/js/app.js`

This task splits the Settings section into Status + Settings, adds the Logs nav tab, and builds the Status page. The Settings page modifications and Logs page are in Tasks 10 and 11.

- [ ] **Step 1: Add new nav tabs**

In `signaldeck/web/index.html`, find the nav links section. Replace the single `Settings` nav link with three links: `Status`, `Settings`, `Logs`.

Find the Settings nav link (it will look like):
```html
<a ... @click.prevent="navigate('settings')" :class="...">Settings</a>
```

Replace with:
```html
            <a href="#status" @click.prevent="navigate('status')"
               :class="currentPage === 'status' ? 'nav-link active' : 'nav-link'">Status</a>
            <a href="#settings" @click.prevent="navigate('settings')"
               :class="currentPage === 'settings' ? 'nav-link active' : 'nav-link'">Settings</a>
            <a href="#logs" @click.prevent="navigate('logs')"
               :class="currentPage === 'logs' ? 'nav-link active' : 'nav-link'">Logs</a>
```

Do the same for the mobile menu nav links further down in the file.

- [ ] **Step 2: Add status page state to app.js**

In `signaldeck/web/js/app.js`, in the data model, after the `settings: {},` line (around line 74), add:

```javascript
    statusData: {},
```

- [ ] **Step 3: Add fetchStatusPage method to app.js**

Add a new method in the API calls section:

```javascript
    async fetchStatusPage() {
      try {
        const resp = await this.apiFetch('/api/status');
        if (resp.ok) this.statusData = await resp.json();
      } catch (e) { /* status page is non-critical */ }
      // Also fetch scanner status and settings for device info
      await this.fetchStatus();
    },
```

- [ ] **Step 4: Update navigate/fetchPageData for status page**

In the `fetchPageData()` method, add a case for `'status'`:

```javascript
      if (this.currentPage === 'status') {
        this.fetchStatusPage();
        this.fetchAnalytics();
      }
```

- [ ] **Step 5: Add Status page HTML**

In `signaldeck/web/index.html`, before the `<!-- ==================== SETTINGS ==================== -->` comment (line 389), add the Status page section:

```html
    <!-- ==================== STATUS ==================== -->
    <section x-show="currentPage === 'status'" x-cloak>
      <div class="page-header">
        <h1>Status</h1>
        <div class="header-controls">
          <button class="btn btn-primary" @click="fetchStatusPage()">Refresh</button>
        </div>
      </div>

      <div class="settings-grid">
        <!-- Scanner Status -->
        <div class="card">
          <div class="card-header">
            <h3>Scanner</h3>
            <span class="badge" :class="scannerStatus.status === 'running' ? 'badge-green' : 'badge-orange'"
                  x-text="scannerStatus.status === 'running' ? 'Active' : 'Idle'"></span>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Mode</span>
              <span class="setting-value" x-text="scannerStatus.mode || '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">Backend</span>
              <span class="setting-value" x-text="scannerStatus.backend || '--'"></span>
            </div>
          </div>
        </div>

        <!-- Connected Devices -->
        <div class="card">
          <div class="card-header">
            <h3>Connected Devices</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Active Devices</span>
              <span class="setting-value" x-text="scannerStatus.active_devices ?? '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">WebSocket Clients</span>
              <span class="setting-value" x-text="statusData.ws_clients ?? '--'"></span>
            </div>
          </div>
        </div>

        <!-- Database Stats -->
        <div class="card">
          <div class="card-header">
            <h3>Database</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Signals</span>
              <span class="setting-value" x-text="statusData.db_stats ? statusData.db_stats.signals : '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">Activity Entries</span>
              <span class="setting-value" x-text="statusData.db_stats ? statusData.db_stats.activity : '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">Bookmarks</span>
              <span class="setting-value" x-text="statusData.db_stats ? statusData.db_stats.bookmarks : '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">Database Size</span>
              <span class="setting-value" x-text="statusData.db_stats ? (statusData.db_stats.db_size / 1024).toFixed(1) + ' KB' : '--'"></span>
            </div>
          </div>
        </div>

        <!-- Session Info -->
        <div class="card">
          <div class="card-header">
            <h3>Session</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Log File</span>
              <span class="setting-value" style="font-size:0.85em"
                    x-text="statusData.session_log || '--'"></span>
            </div>
            <div class="setting-row">
              <span class="setting-label">Started</span>
              <span class="setting-value" x-text="statusData.start_time ? formatTime(statusData.start_time) : '--'"></span>
            </div>
            <div class="setting-row">
              <a href="#logs" @click.prevent="navigate('logs')" style="color:#58a6ff">View Logs &rarr;</a>
            </div>
          </div>
        </div>

        <!-- Analytics (moved from Settings) -->
        <div class="card">
          <div class="card-header">
            <h3>Signal Analytics</h3>
          </div>
          <canvas id="protocol-chart" width="400" height="200"></canvas>
        </div>

        <div class="card">
          <div class="card-header">
            <h3>Hourly Activity</h3>
          </div>
          <canvas id="activity-chart" width="400" height="200"></canvas>
        </div>
      </div>
    </section>

```

- [ ] **Step 6: Remove Scanner Status card and Analytics cards from Settings section**

In the Settings section of `index.html`, remove:
1. The "Scanner Status" card (the first card in settings-grid, lines ~401-413)
2. The "Signal Analytics" canvas card (lines ~529-535)
3. The "Hourly Activity" canvas card (lines ~537-542)

These are now on the Status page.

- [ ] **Step 7: Test manually by running the app**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS (frontend changes don't affect API tests)

- [ ] **Step 8: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "feat: add Status page with scanner, device, database, and session info"
```

---

## Task 10: Frontend — Enhanced Settings Page

**Files:**
- Modify: `signaldeck/web/index.html`
- Modify: `signaldeck/web/js/app.js`

- [ ] **Step 1: Make Audio settings editable**

In `index.html`, replace the read-only Audio card in the Settings section with editable controls:

```html
        <!-- Audio (editable) -->
        <div class="card">
          <div class="card-header">
            <h3>Audio</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <label class="setting-label" for="set-sample-rate">Sample Rate</label>
              <select id="set-sample-rate" class="form-select setting-input"
                      x-model.number="editSettings.sample_rate">
                <option value="22050">22050 Hz</option>
                <option value="44100">44100 Hz</option>
                <option value="48000">48000 Hz</option>
              </select>
            </div>
            <div class="setting-row">
              <label class="setting-label" for="set-rec-dir">Recording Directory</label>
              <input id="set-rec-dir" type="text" class="form-input setting-input"
                     x-model="editSettings.recording_dir">
            </div>
            <div class="setting-row">
              <span class="setting-label">Format</span>
              <span class="setting-value">WAV</span>
            </div>
          </div>
        </div>
```

- [ ] **Step 2: Add Device Roles card**

After the Scan Ranges card and before Audio, add:

```html
        <!-- Device Roles -->
        <div class="card">
          <div class="card-header">
            <h3>Device Roles</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <label class="setting-label" for="set-scanner-device">Scanner Device</label>
              <select id="set-scanner-device" class="form-select setting-input"
                      x-model="editSettings.scanner_device">
                <option value="none">None</option>
                <template x-for="d in (settings.devices ? (settings.devices.discovered || []) : [])" :key="d.serial">
                  <option :value="d.serial" x-text="d.label || d.serial"></option>
                </template>
              </select>
            </div>
            <div class="setting-row">
              <label class="setting-label" for="set-tuner-device">Tuner / Player (gqrx)</label>
              <select id="set-tuner-device" class="form-select setting-input"
                      x-model="editSettings.tuner_device">
                <option value="none">None</option>
                <template x-for="g in (settings.devices ? (settings.devices.gqrx_instances || []) : [])" :key="g.host + ':' + g.port">
                  <option :value="g.host + ':' + g.port" x-text="g.host + ':' + g.port"></option>
                </template>
              </select>
            </div>
          </div>
        </div>
```

- [ ] **Step 3: Add Logging settings card**

After the Audio card, add:

```html
        <!-- Logging -->
        <div class="card">
          <div class="card-header">
            <h3>Logging</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <label class="setting-label" for="set-log-level">Log Level</label>
              <select id="set-log-level" class="form-select setting-input"
                      x-model="editSettings.log_level">
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
          </div>
        </div>
```

- [ ] **Step 4: Enhance Authentication card with controls**

Replace the read-only Authentication card in Settings with:

```html
        <!-- Authentication -->
        <div class="card">
          <div class="card-header">
            <h3>Authentication</h3>
            <span class="badge" :class="settings.auth && settings.auth.enabled ? 'badge-green' : 'badge-orange'"
                  x-text="settings.auth && settings.auth.enabled ? 'Enabled' : 'Disabled'"></span>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Status</span>
              <button class="btn btn-small"
                      :class="settings.auth && settings.auth.enabled ? 'btn-danger' : 'btn-success'"
                      @click="toggleAuth()">
                <span x-text="settings.auth && settings.auth.enabled ? 'Disable Auth' : 'Enable Auth'"></span>
              </button>
            </div>
            <template x-if="settings.auth && settings.auth.enabled">
              <div>
                <div class="setting-row">
                  <span class="setting-label">API Token</span>
                  <div style="display:flex;gap:8px;align-items:center">
                    <code style="font-size:0.8em;background:#161b22;padding:4px 8px;border-radius:4px"
                          x-text="showApiToken ? (currentApiToken || '...') : '••••••••••••••••'"></code>
                    <button class="btn btn-small btn-primary" @click="showApiToken = !showApiToken; if(showApiToken) fetchApiToken()">
                      <span x-text="showApiToken ? 'Hide' : 'Show'"></span>
                    </button>
                    <button class="btn btn-small btn-primary" @click="copyApiToken()" x-show="showApiToken">Copy</button>
                  </div>
                </div>
                <div class="setting-row">
                  <span class="setting-label">Regenerate Token</span>
                  <button class="btn btn-small btn-danger" @click="if(confirm('Regenerate API token? All existing tokens will be invalidated.')) regenerateToken()">
                    Regenerate
                  </button>
                </div>
                <div class="setting-row" style="flex-direction:column;align-items:flex-start;gap:8px">
                  <span class="setting-label">Change Password</span>
                  <div style="display:flex;gap:8px;flex-wrap:wrap">
                    <input type="password" class="form-input" placeholder="Current password"
                           x-model="changePass.current" style="width:160px">
                    <input type="password" class="form-input" placeholder="New password"
                           x-model="changePass.newPass" style="width:160px">
                    <input type="password" class="form-input" placeholder="Confirm"
                           x-model="changePass.confirm" style="width:160px">
                    <button class="btn btn-small btn-success" @click="changePassword()">Change</button>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
```

- [ ] **Step 5: Add Data Management card**

After the Authentication card in Settings, replace the Storage card with:

```html
        <!-- Data Management -->
        <div class="card">
          <div class="card-header">
            <h3>Data Management</h3>
          </div>
          <div class="settings-list">
            <div class="setting-row">
              <span class="setting-label">Database</span>
              <span class="setting-value" style="font-size:0.85em"
                    x-text="settings.storage ? settings.storage.database_path : '--'"></span>
            </div>
            <div class="setting-row" style="flex-wrap:wrap;gap:8px">
              <button class="btn btn-small btn-danger" @click="clearData('signals')">Clear Signals</button>
              <button class="btn btn-small btn-danger" @click="clearData('activity')">Clear Activity</button>
              <button class="btn btn-small btn-danger" @click="clearData('bookmarks')">Clear Bookmarks</button>
              <button class="btn btn-small btn-danger" @click="clearData('recordings')">Clear Recordings</button>
              <button class="btn btn-small btn-danger" @click="deleteLogs()">Delete All Logs</button>
            </div>
            <div class="setting-row">
              <button class="btn btn-danger"
                      @click="if(confirm('Reset ALL data? This cannot be undone.')) clearData('all')">
                Reset All Data
              </button>
            </div>
          </div>
        </div>
```

- [ ] **Step 6: Add auth/data management state and methods to app.js**

In the data model section, add after the `loginError: '',` line:

```javascript
    showApiToken: false,
    currentApiToken: null,
    changePass: { current: '', newPass: '', confirm: '' },
```

Add `sample_rate`, `recording_dir`, and `log_level` to the `editSettings` defaults:

```javascript
    editSettings: {
      gain: 40,
      squelch_offset: 10,
      min_signal_strength: -50,
      dwell_time_ms: 50,
      fft_size: 1024,
      scan_ranges: [],
      sample_rate: 48000,
      recording_dir: 'data/recordings',
      log_level: 'INFO',
      scanner_device: 'none',
      tuner_device: 'none',
    },
```

- [ ] **Step 7: Add auth and data management methods to app.js**

Add these methods in the API calls section:

```javascript
    async toggleAuth() {
      const current = this.settings.auth && this.settings.auth.enabled;
      const action = current ? 'disable' : 'enable';
      if (!confirm(`${action.charAt(0).toUpperCase() + action.slice(1)} authentication?`)) return;
      try {
        const resp = await this.apiFetch('/api/auth/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !current }),
        });
        if (resp.ok) {
          this.showToast(`Authentication ${!current ? 'enabled' : 'disabled'}`, 'success');
          this.fetchStatus();
        }
      } catch (e) {
        this.showToast('Failed to toggle auth', 'error');
      }
    },

    async fetchApiToken() {
      try {
        const resp = await this.apiFetch('/api/auth/token');
        if (resp.ok) {
          const data = await resp.json();
          this.currentApiToken = data.api_token;
        }
      } catch (e) { /* ignore */ }
    },

    async copyApiToken() {
      if (this.currentApiToken) {
        await navigator.clipboard.writeText(this.currentApiToken);
        this.showToast('Token copied to clipboard', 'success');
      }
    },

    async regenerateToken() {
      try {
        const resp = await this.apiFetch('/api/auth/regenerate-token', { method: 'POST' });
        if (resp.ok) {
          const data = await resp.json();
          this.currentApiToken = data.api_token;
          this.apiToken = data.api_token;
          localStorage.setItem('signaldeck_token', data.api_token);
          this.showToast('API token regenerated', 'success');
        }
      } catch (e) {
        this.showToast('Failed to regenerate token', 'error');
      }
    },

    async changePassword() {
      if (this.changePass.newPass !== this.changePass.confirm) {
        this.showToast('Passwords do not match', 'error');
        return;
      }
      try {
        const resp = await this.apiFetch('/api/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: 'admin',
            current_password: this.changePass.current,
            new_password: this.changePass.newPass,
          }),
        });
        if (resp.ok) {
          this.showToast('Password changed', 'success');
          this.changePass = { current: '', newPass: '', confirm: '' };
        } else {
          this.showToast('Invalid current password', 'error');
        }
      } catch (e) {
        this.showToast('Failed to change password', 'error');
      }
    },

    async clearData(target) {
      if (!confirm(`Clear ${target}? This cannot be undone.`)) return;
      try {
        const resp = await this.apiFetch(`/api/data/${target}`, { method: 'DELETE' });
        if (resp.ok) {
          this.showToast(`${target} cleared`, 'success');
        }
      } catch (e) {
        this.showToast(`Failed to clear ${target}`, 'error');
      }
    },

    async deleteLogs() {
      if (!confirm('Delete all log files except the current session?')) return;
      try {
        const resp = await this.apiFetch('/api/logs', { method: 'DELETE' });
        if (resp.ok) {
          const data = await resp.json();
          this.showToast(`Deleted ${data.deleted} log file(s)`, 'success');
        }
      } catch (e) {
        this.showToast('Failed to delete logs', 'error');
      }
    },
```

- [ ] **Step 8: Update fetchStatus to populate new editSettings fields**

In the `fetchStatus()` method, where `editSettings` is populated from the response, add:

```javascript
      // After existing editSettings population
      if (this.settings.audio) {
        this.editSettings.sample_rate = this.settings.audio.sample_rate || 48000;
        this.editSettings.recording_dir = this.settings.audio.recording_dir || 'data/recordings';
      }
      if (this.settings.logging) {
        this.editSettings.log_level = this.settings.logging.level || 'INFO';
      }
```

- [ ] **Step 9: Update saveSettings to include new fields**

In the `saveSettings()` method, extend the payload to include:

```javascript
      const payload = {
        ...this.editSettings,
        log_level: this.editSettings.log_level,
        sample_rate: this.editSettings.sample_rate,
        recording_dir: this.editSettings.recording_dir,
      };
```

- [ ] **Step 10: Update GET /settings to return logging section**

In `signaldeck/api/routes/scanner.py`, in the `get_settings` endpoint, add `logging` to the response:

```python
        "logging": {
            "level": config.get("logging", {}).get("level", "INFO"),
        },
```

- [ ] **Step 11: Run tests**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS

- [ ] **Step 12: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js signaldeck/api/routes/scanner.py
git commit -m "feat: enhanced Settings page — editable audio, logging, auth controls, data management"
```

---

## Task 11: Frontend — Logs Viewer Page

**Files:**
- Modify: `signaldeck/web/index.html`
- Modify: `signaldeck/web/js/app.js`

- [ ] **Step 1: Add Logs page state to app.js**

In the data model, add:

```javascript
    // --- Logs ---
    logFiles: [],
    currentLog: { name: '', content: '' },
    logFilter: '',  // '' = all, 'INFO', 'WARNING', 'ERROR'
```

- [ ] **Step 2: Add log viewer methods to app.js**

```javascript
    async fetchLogFiles() {
      try {
        const resp = await this.apiFetch('/api/logs');
        if (resp.ok) this.logFiles = await resp.json();
      } catch (e) { /* ignore */ }
    },

    async fetchCurrentLog() {
      try {
        const resp = await this.apiFetch('/api/logs/current');
        if (resp.ok) this.currentLog = await resp.json();
      } catch (e) { /* ignore */ }
    },

    async selectLogFile(filename) {
      try {
        const resp = await this.apiFetch(`/api/logs/${filename}`);
        if (resp.ok) this.currentLog = await resp.json();
      } catch (e) {
        this.showToast('Failed to load log file', 'error');
      }
    },

    get filteredLogLines() {
      if (!this.currentLog.content) return [];
      const lines = this.currentLog.content.split('\n');
      if (!this.logFilter) return lines;
      const levels = { 'ERROR': 3, 'WARNING': 2, 'INFO': 1 };
      const minLevel = levels[this.logFilter] || 0;
      return lines.filter(line => {
        if (line.includes(' ERROR:')) return levels['ERROR'] >= minLevel;
        if (line.includes(' WARNING:')) return levels['WARNING'] >= minLevel;
        if (line.includes(' INFO:')) return levels['INFO'] >= minLevel;
        if (line.includes(' DEBUG:')) return 0 >= minLevel;
        return true;  // non-standard lines pass through
      });
    },
```

- [ ] **Step 3: Update fetchPageData for logs page**

In `fetchPageData()`, add:

```javascript
      if (this.currentPage === 'logs') {
        this.fetchLogFiles();
        this.fetchCurrentLog();
      }
```

- [ ] **Step 4: Add Logs page HTML**

In `index.html`, before the `</main>` closing tag, after the Settings section, add:

```html
    <!-- ==================== LOGS ==================== -->
    <section x-show="currentPage === 'logs'" x-cloak>
      <div class="page-header">
        <h1>Logs</h1>
        <div class="header-controls">
          <select class="form-select" style="width:auto" @change="selectLogFile($event.target.value)">
            <template x-for="f in logFiles" :key="f.name">
              <option :value="f.name" :selected="f.name === currentLog.name" x-text="f.name"></option>
            </template>
          </select>
          <button class="btn btn-primary" @click="fetchCurrentLog()">Refresh</button>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <h3 x-text="currentLog.name || 'No log loaded'"></h3>
          <div style="display:flex;gap:4px">
            <button class="btn btn-small" :class="logFilter === '' ? 'btn-primary' : ''" @click="logFilter = ''">All</button>
            <button class="btn btn-small" :class="logFilter === 'INFO' ? 'btn-primary' : ''" @click="logFilter = 'INFO'">INFO+</button>
            <button class="btn btn-small" :class="logFilter === 'WARNING' ? 'btn-primary' : ''" @click="logFilter = 'WARNING'">WARN+</button>
            <button class="btn btn-small" :class="logFilter === 'ERROR' ? 'btn-primary' : ''" @click="logFilter = 'ERROR'">ERROR</button>
          </div>
        </div>
        <pre style="max-height:600px;overflow-y:auto;padding:12px;margin:0;font-size:0.82em;line-height:1.5;background:#0d1117;color:#c9d1d9;white-space:pre-wrap;word-break:break-all"><template x-for="line in filteredLogLines" :key="$index"><span x-text="line + '\n'"
              :style="line.includes(' ERROR:') ? 'color:#f85149' : line.includes(' WARNING:') ? 'color:#d29922' : ''"></span></template></pre>
      </div>
    </section>

```

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v --ignore=tests/test_hardware.py`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "feat: add Logs viewer page with file selector and level filtering"
```

---

## Execution Notes

**Parallelization:** Tasks 1-2 (channelizer), Tasks 3-4 (logging), and Task 5 (database) are fully independent and can be dispatched as parallel subagents. Tasks 6-7 depend on Task 5. Tasks 9-11 (frontend) depend on Tasks 4, 6, 7, 8 being complete.

**Dependency graph:**
```
Task 1 → Task 2 (channelizer integration)
Task 3 (logging setup, standalone)
Task 4 depends on Task 3 (log API needs log_dir in config)
Task 5 (database methods, standalone)
Task 6 depends on Task 5 (data management API uses clear_*)
Task 7 (auth endpoints, standalone)
Task 8 (settings API extension, standalone)
Task 9 depends on Tasks 4, 6, 8 (Status page shows status data)
Task 10 depends on Tasks 7, 8 (Settings page uses auth + settings endpoints)
Task 11 depends on Task 4 (Logs page uses log API)
```

**Suggested parallel batches:**
1. Batch 1: Tasks 1, 3, 5, 7, 8 (all independent)
2. Batch 2: Tasks 2, 4, 6 (depend on batch 1)
3. Batch 3: Tasks 9, 10, 11 (frontend, all depend on batch 2 — combine into single subagent since they all modify index.html and app.js)

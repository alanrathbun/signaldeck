# Logging Fix + UI Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix silent scanning logs in gqrx-only mode and consolidate Signals/Activity pages into the Active Signals table on the Live dashboard.

**Architecture:** Two independent workstreams. (1) Add operational logging throughout the main loop, gqrx commands, signal broadcasts, and WebSocket connections. (2) Remove the Signals and Activity nav pages entirely, merge their unique columns (first_seen, confidence, decoder, result_type) into the Active Signals table by enriching live signals with periodic REST fetches to `/api/signals` and `/api/activity`. Extend the existing column picker and filter bar to cover all columns.

**Tech Stack:** Python asyncio, FastAPI, Alpine.js, localStorage

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `signaldeck/main.py` | Modify | Add periodic heartbeat log in gqrx-only mode, log gqrx tune at INFO |
| `signaldeck/engine/gqrx_client.py` | Modify | Log each command sent/received at DEBUG |
| `signaldeck/engine/gqrx_device.py` | Modify | Promote tune log from DEBUG to INFO |
| `signaldeck/api/websocket/live_signals.py` | Modify | Log broadcasts and client connect/disconnect |
| `signaldeck/web/js/app.js` | Modify | Remove signals/activity page state, add enrichment fetch, expand columns/filters |
| `signaldeck/web/index.html` | Modify | Remove Signals and Activity nav links + sections, add new columns to Active Signals table |
| `signaldeck/api/routes/signals.py` | Modify | Add `/api/signals/enrichment` endpoint returning keyed-by-frequency data |
| `tests/test_ws_signals.py` | Modify | Add test for broadcast logging |
| `tests/test_gqrx_client.py` | No change | Existing tests cover commands |
| `tests/test_api_signals.py` | Modify | Add test for enrichment endpoint |

---

## Task 1: Add Logging to Main Loop and gqrx Operations

**Files:**
- Modify: `signaldeck/main.py:278-301` (main loop)
- Modify: `signaldeck/engine/gqrx_client.py:51-65` (_send_command)
- Modify: `signaldeck/engine/gqrx_device.py:18-20` (tune method)
- Modify: `signaldeck/api/websocket/live_signals.py:30-52,55-67` (broadcast + ws handler)

- [ ] **Step 1: Add heartbeat logging in gqrx-only idle loop**

In `signaldeck/main.py`, add a counter and periodic log inside the `else` branch of the main loop (line 299-301):

```python
                else:
                    # gqrx-only mode: no scanning, just handle tuning
                    _idle_count = getattr(_handle_gqrx_tuning, '_idle_count', 0) + 1
                    if _idle_count % 20 == 1:  # every ~10 seconds (20 * 0.5s)
                        logger.info("gqrx-only mode: idle, waiting for dashboard input (%s client(s) connected)",
                                    len(_clients) if '_clients' in dir() else '?')
                    _handle_gqrx_tuning._idle_count = _idle_count
                    await asyncio.sleep(0.5)
```

Actually, simpler approach — use a module-level counter before the loop:

Replace lines 277-301 in `main.py`:
```python
        if scanner:
            logger.info("Starting sweep across %d range(s)...", len(ranges))
        else:
            logger.info("gqrx-only mode — use the dashboard to tune frequencies")
        idle_ticks = 0
        try:
            while True:
                # If gqrx is connected, handle tuning requests from the UI
                await _handle_gqrx_tuning()

                if scanner:
                    # If no gqrx, SoapySDR can do audio (pauses scanning)
                    if not gqrx_device and audio_request_fn:
                        audio_req = audio_request_fn()
                        if audio_req.get("active") and audio_req.get("frequency_hz"):
                            logger.info("Audio streaming: tuning to %.3f MHz",
                                        audio_req["frequency_hz"] / 1e6)
                            await _stream_audio(device, audio_req["frequency_hz"],
                                                audio_stream_fn, audio_request_fn,
                                                sample_rate=2_000_000)
                            logger.info("Audio streaming ended, resuming scan")
                            continue

                    # SoapySDR handles scanning
                    signals = await scanner.sweep_once(fft_callback=on_fft)
                    if signals:
                        await on_signals(signals)
                else:
                    # gqrx-only mode: no scanning, just handle tuning
                    idle_ticks += 1
                    if idle_ticks % 20 == 1:  # every ~10s
                        logger.info("Idle — dashboard ready, %s gqrx %s",
                                    "gqrx connected" if gqrx_device else "no gqrx",
                                    "(tuned to %.3f MHz)" % (_gqrx_tuned_freq / 1e6) if _gqrx_tuned_freq else "(idle)")
                    await asyncio.sleep(0.5)
```

- [ ] **Step 2: Add DEBUG logging to gqrx_client._send_command**

In `signaldeck/engine/gqrx_client.py`, add logging inside `_send_command` (line 51-65):

```python
    async def _send_command(self, cmd: str) -> str:
        if not self.is_connected:
            raise GqrxConnectionError("Not connected to gqrx")
        try:
            logger.debug("gqrx >> %s", cmd)
            self._writer.write(f"{cmd}\n".encode())
            await self._writer.drain()
            line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self.timeout,
            )
            resp = line.decode().strip()
            logger.debug("gqrx << %s", resp)
            return resp
        except (OSError, asyncio.TimeoutError) as e:
            self._writer = None
            self._reader = None
            raise GqrxConnectionError(f"Command '{cmd}' failed: {e}") from e
```

- [ ] **Step 3: Promote gqrx_device.tune log to INFO**

In `signaldeck/engine/gqrx_device.py` line 20, change `logger.debug` to `logger.info`:

```python
    async def tune(self, frequency_hz: float) -> None:
        await self._client.set_frequency(int(frequency_hz))
        logger.info("gqrx tuned to %.3f MHz", frequency_hz / 1e6)
```

- [ ] **Step 4: Add logging to live_signals.py broadcast and WebSocket handler**

In `signaldeck/api/websocket/live_signals.py`:

Add logging to `broadcast()` after the throttle check passes (after line 39):
```python
    logger.debug("Broadcasting signal %.3f MHz to %d client(s)", 
                 message.get("frequency_mhz", 0), len(_clients))
```

Add logging to `ws_signals()`:
```python
@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    logger.info("WebSocket client connected (%d total)", len(_clients))
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(_clients))
```

- [ ] **Step 5: Run tests to verify nothing broke**

Run: `pytest tests/ -x -q`
Expected: All 237 tests pass (logging changes are additive, no behavior change).

- [ ] **Step 6: Commit**

```bash
git add signaldeck/main.py signaldeck/engine/gqrx_client.py signaldeck/engine/gqrx_device.py signaldeck/api/websocket/live_signals.py
git commit -m "fix: add operational logging to main loop, gqrx commands, and WebSocket"
```

---

## Task 2: Add Signal Enrichment API Endpoint

The Active Signals table currently only has real-time WebSocket fields (frequency, bandwidth, power, modulation, protocol). To show database fields (first_seen, hit_count, confidence) and activity data (decoder, result_type), we need an endpoint that returns this data keyed by frequency so the frontend can merge it.

**Files:**
- Modify: `signaldeck/api/routes/signals.py`
- Modify: `tests/test_api_signals.py`

- [ ] **Step 1: Write the failing test for enrichment endpoint**

Add to `tests/test_api_signals.py`:

```python
async def test_enrichment_endpoint(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    sig_id = await db.upsert_signal(Signal(frequency=162_550_000.0, bandwidth=12500.0, modulation="FM",
        protocol="NOAA", first_seen=now, last_seen=now, hit_count=5, avg_strength=-45.0, confidence=0.8))
    await db.insert_activity(ActivityEntry(signal_id=sig_id, timestamp=now, duration=2.0, strength=-45.0,
        decoder_used="noaa", result_type="weather", summary="NOAA weather broadcast"))
    resp = await client.get("/api/signals/enrichment")
    assert resp.status_code == 200
    data = resp.json()
    # Keyed by frequency in Hz as string
    key = "162550000"
    assert key in data
    assert data[key]["first_seen"] is not None
    assert data[key]["hit_count"] == 5
    assert data[key]["confidence"] == 0.8
    assert data[key]["last_activity"]["decoder"] == "noaa"
    assert data[key]["last_activity"]["type"] == "weather"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_signals.py::test_enrichment_endpoint -v`
Expected: FAIL with 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Implement the enrichment endpoint**

Add to `signaldeck/api/routes/signals.py`:

```python
@router.get("/signals/enrichment")
async def signal_enrichment():
    """Return database signal data keyed by frequency (Hz) for frontend enrichment."""
    db = get_db()
    signals = await db.get_all_signals()
    activity = await db.get_recent_activity(limit=500)

    # Build activity lookup: signal_id -> most recent activity entry
    activity_by_signal: dict[int, dict] = {}
    for e in activity:
        if e.signal_id not in activity_by_signal:
            activity_by_signal[e.signal_id] = {
                "decoder": e.decoder_used,
                "type": e.result_type,
                "summary": e.summary,
                "timestamp": e.timestamp.isoformat(),
            }

    result = {}
    for s in signals:
        freq_key = str(int(s.frequency))
        entry = {
            "first_seen": s.first_seen.isoformat(),
            "last_seen": s.last_seen.isoformat(),
            "hit_count": s.hit_count,
            "confidence": s.confidence,
        }
        if s.id and s.id in activity_by_signal:
            entry["last_activity"] = activity_by_signal[s.id]
        else:
            entry["last_activity"] = None
        result[freq_key] = entry
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_signals.py::test_enrichment_endpoint -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add signaldeck/api/routes/signals.py tests/test_api_signals.py
git commit -m "feat: add /api/signals/enrichment endpoint for frontend data merge"
```

---

## Task 3: Remove Signals and Activity Nav Pages from HTML

**Files:**
- Modify: `signaldeck/web/index.html`

- [ ] **Step 1: Remove Signals and Activity nav links**

In `index.html`, remove lines 44-51 (the `<a>` tags for Signals and Activity in the nav):

```html
      <a href="#" :class="{ active: currentPage === 'signals' }" @click.prevent="navigate('signals')">
        <svg ...>...</svg>
        Signals
      </a>
      <a href="#" :class="{ active: currentPage === 'activity' }" @click.prevent="navigate('activity')">
        <svg ...>...</svg>
        Activity
      </a>
```

Remove these two `<a>` elements entirely.

- [ ] **Step 2: Remove the Signals section**

Remove the entire `<!-- ==================== SIGNALS ==================== -->` section (lines 235-298 in original).

- [ ] **Step 3: Remove the Activity section**

Remove the entire `<!-- ==================== ACTIVITY ==================== -->` section (lines 300-348 in original).

- [ ] **Step 4: Verify the app loads in a browser**

Run the app and confirm the Live, Recordings, Bookmarks, Map, Settings pages still work. The hash routes `#signals` and `#activity` should silently fall through to Live.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/web/index.html
git commit -m "refactor: remove redundant Signals and Activity pages from dashboard"
```

---

## Task 4: Expand Active Signals Table with All Columns

**Files:**
- Modify: `signaldeck/web/index.html` (Active Signals table headers + cells)
- Modify: `signaldeck/web/js/app.js` (column definitions, enrichment state, filters)

- [ ] **Step 1: Update allLiveColumns in app.js**

Replace the `allLiveColumns` array (lines 32-41) with the consolidated column set:

```javascript
    allLiveColumns: [
      { key: 'frequency', label: 'Frequency' },
      { key: 'bandwidth', label: 'Bandwidth' },
      { key: 'power', label: 'Power' },
      { key: 'modulation', label: 'Modulation' },
      { key: 'protocol', label: 'Protocol' },
      { key: 'hits', label: 'Hits' },
      { key: 'last_seen', label: 'Last Seen' },
      { key: 'first_seen', label: 'First Seen' },
      { key: 'confidence', label: 'Confidence' },
      { key: 'decoder', label: 'Decoder' },
      { key: 'activity_type', label: 'Activity Type' },
      { key: 'activity_summary', label: 'Last Activity' },
    ],
```

- [ ] **Step 2: Add enrichment state and fetch logic to app.js**

Add these properties to the dashboard object (after `liveSignals: [],` around line 21):

```javascript
    signalEnrichment: {},
    _enrichmentTimer: null,
```

Add an enrichment fetch method (after `clearLiveFilters` method):

```javascript
    async fetchEnrichment() {
      const data = await this.apiFetch('/api/signals/enrichment');
      if (data) this.signalEnrichment = data;
    },
```

Start periodic enrichment in `init()` after `this.fetchStatus();` (around line 140):

```javascript
      // Periodic enrichment sync for database fields
      this.fetchEnrichment();
      this._enrichmentTimer = setInterval(() => this.fetchEnrichment(), 10000);
```

- [ ] **Step 3: Add enriched signal getter**

Add a computed getter that merges live signals with enrichment data. Replace `sortedLiveSignals` getter to use enriched data:

```javascript
    get enrichedLiveSignals() {
      return this.filteredLiveSignals.map(sig => {
        const freqKey = String(Math.round(sig.frequency || 0));
        const enrich = this.signalEnrichment[freqKey] || {};
        const activity = enrich.last_activity || {};
        return {
          ...sig,
          first_seen: enrich.first_seen || null,
          db_hits: enrich.hit_count || 0,
          confidence: enrich.confidence || 0,
          decoder: activity.decoder || null,
          activity_type: activity.type || null,
          activity_summary: activity.summary || null,
        };
      });
    },

    get sortedLiveSignals() {
      const key = this.liveSortKey;
      const asc = this.liveSortAsc;
      return [...this.enrichedLiveSignals].sort((a, b) => {
        let va = a[key], vb = b[key];
        if (key === 'hits') { va = a._hits || 1; vb = b._hits || 1; }
        if (typeof va === 'string') va = (va || '').toLowerCase();
        if (typeof vb === 'string') vb = (vb || '').toLowerCase();
        if (va == null) va = '';
        if (vb == null) vb = '';
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
      });
    },
```

- [ ] **Step 4: Add new column headers and cells to index.html Active Signals table**

After the existing `<th>` for `summary` (which we'll remove) and before the Actions `<th>`, add:

```html
                <th x-show="liveVisibleCols.includes('first_seen')" @click="sortLive('first_seen')" class="sortable-th">
                  First Seen <span x-text="liveSortIcon('first_seen')"></span></th>
                <th x-show="liveVisibleCols.includes('confidence')" @click="sortLive('confidence')" class="sortable-th">
                  Confidence <span x-text="liveSortIcon('confidence')"></span></th>
                <th x-show="liveVisibleCols.includes('decoder')" @click="sortLive('decoder')" class="sortable-th">
                  Decoder <span x-text="liveSortIcon('decoder')"></span></th>
                <th x-show="liveVisibleCols.includes('activity_type')" @click="sortLive('activity_type')" class="sortable-th">
                  Activity <span x-text="liveSortIcon('activity_type')"></span></th>
                <th x-show="liveVisibleCols.includes('activity_summary')">Last Activity</th>
```

Remove the old `summary` column header. Then in the `<template x-for>` row body, remove the summary `<td>` and add:

```html
                  <td x-show="liveVisibleCols.includes('first_seen')" x-text="sig.first_seen ? formatTime(sig.first_seen) : '--'"></td>
                  <td x-show="liveVisibleCols.includes('confidence')" x-text="sig.confidence ? (sig.confidence * 100).toFixed(0) + '%' : '--'"></td>
                  <td x-show="liveVisibleCols.includes('decoder')"><span class="badge badge-blue" x-show="sig.decoder" x-text="sig.decoder"></span><span x-show="!sig.decoder">--</span></td>
                  <td x-show="liveVisibleCols.includes('activity_type')" x-text="sig.activity_type || '--'"></td>
                  <td x-show="liveVisibleCols.includes('activity_summary')" class="summary-cell" x-text="sig.activity_summary || '--'"></td>
```

- [ ] **Step 5: Add new filter options**

Add filter state variables to dashboard object (after existing filter vars around line 26):

```javascript
    liveFilterDecoder: '',
    liveFilterBandwidthMin: null,
    liveFilterBandwidthMax: null,
```

Update `filteredLiveSignals` getter to include new filters:

```javascript
    get filteredLiveSignals() {
      return this.liveSignals.filter(s => {
        if (this.liveFilterMod && s.modulation !== this.liveFilterMod) return false;
        if (this.liveFilterProto && s.protocol !== this.liveFilterProto) return false;
        if (this.liveFilterMinPower && s.power < this.liveFilterMinPower) return false;
        if (this.liveFilterFreq) {
          const mhz = (s.frequency || 0) / 1e6;
          const f = this.liveFilterFreq.trim();
          if (f.includes('-')) {
            const [lo, hi] = f.split('-').map(Number);
            if (mhz < lo || mhz > hi) return false;
          } else {
            if (!mhz.toFixed(3).includes(f)) return false;
          }
        }
        if (this.liveFilterDecoder) {
          const freqKey = String(Math.round(s.frequency || 0));
          const enrich = this.signalEnrichment[freqKey] || {};
          const activity = enrich.last_activity || {};
          if ((activity.decoder || '') !== this.liveFilterDecoder) return false;
        }
        if (this.liveFilterBandwidthMin && (s.bandwidth || 0) < this.liveFilterBandwidthMin) return false;
        if (this.liveFilterBandwidthMax && (s.bandwidth || 0) > this.liveFilterBandwidthMax) return false;
        return true;
      });
    },
```

Add a `liveDecoders` getter:

```javascript
    get liveDecoders() {
      const decoders = new Set();
      for (const s of this.liveSignals) {
        const freqKey = String(Math.round(s.frequency || 0));
        const enrich = this.signalEnrichment[freqKey] || {};
        const decoder = (enrich.last_activity || {}).decoder;
        if (decoder) decoders.add(decoder);
      }
      return [...decoders].sort();
    },
```

Update `clearLiveFilters`:

```javascript
    clearLiveFilters() {
      this.liveFilterMod = '';
      this.liveFilterProto = '';
      this.liveFilterMinPower = null;
      this.liveFilterFreq = '';
      this.liveFilterDecoder = '';
      this.liveFilterBandwidthMin = null;
      this.liveFilterBandwidthMax = null;
    },
```

- [ ] **Step 6: Add filter UI elements to index.html**

In the filter bar (after the existing frequency filter input, before the Clear button), add:

```html
          <select class="form-select filter-select" x-model="liveFilterDecoder" title="Filter by decoder">
            <option value="">All Decoders</option>
            <template x-for="dec in liveDecoders" :key="dec">
              <option :value="dec" x-text="dec"></option>
            </template>
          </select>
          <input type="number" class="form-input filter-select" x-model.number="liveFilterBandwidthMin"
                 placeholder="BW min Hz" title="Minimum bandwidth (Hz)" style="width:100px">
          <input type="number" class="form-input filter-select" x-model.number="liveFilterBandwidthMax"
                 placeholder="BW max Hz" title="Maximum bandwidth (Hz)" style="width:100px">
```

Update the Clear button's `x-show` to include new filter vars:

```html
          <button class="btn btn-small" @click="clearLiveFilters()"
            x-show="liveFilterMod || liveFilterProto || liveFilterMinPower || liveFilterFreq || liveFilterDecoder || liveFilterBandwidthMin || liveFilterBandwidthMax">Clear</button>
```

- [ ] **Step 7: Clean up removed page references in app.js**

Remove from the dashboard object:
- `signals: [],` and `signalSortKey`, `signalSortAsc` properties
- `activity: [],`, `activityLimit`, `activityAutoRefresh`, `activityRefreshTimer` properties
- `fetchSignals()` method
- `fetchActivity()` method
- `toggleActivityRefresh()` method
- `sortSignals()` method
- `sortedSignals` getter
- `sortIcon()` method
- Remove `'signals'` and `'activity'` from the hash route list in `init()` and from `fetchPageData()` switch

Update `init()` hash check (line 116):
```javascript
      if (hash && ['live', 'recordings', 'bookmarks', 'map', 'settings'].includes(hash)) {
```

Update `fetchPageData()`:
```javascript
    fetchPageData() {
      switch (this.currentPage) {
        case 'recordings': this.fetchRecordings(); break;
        case 'bookmarks': this.fetchBookmarks(); break;
        case 'settings': this.fetchStatus(); break;
      }
    },
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass. (Frontend changes don't break backend tests.)

- [ ] **Step 9: Manual verification**

Open `http://localhost:8080` in browser. Verify:
- Only Live, Recordings, Bookmarks, Map, Settings tabs in nav
- Active Signals table shows new columns in column picker
- New filter dropdowns work
- Column visibility persists after page reload

- [ ] **Step 10: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "feat: consolidate Signals and Activity pages into Active Signals table

Removes separate Signals and Activity nav pages. All columns (first_seen,
confidence, decoder, activity type/summary) now available in the Active
Signals table via column picker. Adds decoder and bandwidth filters.
Database fields enriched via periodic /api/signals/enrichment fetch."
```

---

## Task 5: Final Cleanup and Verification

**Files:**
- Modify: `signaldeck/web/index.html` (if any dead references remain)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Start the app and verify logging**

Run: `python -m signaldeck start`
Expected output should include periodic heartbeat messages like:
```
12:00:01 [signaldeck] INFO: gqrx-only mode — use the dashboard to tune frequencies
12:00:11 [signaldeck] INFO: Idle — dashboard ready, gqrx connected (idle)
12:00:21 [signaldeck] INFO: Idle — dashboard ready, gqrx connected (idle)
```

When tuning via dashboard:
```
12:01:05 [signaldeck.engine.gqrx_device] INFO: gqrx tuned to 162.550 MHz
```

WebSocket connections:
```
12:01:00 [signaldeck.api.websocket.live_signals] INFO: WebSocket client connected (1 total)
```

- [ ] **Step 3: Verify consolidated dashboard**

Open browser, confirm:
- No Signals or Activity tabs
- Column picker has 11 columns (frequency, bandwidth, power, modulation, protocol, hits, last_seen, first_seen, confidence, decoder, activity_type, activity_summary)
- Decoder filter dropdown appears when decoder data exists
- Bandwidth min/max filters work
- All columns sortable

- [ ] **Step 4: Commit if any final fixes needed, then push**

```bash
git push origin feature/gqrx-backend
```

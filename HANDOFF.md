# SignalDeck Handoff — Remaining Work & Context

## What This Project Is

SignalDeck is an SDR scanner/decoder platform at `~/signaldeck`. It scans radio frequencies with a HackRF One, classifies signals, decodes them with 11 protocol decoders, and serves a web dashboard. GitHub: https://github.com/alanrathbun/signaldeck

## Current State

- **60 commits**, all on `master`, pushed to GitHub
- **218 tests** (214 unit + 4 hardware integration), all passing
- **Venv** at `~/signaldeck/venv` (created with `--system-site-packages` for SoapySDR)
- **HackRF One** is physically connected and working
- **External tools installed**: multimon-ng, rtl_433, dump1090-mutability, acarsdec, dsd-fme, OP25

## What Was Built (Plans 1-6, all complete)

| Plan | Status | What |
|------|--------|------|
| 1. Core | Done | Device manager, FFT scanner, audio pipeline, SQLite, CLI |
| 2. Decoders | Done | 7 decoders via apt (FM/AM, RDS, Weather, ISM, POCSAG, APRS, ADS-B) |
| 2b. Source Decoders | Done | 4 decoders built from source (ACARS, DSD-FME, P25, NOAA APT) |
| 3. Dashboard | Done | FastAPI server, 3 WebSocket endpoints, 7-page Alpine.js SPA |
| 4. AI | Done | CNN modulation classifier, audio classifier, anomaly detector, LLM summarizer, training pipeline |
| 5. Learning | Done | Pattern tracker (7x24 matrix), priority scorer, bookmark monitor |
| 6. Security | Done | Auth middleware, bcrypt credentials, login page, Nginx/Tailscale scripts |

## What Works

- `signaldeck start` launches scanner + web dashboard on port 8080
- Scanner sweeps configured frequency ranges, detects signals via FFT power
- Signal classifier identifies modulation/protocol (FM, AM, broadcast_fm, aviation, ism, weather_radio, narrowband_fm, etc.)
- Signals appear in real-time on the Live page via WebSocket
- Activity log shows detected signals with frequency, classifier results, power
- Signals page shows accumulated signal database (sorted by hit count)
- Bookmarks CRUD works (add/delete via API and dashboard)
- Settings page shows and allows editing gain, squelch, FFT size, scan ranges
- Waterfall/spectrogram canvas renders live FFT data
- Map page loads with Leaflet/OpenStreetMap (ready for ADS-B/APRS positions)

## Known Issues & What Needs Fixing

### Audio Streaming (partially working)
- **What was done**: Added `_stream_audio()` in `main.py` that tunes HackRF to a frequency, captures 0.5s IQ, FM demodulates, sends PCM via WebSocket. Frontend `AudioPlayer` class in `audio.js` uses Web Audio API ScriptProcessorNode to play PCM.
- **What's broken**: User reported no audio heard when clicking Listen. Likely causes:
  1. The scanner loop may not yield to the audio capture often enough (it runs `sweep_once` which can take seconds)
  2. ScriptProcessorNode in `audio.js` may have buffer underrun issues — it expects continuous PCM but gets intermittent 0.5s chunks
  3. The `_stream_audio` function calls `device.start_stream()` / `device.stop_stream()` which may conflict with `sweep_once()` also using the same device stream
  4. Web Audio API requires user gesture to start AudioContext on modern browsers — may need a click-to-unlock
- **How to debug**: Open browser console, check for errors when clicking Listen. Add `console.log` in `audio.js` `onmessage` to see if PCM bytes arrive. Check terminal for `_stream_audio` being called.
- **Better approach**: Instead of interleaving audio in the sweep loop, use a separate mode: when user clicks Listen, **pause the sweep** and dedicate the SDR to that frequency for continuous demod+streaming. Resume sweep when user clicks Stop. This is how real scanners work.

### Decoders Not Connected to Live Scanning
- The 11 decoder plugins are built and tested, but the scanner's `on_signals` callback only classifies signals — it never actually runs a decoder on them.
- **What needs to happen**: When the classifier identifies a signal (e.g., `protocol_hint="ism"`), the scanner should route it to the decoder registry, call `decoder.decode()`, and log the decoded results to the database.
- The decoder registry (`signaldeck/decoders/all.py`) and classifier (`signaldeck/engine/classifier.py`) are ready. Just need to wire them together in `main.py`'s `on_signals` callback.
- For subprocess decoders (rtl_433, multimon-ng, dump1090), this means capturing a chunk of IQ or audio data and feeding it to the decoder.

### ADS-B and ACARS Need Dedicated SDR
- ADS-B (dump1090) and ACARS (acarsdec) need a dedicated RTL-SDR parked on their frequencies — they can't share the HackRF that's sweeping.
- User is purchasing an RTL-SDR V5 but it may not have arrived yet.
- The `AdsbDecoder.start_monitoring()` and `AcarsDecoder.start_monitoring()` methods exist and will launch the subprocess with its own RTL-SDR.
- **What needs doing**: Add multi-device support to `main.py` — detect if an RTL-SDR is connected, and if so, start ADS-B monitoring on it while the HackRF sweeps.

### Dashboard Polish Items
- Activity page frequency column sometimes shows `--` for old entries (before classifier was added)
- Recordings page is empty (no decoder is actually recording audio yet)
- Map page has no data flowing to it (ADS-B not connected)
- Analytics charts on Settings page may not render (need data from `/api/analytics/summary` which returns minimal data)

### Things That Were Never Started
These were mentioned in the design spec but no plan was written:
- **Trunked system following** (OP25 can do this but needs configuration per system)
- **RDS 57 kHz subcarrier DSP pipeline** (RDS parser exists but the RF extraction from broadcast FM needs GNU Radio flowgraph)
- **NOAA APT live satellite pass scheduling** (satellites likely decommissioned anyway)

## Key Architecture Decisions

- **Single SDR constraint**: HackRF can only tune to one frequency at a time. The scanner time-slices across ranges. Audio listening requires pausing the sweep.
- **Subprocess decoders**: rtl_433, multimon-ng, dump1090, acarsdec, dsd-fme, OP25 are all external binaries managed by `ProcessSupervisor` (`signaldeck/decoders/supervisor.py`).
- **Database sharing**: `main.py` creates the Database instance and passes it to `create_app(cfg, shared_db=db)` so scanner and API share one connection. SQLite WAL mode enabled.
- **Alpine.js SPA**: No build step. CDN for Alpine.js and Leaflet. All JS in `signaldeck/web/js/`.

## Bugs Fixed During Development (Don't Reintroduce)

1. **SoapySDR returns `SoapySDRKwargs`** objects, not plain dicts — must wrap with `dict()` before `.get()`
2. **SoapySDR `readStream()` returns `StreamResult`** with `.ret` attribute, not a plain int/tuple
3. **Audio devices show up in SoapySDR enumerate** — filter out `driver="audio"` before selecting SDR
4. **`fftshift` is required** in `compute_power_spectrum` for correct frequency mapping in `find_signals_in_spectrum`
5. **Alpine.js `init()` must be `async`** if it uses `await`
6. **`_clients -= disconnected`** in WebSocket broadcast requires `global _clients` declaration
7. **Two Database instances** caused API to not see scanner's data — fixed by sharing via `create_app(cfg, shared_db=db)`

## File Layout

```
~/signaldeck/
├── signaldeck/
│   ├── main.py              # CLI + scanner loop + audio streaming
│   ├── config.py            # YAML config with deep merge
│   ├── engine/              # device_manager, scanner, classifier, audio_pipeline, bookmark_monitor
│   ├── decoders/            # base, registry, supervisor, 11 decoder plugins, all.py factory
│   ├── ai/                  # modulation_cnn, audio_classifier, anomaly_detector, summarizer, training
│   ├── learning/            # pattern_tracker, priority_scorer
│   ├── storage/             # database.py (SQLite), models.py (dataclasses)
│   ├── api/                 # server.py (FastAPI), routes/, websocket/, auth.py
│   └── web/                 # index.html, css/, js/ (app.js, waterfall.js, audio.js, map.js, charts.js)
├── config/default.yaml
├── scripts/                 # install_decoders.sh, setup_nginx.sh, setup_tailscale.sh
├── tests/                   # 218 tests
├── docs/superpowers/        # Design spec and all 6 implementation plans (at ~/docs/)
├── pyproject.toml
├── README.md
└── LICENSE                  # GPL v3
```

## Design Spec & Plans

All at `~/docs/superpowers/`:
- `specs/2026-04-02-signaldeck-design.md` — full design document
- `plans/2026-04-02-signaldeck-plan1-core.md` through `plans/2026-04-03-signaldeck-plan6-security.md`

## How to Run

```bash
cd ~/signaldeck
source venv/bin/activate
signaldeck start          # scanner + web dashboard on :8080
signaldeck start --headless  # CLI only
pytest tests/ -v -m "not hardware"   # run tests
```

## Priority Order for Remaining Work

1. **Fix audio streaming** — this is the user's top request. Pause sweep when listening, continuous demod+stream.
2. **Connect decoders to scanner** — when a signal is classified, route to the appropriate decoder and log decoded results.
3. **Multi-device support** — detect RTL-SDR, start ADS-B monitoring, feed positions to map.
4. **Dashboard polish** — recordings page, analytics charts, map integration.
5. **Activity log cleanup** — clear old "unknown" entries, or re-classify them.

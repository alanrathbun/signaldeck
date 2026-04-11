# Logging, Settings Overhaul & Frequency Channelization — Design Spec

## Goal

Three changes: (1) Move log output from console to session log files with a dashboard viewer, (2) split Status from Settings into separate pages with more controls exposed, (3) snap detected signals to standard channel frequencies per FCC/ITU band allocations.

## 1. Logging Overhaul

### Console Output

Only WARNING and above go to console (stderr). INFO/DEBUG messages go to log file only. This eliminates the heartbeat spam, tuning events, and WebSocket connection messages from the terminal while preserving them in the log.

### Log Files

- Stored in `data/logs/`
- New file per app start: `signaldeck-2026-04-03T14-30-00.log`
- Full INFO-level output (or DEBUG if configured)
- Format: `HH:MM:SS [logger_name] LEVEL: message` (same as current)

### Log Viewer

A dedicated "Logs" page in the nav, linked from the Status page.

- Displays current session log with auto-scroll
- Dropdown to select and view previous session logs
- Level filter buttons (INFO / WARNING / ERROR) to show/hide by severity
- Basic text display, monospace

### Log API

- `GET /api/logs` — list available log files (name, size, created timestamp)
- `GET /api/logs/current` — return contents of the current session log file
- `GET /api/logs/{filename}` — return contents of a specific log file

### Log Management

- "Delete All Logs" button on Settings page removes all files in `data/logs/` except the current session log
- `DELETE /api/logs` — backend endpoint for log cleanup

## 2. Separate Status and Settings Pages

Replace the single "Settings" nav tab with two tabs: "Status" and "Settings".

### Status Page (read-only)

- **Scanner**: mode (sweep/bookmarks/smart), backend (SoapySDR/gqrx/both), active/idle badge
- **Connected devices**: detected SoapySDR devices (label, driver, serial) and gqrx instances (host:port)
- **WebSocket clients**: current count
- **Database stats**: signal count, activity entry count, bookmark count, database file size
- **Current session log**: file path + "View Logs" link navigating to the Logs page
- **Uptime**: time since app start
- **Signal Analytics**: protocol distribution chart (moved from current Settings page)
- **Hourly Activity**: activity timeline chart (moved from current Settings page)

### Settings Page (editable controls)

**SDR & Scanner** (existing, kept as-is):
- Gain (dB), Squelch Offset, Min Signal Strength, Dwell Time, FFT Size
- Scan Ranges (add/remove with label, start MHz, end MHz)

**Device Roles** (new):
- **Scanner device**: dropdown of all detected SoapySDR devices (by label/serial) + "None"
- **Tuner/Player**: dropdown of all detected gqrx instances (by host:port) + "None"
- Persisted to `user_settings.yaml` as `devices.scanner_device` (serial) and `devices.tuner_device` (host:port)
- Applied on next scan cycle

**Audio** (currently read-only, make editable):
- Sample rate (dropdown: 22050, 44100, 48000 Hz)
- Recording directory (text input)
- Audio format (dropdown: wav) — only wav for now, but expose the control

**Authentication** (new UI):
- Enable/disable toggle
- Change password form (old password + new password + confirm)
- Regenerate API token button (with confirmation dialog)
- Show current API token (masked by default, click to reveal, click to copy)

**Logging** (new):
- Log level dropdown (DEBUG / INFO / WARNING / ERROR)
- Persisted to `user_settings.yaml`

**Data Management** (new):
- Individual clear buttons: Clear Signals, Clear Activity Log, Clear Bookmarks, Clear Recordings
- Reset All Data button (with "Are you sure?" confirmation dialog)
- Delete All Logs button
- Database path display + file size

### Settings API Additions

- `PUT /api/settings` — extend existing endpoint to accept audio, logging, and device role fields
- `POST /api/auth/toggle` — enable/disable auth
- `POST /api/auth/regenerate-token` — generate new API token, return it
- `GET /api/auth/token` — return current API token (requires auth)
- `DELETE /api/data/signals` — clear signals table
- `DELETE /api/data/activity` — clear activity_log table
- `DELETE /api/data/bookmarks` — clear bookmarks table
- `DELETE /api/data/recordings` — clear recordings table + delete audio files
- `DELETE /api/data/all` — clear all tables + delete audio files
- `DELETE /api/logs` — delete all log files except current session
- `GET /api/status` — return status page data (devices, stats, uptime, client count)

### Database Additions

Add methods to `Database`:
- `clear_signals()` — DELETE FROM signals
- `clear_activity()` — DELETE FROM activity_log
- `clear_bookmarks()` — DELETE FROM bookmarks
- `clear_recordings()` — DELETE FROM recordings
- `clear_all()` — clear all four tables
- `get_stats()` — return counts for each table + file size

## 3. Frequency Channelization

### Channel Spacing Table

Hardcoded lookup based on FCC/ITU standards. More specific ranges override broader bands. Checked most-specific first.

| Priority | Band | Frequency Range | Step | Source |
|----------|------|----------------|------|--------|
| 1 | NOAA Weather | 162.400 - 162.550 MHz | 25 kHz | FCC Part 95 |
| 2 | Marine VHF | 156.000 - 162.000 MHz | 25 kHz | ITU-R M.1084, FCC Part 80 |
| 3 | ISM 433 | 433.050 - 434.790 MHz | 25 kHz | ETSI EN 300 220 |
| 4 | GMRS/FRS | 462.000 - 467.000 MHz | 12.5 kHz | FCC Part 95 |
| 5 | VHF Low | 30 - 88 MHz | 20 kHz | FCC Part 90 |
| 6 | FM Broadcast | 88 - 108 MHz | 200 kHz | FCC Part 73 |
| 7 | Airband | 118 - 137 MHz | 25 kHz | FCC Part 87 |
| 8 | 2m Ham | 144 - 148 MHz | 5 kHz | ARRL Band Plan |
| 9 | VHF High | 150 - 174 MHz | 12.5 kHz | FCC Part 90 (narrowband) |
| 10 | 70cm Ham | 420 - 450 MHz | 5 kHz | ARRL Band Plan |
| 11 | UHF Land Mobile | 450 - 470 MHz | 12.5 kHz | FCC Part 90 (narrowband) |

Frequencies outside all defined ranges pass through unmodified.

### Implementation

New file: `signaldeck/engine/channelizer.py`

Pure function: `channelize(frequency_hz: float) -> float`
- Iterates the table (specific ranges first)
- Snaps to nearest multiple of the step size
- Returns the snapped frequency

Called in `main.py` `on_signals()` callback — snap `sig.frequency_hz` before classification, storage, and broadcast. This ensures:
- Database stores channelized frequencies
- WebSocket broadcasts channelized frequencies
- Enrichment endpoint key matching works (same integer Hz)
- Active Signals table naturally deduplicates per channel

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `signaldeck/main.py` | Modify | Dual-handler logging setup (file + console), channelizer call in on_signals |
| `signaldeck/engine/channelizer.py` | Create | Channel spacing table + `channelize()` function |
| `signaldeck/api/routes/scanner.py` | Modify | Extend PUT /api/settings, add GET /api/status |
| `signaldeck/api/routes/signals.py` | Modify | Add DELETE endpoints for data management |
| `signaldeck/api/routes/auth_routes.py` | Modify | Add toggle, regenerate-token, get-token endpoints |
| `signaldeck/api/routes/logs.py` | Create | Log file listing/viewing/deletion endpoints |
| `signaldeck/storage/database.py` | Modify | Add clear_* and get_stats methods |
| `signaldeck/web/index.html` | Modify | Split Status/Settings, add Logs page, add new controls |
| `signaldeck/web/js/app.js` | Modify | Status/Settings/Logs page state, data management actions, device role dropdowns |
| `signaldeck/config.py` | Modify | Support new settings fields in user_settings.yaml |
| `config/default.yaml` | Modify | Add log_dir, device role defaults |
| `tests/test_channelizer.py` | Create | Channel snapping tests |
| `tests/test_api_logs.py` | Create | Log API tests |
| `tests/test_api_data_management.py` | Create | Data clear/reset endpoint tests |

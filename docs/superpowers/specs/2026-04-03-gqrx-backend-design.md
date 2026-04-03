# gqrx Backend Design

**Date:** 2026-04-03
**Branch:** `feature/gqrx-backend`
**Status:** Approved

## Overview

Add gqrx as an alternative SDR backend. SignalDeck controls gqrx via its rigctl TCP protocol (port 7356, hamlib-compatible). gqrx handles hardware, demodulation, and audio output. SignalDeck handles scanning logic, signal tracking, classification, and the web dashboard.

This lets users leverage gqrx's mature SDR stack (with its own waterfall, filters, and audio pipeline) while getting SignalDeck's automated scanning, signal database, and web UI on top.

## Constraints

- gqrx's rigctl protocol does NOT expose raw IQ samples or FFT data
- Signal strength is available only as a single dBFS reading per command (`l STRENGTH`)
- Audio stays in gqrx — no web dashboard audio streaming in gqrx mode
- All commands are text-based over TCP, one response per command

## New Files

### `signaldeck/engine/gqrx_client.py` — Rigctl TCP Client

Low-level async TCP client for the rigctl protocol. Manages a persistent connection to gqrx.

**Interface:**

```python
class GqrxClient:
    def __init__(self, host: str = "localhost", port: int = 7356, timeout: float = 2.0)

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def is_connected(self) -> bool

    # Frequency
    async def set_frequency(self, freq_hz: int) -> None       # F <freq>
    async def get_frequency(self) -> int                       # f

    # Demodulator
    async def set_mode(self, mode: str, passband: int = 0) -> None  # M <mode> <passband>
    async def get_mode(self) -> tuple[str, int]                      # m

    # Signal level
    async def get_signal_strength(self) -> float               # l STRENGTH (returns dBFS)

    # Squelch
    async def set_squelch(self, level_dbfs: float) -> None     # L SQL <level>
    async def get_squelch(self) -> float                       # l SQL

    # Audio gain
    async def set_audio_gain(self, gain_db: float) -> None     # L AF <gain>

    # Recording
    async def start_recording(self) -> None                    # U RECORD 1
    async def stop_recording(self) -> None                     # U RECORD 0

    # Low-level
    async def _send_command(self, cmd: str) -> str             # Send line, read response
```

**Protocol details:**
- Commands are newline-terminated ASCII
- Responses: numeric values on their own line, errors return `RPRT 1`
- `get_mode()` returns two lines (mode string, then passband int)
- Connection kept alive between commands; reconnect on failure
- 2-second timeout per command

### `signaldeck/engine/gqrx_device.py` — gqrx Device Adapter

Wraps `GqrxClient` to present a device-like interface compatible with SignalDeck's scanner.

```python
class GqrxDevice:
    def __init__(self, client: GqrxClient, info: DeviceInfo)

    # Scanner-compatible interface
    def tune(self, frequency_hz: float) -> None
    def set_gain(self, gain_db: float) -> None           # no-op (gqrx manages gain)
    def set_sample_rate(self, rate: float) -> None       # no-op
    def start_stream(self) -> None                       # no-op
    def stop_stream(self) -> None                        # no-op
    def read_samples(self, num_samples: int) -> None     # returns None (no IQ access)
    def close(self) -> None                              # disconnects TCP

    # gqrx-specific methods
    async def get_signal_strength(self) -> float
    async def set_mode(self, mode: str) -> None
    async def set_squelch(self, level: float) -> None
    async def start_recording(self) -> None
    async def stop_recording(self) -> None

    @property
    def is_gqrx(self) -> bool                            # returns True
```

The no-op methods allow `GqrxDevice` to be passed where `SDRDevice` is expected without crashing. Code that needs gqrx-specific features checks `is_gqrx` or uses `isinstance`.

## Modified Files

### `signaldeck/engine/device_manager.py` — Discovery and Connection

**Changes to `DeviceManager.enumerate()`:**
After SoapySDR discovery, if `gqrx_auto_detect` is true (default), attempt TCP connection to `localhost:7356`. If gqrx responds to `f` (get frequency), add it as:
```python
DeviceInfo(label="gqrx @ localhost:7356", driver="gqrx", serial="localhost:7356")
```

Also check any instances listed in `devices.gqrx_instances` config.

**Changes to `DeviceManager.open()`:**
If `driver == "gqrx"`, parse `serial` as `host:port`, create `GqrxClient`, connect, and return `GqrxDevice`.

### `signaldeck/engine/scanner.py` — Strength-Based Scanning

**New method: `strength_sweep_once(fft_callback=None)`**

For gqrx mode where IQ samples aren't available:

1. Iterate through scan ranges, stepping by `step_hz`
2. At each frequency: `device.tune(freq)` then `device.get_signal_strength()`
3. Collect strength readings into an array
4. After each range, build a coarse power spectrum from the collected readings
5. If `fft_callback` is provided, broadcast the power array (waterfall gets coarser data but same JSON format)
6. Detect signals: any reading above `noise_floor + squelch_offset` becomes a `DetectedSignal`
7. Return signal list

The coarse waterfall will have one bin per frequency step (vs 1024 bins per FFT in SoapySDR mode), but the frontend renders it the same way.

**New method: `bookmark_scan_once(bookmarks, fft_callback=None)`**

For bookmark-based scanning:

1. Cycle through a list of bookmark frequencies
2. At each: tune, read strength, check against threshold
3. If active (above threshold), yield a `DetectedSignal`
4. Optionally broadcast per-bookmark strength to waterfall
5. Return signal list

### `signaldeck/main.py` — Main Loop

**Changes to `_run()`:**

After device discovery and open:

```python
is_gqrx = isinstance(device, GqrxDevice)
```

In the main loop:
- If `is_gqrx`: call `scanner.strength_sweep_once(fft_callback=on_fft)` instead of `sweep_once()`
- Skip `_stream_audio()` entirely — gqrx handles audio, so the audio request check is skipped
- Everything else (on_signals, database, WebSocket broadcast) stays identical

### `signaldeck/config.py` — Config Loading

No changes needed. The new config keys fall under `devices:` which is already loaded.

### `config/default.yaml` — Default Configuration

Add:
```yaml
devices:
  gqrx_auto_detect: true
  gqrx_instances: []
  # Example:
  # gqrx_instances:
  #   - host: "192.168.1.50"
  #     port: 7356
```

## Data Flow

### Sweep Mode (gqrx)
```
main loop
  -> scanner.strength_sweep_once()
    -> for each freq in range:
      -> device.tune(freq)              # sends "F <freq>\n" over TCP
      -> device.get_signal_strength()   # sends "l STRENGTH\n", reads dBFS
      -> collect into power array
    -> fft_callback(center_freq, sample_rate, power_array)  # waterfall
    -> threshold detection -> DetectedSignal list
  -> on_signals(signals)                # classify, store, broadcast (unchanged)
```

### Bookmark Mode (gqrx)
```
main loop
  -> scanner.bookmark_scan_once(bookmarks)
    -> for each bookmark:
      -> device.tune(bookmark.frequency)
      -> device.get_signal_strength()
      -> if strength > threshold: yield DetectedSignal
  -> on_signals(signals)
```

### SoapySDR Mode (unchanged)
```
main loop
  -> scanner.sweep_once()
    -> for each freq:
      -> device.tune(freq)
      -> device.read_samples()          # raw IQ
      -> compute_power_spectrum()       # FFT
      -> fft_callback()                 # waterfall
      -> find_signals_in_spectrum()     # peak detection
  -> on_signals(signals)
```

## What Stays the Same

- Web dashboard (all 7 pages)
- Database schema and storage
- Signal classification
- Decoder registry (decoders still receive signal info, even if triggered differently)
- All API endpoints and WebSocket endpoints
- Settings persistence
- Waterfall frontend rendering (receives same JSON format, just coarser data)
- Live signals broadcast and throttling

## Out of Scope

- Audio streaming through web dashboard in gqrx mode (gqrx owns audio)
- Raw IQ access via gqrx (protocol doesn't support it)
- Controlling gqrx DSP settings beyond mode/squelch/gain
- Multiple simultaneous gqrx instances in a single scan loop (future work)
- gqrx UDP audio capture (future enhancement)

## Testing

- `GqrxClient`: unit tests with a mock TCP server that speaks rigctl
- `GqrxDevice`: unit tests verifying command translation and no-op methods
- `strength_sweep_once`: unit tests with a mock device returning known strength values
- `bookmark_scan_once`: unit tests with mock bookmarks and thresholds
- `DeviceManager.enumerate`: test that gqrx auto-detect adds device when available, skips gracefully when not
- Integration: manual test with real gqrx instance (marked `@pytest.mark.hardware`)

# SignalDeck

An SDR (Software Defined Radio) scanning, signal classification, and decoding platform with a web dashboard. SignalDeck automatically discovers active radio transmissions, identifies their type, decodes them into human-readable formats, and learns activity patterns over time.

Built for the HackRF One and RTL-SDR, with support for multiple simultaneous SDR devices.

## Features

- **Automatic frequency scanning** with FFT-based signal detection and configurable sweep ranges
- **11 protocol decoders** covering analog voice, digital voice, data, aircraft tracking, and more
- **AI-powered signal analysis** with CNN modulation classification, audio content detection, and anomaly flagging
- **Web dashboard** accessible from any browser (desktop and mobile) with live waterfall display, signal map, and audio streaming
- **Smart scanning** that learns which frequencies are active at what times and prioritizes accordingly
- **Remote access** via Tailscale VPN or Nginx reverse proxy with HTTPS
- **Audio recording** with in-browser playback and file management

## Supported Protocols

| Protocol | Tool | What It Decodes |
|----------|------|-----------------|
| FM/AM Voice | Native | Analog radio, aviation, weather radio |
| RDS | Native | FM station names, genre, radio text |
| Weather Radio (SAME) | Native | NOAA weather alerts with event parsing |
| ISM Sensors | rtl_433 | 433/915 MHz wireless sensors (weather stations, tire pressure, etc.) |
| POCSAG/FLEX | multimon-ng | Pager messages |
| APRS | multimon-ng | Amateur radio position reports, weather, messages |
| ADS-B | dump1090 | Aircraft positions, callsigns, altitude, speed |
| ACARS | acarsdec | Aircraft text messages |
| DMR | DSD-FME | Digital mobile radio voice and data |
| D-STAR | DSD-FME | Amateur digital voice with callsign routing |
| NXDN | DSD-FME | Narrowband digital voice |
| P25 | OP25 | Public safety digital voice, trunked systems |
| NOAA APT | aptdec | Weather satellite imagery |

## Hardware

**Required:**
- HackRF One (or any SoapySDR-compatible SDR)

**Recommended additions:**
- RTL-SDR Blog V4/V5 for dedicated monitoring (e.g., park on ADS-B 1090 MHz while HackRF sweeps)
- Appropriate antennas for your frequency ranges of interest

## Quick Start

### Prerequisites

- Ubuntu 22.04+ (tested on 24.04)
- Python 3.12+
- GNU Radio 3.10+
- SoapySDR with HackRF module

```bash
# System packages
sudo apt install -y python3.12-venv python3-soapysdr \
    hackrf gnuradio gqrx-sdr gr-osmosdr soapysdr-tools \
    soapysdr0.8-module-hackrf sox ffmpeg

# Decoder tools (available via apt)
sudo apt install -y multimon-ng rtl-433 dump1090-mutability
```

### Installation

```bash
git clone https://github.com/alanrathbun/signaldeck.git
cd signaldeck

# Create virtual environment (needs system-site-packages for SoapySDR)
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Install SignalDeck
pip install -e ".[dev]"

# Verify your SDR is detected
signaldeck devices
```

### Optional: Build-from-Source Decoders

For P25, DMR/D-STAR/NXDN, ACARS, and NOAA APT decoding:

```bash
./scripts/install_decoders.sh
```

This builds and installs [OP25](https://github.com/boatbod/op25), [DSD-FME](https://github.com/lwvmobile/dsd-fme), [acarsdec](https://github.com/f00b4r0/acarsdec), and [aptdec](https://github.com/Xerbo/aptdec) from source.

### Run

```bash
# Start with web dashboard
signaldeck start

# Dashboard available at http://localhost:8080

# Start without web dashboard (CLI only)
signaldeck start --headless

# Custom port/host
signaldeck start --port 9090 --host 0.0.0.0
```

## CLI Reference

```bash
signaldeck --version              # Show version
signaldeck devices                # List connected SDR devices
signaldeck status                 # Show known signals and recent activity
signaldeck start                  # Start scanner + web dashboard
signaldeck start --headless       # Scanner only, no web
signaldeck scan sweep             # Single sweep across all configured ranges
signaldeck scan sweep 88-108M     # Sweep a specific range
signaldeck bookmark list          # List frequency bookmarks
signaldeck bookmark add 162.400M --label "NOAA Weather" --decoder weather --priority 5
```

## Web Dashboard

The dashboard provides seven pages accessible from any browser:

- **Live View** -- Real-time waterfall spectrogram, active signal list, audio streaming, scanner controls
- **Signals** -- Sortable table of all discovered signals with frequency, modulation, protocol, hit count
- **Activity** -- Searchable activity log with timestamps and decoded summaries
- **Recordings** -- Audio file browser with in-browser playback
- **Bookmarks** -- Manage monitored frequencies with priority levels
- **Map** -- Live aircraft (ADS-B) and APRS station positions on OpenStreetMap
- **Settings** -- Device info, scan configuration, system status

The dashboard is responsive and works on mobile devices for remote monitoring.

## Architecture

```
                        ┌──────────────────────┐
                        │    Web Dashboard     │
                        │  (Alpine.js + Canvas)│
                        └──────────┬───────────┘
                                   │ REST + WebSocket
                        ┌──────────┴───────────┐
                        │   FastAPI Server     │
                        │  (API + Auth + WS)   │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────┴──────────┐ ┌──────┴───────┐ ┌──────────┴─────────┐
    │   Scanner Engine   │ │   Decoder    │ │   AI Analyzer      │
    │ Device Mgr, FFT,   │ │   Registry   │ │ CNN, Audio Class., │
    │ Sweep, Bookmarks   │ │ 11 Protocols │ │ Anomaly, LLM      │
    └─────────┬──────────┘ └──────────────┘ └────────────────────┘
              │
    ┌─────────┴──────────┐
    │  Learning Engine   │
    │ Patterns, Priority │
    │ Smart Scheduling   │
    └─────────┬──────────┘
              │
    ┌─────────┴──────────┐
    │   SQLite Storage   │
    │ Signals, Activity, │
    │ Bookmarks, Patterns│
    └────────────────────┘
```

### Key Components

- **Scanner Engine** -- SoapySDR device abstraction, FFT power sweep, multi-device allocation, bookmark monitoring
- **Signal Classifier** -- Rule-based frequency/bandwidth classification augmented by CNN modulation detection
- **Decoder Registry** -- Plugin system where each decoder implements `can_decode()` (confidence routing) and `decode()` (async generator)
- **Process Supervisor** -- Manages subprocess-based decoders (rtl_433, multimon-ng, dump1090, etc.) with lifecycle management and output parsing
- **AI Signal Analyzer** -- Modulation CNN (PyTorch), audio content classifier (MFCC), statistical anomaly detector, LLM activity summarizer
- **Learning Engine** -- 7x24 activity matrix per signal, priority scorer (`score = priority*3 + likelihood*2 + recency + novelty`)
- **Web Dashboard** -- FastAPI + WebSocket for live data/audio/waterfall, Alpine.js SPA with Leaflet maps

## Configuration

The default configuration is in `config/default.yaml`. Create a custom config to override:

```yaml
# my_config.yaml
devices:
  gain: 50  # increase gain

scanner:
  squelch_offset: 15  # increase squelch threshold
  sweep_ranges:
    - label: "My Local Repeaters"
      start_mhz: 440
      end_mhz: 450

auth:
  enabled: true  # enable authentication
```

```bash
signaldeck start --config my_config.yaml
```

### Authentication

Authentication is disabled by default. To enable:

1. Set `auth.enabled: true` in your config
2. Restart SignalDeck
3. On first run, an admin password and API token are generated and printed to the console
4. Credentials are saved to `config/credentials.yaml` (file permissions set to 0600)
5. Log in via the web dashboard or use the API token for programmatic access:

```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" http://localhost:8080/api/signals
```

## Remote Access

### Tailscale (Recommended)

The easiest way to access SignalDeck remotely with zero port forwarding:

```bash
./scripts/setup_tailscale.sh
```

Then access from any device on your Tailnet at `http://TAILSCALE_IP:8080`.

### Nginx + HTTPS

For traditional reverse proxy with optional Let's Encrypt HTTPS:

```bash
# HTTP only
./scripts/setup_nginx.sh

# With HTTPS (requires a domain pointing to your server)
./scripts/setup_nginx.sh --domain sdr.example.com --https
```

## API Reference

All endpoints are under `/api/`. When auth is enabled, include `Authorization: Bearer TOKEN` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check (always public) |
| GET | `/api/signals` | List all discovered signals |
| GET | `/api/activity?limit=50` | Recent activity log |
| GET | `/api/bookmarks` | List bookmarks |
| POST | `/api/bookmarks` | Create bookmark |
| DELETE | `/api/bookmarks/{id}` | Delete bookmark |
| GET | `/api/recordings` | List audio recordings |
| GET | `/api/analytics/summary` | Signal statistics |
| GET | `/api/scanner/status` | Scanner state |
| POST | `/api/auth/login` | Login (returns tokens) |
| POST | `/api/auth/change-password` | Change password |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws/signals` | Real-time signal detection feed (JSON) |
| `/ws/waterfall` | FFT data for spectrogram display (JSON) |
| `/ws/audio` | Live audio streaming (binary PCM, subscribe by frequency) |

## AI Features

### Modulation Classifier
Small CNN trained on spectrograms to identify modulation type (FM, AM, 4FSK, GMSK, OOK, etc.). Falls back to envelope/frequency heuristics when untrained. Self-trains from decoder-confirmed signals over time.

### Audio Content Classifier
MFCC-based classifier that quickly determines if demodulated audio contains human speech, digital data, noise, music, or tones. Saves CPU by skipping expensive decoders on noise.

### Anomaly Detector
Maintains per-band statistical profiles (power distribution, typical modulation, bandwidth). Flags signals that deviate significantly -- new transmitters, unusual power levels, unexpected modulation types.

### Activity Summarizer
Connects to a local LLM (via OpenAI-compatible API, e.g., llama.cpp server) to generate human-readable summaries: "In the last 6 hours: 47 aircraft tracked, 3 weather alerts, P25 talkgroup 1001 had 45 minutes of voice activity." Falls back to formatted text when no LLM is available.

## Smart Scanning

SignalDeck learns from observation:

1. **Discovery sweep** finds active signals across configured frequency ranges
2. **Pattern tracker** builds a 7-day x 24-hour activity matrix per signal
3. **Priority scorer** ranks frequencies: `score = (bookmark_priority * 3) + (activity_likelihood * 2) + recency_bonus + novelty_bonus`
4. **Smart mode** allocates scan time proportionally to score, checking likely-active frequencies first

New/unclassified signals get a temporary novelty bonus for extra attention.

## Project Structure

```
signaldeck/
├── signaldeck/
│   ├── main.py                # CLI entry point
│   ├── config.py              # YAML config loading
│   ├── engine/                # Scanner, device manager, audio pipeline
│   ├── decoders/              # 11 decoder plugins + registry + supervisor
│   ├── ai/                    # CNN, audio classifier, anomaly, LLM, training
│   ├── learning/              # Pattern tracker, priority scorer
│   ├── storage/               # SQLite database, models
│   ├── api/                   # FastAPI server, routes, WebSocket, auth
│   └── web/                   # Dashboard HTML/CSS/JS
├── config/
│   └── default.yaml           # Default configuration
├── scripts/
│   ├── install_decoders.sh    # Build P25/DMR/ACARS/APT decoders
│   ├── setup_nginx.sh         # Nginx reverse proxy
│   └── setup_tailscale.sh     # Tailscale VPN
├── tests/                     # 214 tests
├── pyproject.toml
├── LICENSE                    # GPL v3
└── README.md
```

## Development

```bash
# Run tests
pytest tests/ -v

# Run tests without hardware
pytest tests/ -v -m "not hardware"

# Run hardware integration tests (requires connected SDR)
pytest tests/test_integration.py -v -m hardware
```

## Contributing

Contributions are welcome! Areas that could use help:

- Additional decoder plugins (TETRA, M17, YSF, EDACS)
- RDS 57 kHz subcarrier DSP pipeline (currently parses RDS data but needs the RF extraction)
- Improved AI training data and model accuracy
- Dashboard UI enhancements
- Mobile app or PWA wrapper
- Documentation and tutorials

Please open an issue to discuss major changes before submitting a PR.

## Legal Notice

This software is designed for lawful radio monitoring and reception. Users are responsible for complying with all applicable laws regarding radio reception in their jurisdiction. In the United States, the Electronic Communications Privacy Act (18 U.S.C. 2511) permits the reception of radio communications that are not encrypted and are transmitted over frequencies allocated for general public use. Some signals (e.g., cellular, cordless phones) are illegal to intentionally receive in certain jurisdictions.

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.

## Acknowledgments

SignalDeck builds on these excellent open-source projects:

- [GNU Radio](https://www.gnuradio.org/) -- Signal processing framework
- [SoapySDR](https://github.com/pothosware/SoapySDR) -- Hardware abstraction
- [rtl_433](https://github.com/merbanan/rtl_433) -- ISM band decoder
- [multimon-ng](https://github.com/EliasOeworking/multimon-ng) -- POCSAG/APRS decoder
- [dump1090](https://github.com/mutability/dump1090) -- ADS-B decoder
- [OP25](https://github.com/boatbod/op25) -- P25 decoder
- [DSD-FME](https://github.com/lwvmobile/dsd-fme) -- DMR/D-STAR/NXDN decoder
- [acarsdec](https://github.com/f00b4r0/acarsdec) -- ACARS decoder
- [aptdec](https://github.com/Xerbo/aptdec) -- NOAA APT decoder
- [Alpine.js](https://alpinejs.dev/) -- Lightweight JS framework
- [Leaflet](https://leafletjs.com/) -- Interactive maps

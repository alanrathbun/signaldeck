import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import click

from signaldeck import __version__
from signaldeck.config import load_config
from signaldeck.engine.channelizer import channelize
from signaldeck.engine.ism_workflow import capture_iq_burst, summarize_burst_triage, triage_ism_burst
from signaldeck.engine.scan_presets import resolve_sweep_ranges


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


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """SignalDeck — SDR scanner, classifier, and decoder platform."""


async def _stream_audio(device, frequency_hz: float, send_fn, audio_request_fn,
                        sample_rate: float = 2_000_000,
                        chunk_duration_s: float = 0.1,
                        fft_callback=None,
                        rds_callback=None) -> None:
    """Tune to a frequency and continuously stream demodulated FM audio.

    Also computes FFT for the waterfall display and runs RDS decoding
    on the sustained IQ stream.  Keeps streaming until the audio request
    becomes inactive.
    """
    import numpy as np
    from signaldeck.engine.audio_pipeline import fm_demodulate
    from signaldeck.engine.scanner import compute_power_spectrum

    num_samples = int(sample_rate * chunk_duration_s)
    device.tune(frequency_hz)
    await asyncio.sleep(0.01)  # settle time

    device.start_stream()
    try:
        while True:
            # Check if still requested
            req = audio_request_fn()
            if not req.get("active") or req.get("frequency_hz") != frequency_hz:
                break

            samples = device.read_samples(num_samples)
            if samples is None or len(samples) < 1000:
                await asyncio.sleep(0.01)
                continue

            # Compute FFT for waterfall (use first 1024 samples)
            if fft_callback is not None and len(samples) >= 1024:
                power_db = compute_power_spectrum(samples[:1024], fft_size=1024)
                await fft_callback(frequency_hz, sample_rate, power_db)

            # Run RDS on the full IQ chunk (FM broadcast band only)
            if rds_callback is not None and 87_500_000 <= frequency_hz <= 108_000_000:
                await rds_callback(frequency_hz, samples)

            # FM demodulate to 48 kHz audio
            audio = fm_demodulate(samples, sample_rate=sample_rate, audio_rate=48000)

            # Convert to 16-bit PCM bytes
            pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            await send_fn(frequency_hz, pcm16.tobytes())

            # Yield to event loop
            await asyncio.sleep(0)
    finally:
        device.stop_stream()


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to config YAML file")
@click.option("--headless", is_flag=True, help="Start without web dashboard")
@click.option("--host", default="0.0.0.0", help="Web dashboard host")
@click.option("--port", default=8080, type=int, help="Web dashboard port")
def start(config_path: str | None, headless: bool, host: str, port: int) -> None:
    """Start the SignalDeck engine."""
    cfg = load_config(config_path)
    log_dir = cfg["logging"].get("log_dir", "data/logs")
    log_file = setup_logging(cfg["logging"]["level"], log_dir)
    cfg["_session_log_file"] = str(log_file)
    cfg["_start_time"] = datetime.now(timezone.utc).isoformat()
    logger = logging.getLogger("signaldeck")

    logger.info("SignalDeck v%s starting...", __version__)

    from signaldeck.engine.device_manager import DeviceManager
    from signaldeck.engine.gqrx_device import GqrxDevice
    from signaldeck.engine.gqrx_launcher import ensure_gqrx_running
    from signaldeck.engine.scanner import FrequencyScanner, ScanRange
    from signaldeck.storage.database import Database

    async def _run() -> None:
        # Initialize database
        db_path = cfg["storage"]["database_path"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = Database(db_path)
        await db.initialize()
        logger.info("Database initialized at %s", db_path)

        # Start web dashboard (unless headless)
        web_task = None
        if not headless:
            from signaldeck.api.server import create_app
            import uvicorn
            app = create_app(cfg, shared_db=db)
            uvi_config = uvicorn.Config(app, host=host, port=port, log_level="warning")
            server = uvicorn.Server(uvi_config)
            web_task = asyncio.create_task(server.serve())
            logger.info("Web dashboard at http://%s:%d", host, port)

        # Discover devices
        mgr = DeviceManager()
        gqrx_cfg = cfg.get("devices", {})
        gqrx_instances = gqrx_cfg.get("gqrx_instances", [])
        default_gqrx = gqrx_instances[0] if gqrx_instances else {"host": "localhost", "port": 7356}
        default_gqrx_host = default_gqrx.get("host", "localhost")
        default_gqrx_port = int(default_gqrx.get("port", 7356))

        if gqrx_cfg.get("gqrx_auto_detect", True):
            await ensure_gqrx_running(
                default_gqrx_host,
                default_gqrx_port,
                auto_start=gqrx_cfg.get("gqrx_auto_start", True),
                command=gqrx_cfg.get("gqrx_command") or None,
                config_path=os.path.expanduser(
                    gqrx_cfg.get("gqrx_config_path", "~/.config/gqrx/default.conf")
                ),
                startup_timeout_s=float(gqrx_cfg.get("gqrx_startup_timeout_s", 12)),
                probe_fn=lambda: mgr._probe_gqrx(default_gqrx_host, default_gqrx_port),
            )

        available = await mgr.enumerate_async(
            gqrx_auto_detect=gqrx_cfg.get("gqrx_auto_detect", True),
            gqrx_host=default_gqrx_host,
            gqrx_port=default_gqrx_port,
            gqrx_instances=gqrx_cfg.get("gqrx_instances", []),
        )

        # Separate SoapySDR scan devices from gqrx tuner
        hw_devices = [d for d in available if d.driver not in ("audio", "gqrx")]
        gqrx_devices = [d for d in available if d.driver == "gqrx"]

        # Store discovered devices in config so the settings API can list them
        cfg.setdefault("devices", {})["discovered"] = [
            {"label": d.label, "driver": d.driver, "serial": d.serial}
            for d in hw_devices
        ]
        cfg["devices"]["gqrx_instances"] = [
            {"host": d.serial.split(":")[0], "port": int(d.serial.split(":")[1])}
            for d in gqrx_devices
        ]
        cfg["_runtime_devices"] = {
            "scanner": None,
            "tuner": None,
            "available_sdrs": [
                {"label": d.label, "driver": d.driver, "serial": d.serial}
                for d in hw_devices
            ],
            "available_gqrx": [
                {"label": d.label, "serial": d.serial}
                for d in gqrx_devices
            ],
        }

        if not hw_devices and not gqrx_devices:
            logger.error("No devices found. Connect an SDR or start gqrx with remote control enabled.")
            if web_task:
                web_task.cancel()
            await db.close()
            return

        # Pick which SDR to use for scanning based on config
        scanner_pref = cfg.get("devices", {}).get("scanner_device")
        def _pick_scanner_device(hw_list, pref):
            """Select the preferred scanner device by serial or driver name."""
            if pref and pref != "none":
                for d in hw_list:
                    if d.serial == pref or d.driver == pref:
                        return d
                logger.warning("Preferred scanner device '%s' not found, falling back", pref)
            # Default: prefer rtlsdr over hackrf for scanning (lower noise floor)
            for d in hw_list:
                if d.driver == "rtlsdr":
                    return d
            return hw_list[0] if hw_list else None

        scan_dev_info = _pick_scanner_device(hw_devices, scanner_pref)

        # Open SoapySDR device for scanning (if available)
        device = None
        if scan_dev_info:
            try:
                device = mgr.open(driver=scan_dev_info.driver, serial=scan_dev_info.serial)
                device.set_gain(cfg["devices"]["gain"])
                # Prime the stream, but do not fail startup on a transient first read.
                try:
                    device.start_stream()
                    test_buf = device.read_samples(1024, retries=8)
                    device.stop_stream()
                    if test_buf is None:
                        logger.warning(
                            "SDR opened but initial read failed; continuing and letting the sweep loop retry"
                        )
                except Exception as stream_err:
                    logger.warning(
                        "SDR stream probe failed during startup; continuing with retries: %s",
                        stream_err,
                    )
                    try:
                        device.stop_stream()
                    except Exception:
                        pass
                logger.info("Scanning with: %s (%s)", scan_dev_info.label, scan_dev_info.driver)
                cfg["_runtime_devices"]["scanner"] = {
                    "label": scan_dev_info.label,
                    "driver": scan_dev_info.driver,
                    "serial": scan_dev_info.serial,
                    "gain_db": cfg["devices"]["gain"],
                    "sample_rate_hz": 2_000_000,
                    "status": "active",
                }
            except Exception as e:
                logger.warning("Cannot use SDR device: %s — falling back to gqrx-only mode", e)
                try:
                    device.close()
                except Exception:
                    pass
                device = None
                cfg["_runtime_devices"]["scanner"] = {
                    "label": scan_dev_info.label,
                    "driver": scan_dev_info.driver,
                    "serial": scan_dev_info.serial,
                    "status": f"unavailable: {e}",
                }
        if device is None:
            logger.info("No usable SoapySDR device — running in gqrx-only mode (no scanning)")

        # Open gqrx as tuner/player if available
        gqrx_device = None
        if gqrx_devices:
            # Pick preferred gqrx instance from config
            tuner_pref = cfg.get("devices", {}).get("tuner_device")
            gd = gqrx_devices[0]  # default to first
            if tuner_pref and tuner_pref != "none":
                for d in gqrx_devices:
                    if d.serial == tuner_pref:
                        gd = d
                        break
                else:
                    logger.warning("Preferred tuner device '%s' not found, using %s", tuner_pref, gd.serial)
            try:
                gqrx_host, gqrx_port_str = gd.serial.split(":")
                gqrx_device = await mgr.open_gqrx(host=gqrx_host, port=int(gqrx_port_str))
                logger.info("gqrx connected at %s — select a signal to tune", gd.serial)
                cfg["_runtime_devices"]["tuner"] = {
                    "label": gd.label,
                    "driver": "gqrx",
                    "serial": gd.serial,
                    "host": gqrx_host,
                    "port": int(gqrx_port_str),
                    "status": "connected",
                }
                if not headless:
                    try:
                        from signaldeck.api.routes.scanner import _scanner_state
                        _scanner_state["backend"] = "both" if device else "gqrx"
                        _scanner_state["active_devices"] = (1 if device else 0) + 1
                        _scanner_state["scanner_device"] = (
                            cfg["_runtime_devices"]["scanner"]["label"]
                            if cfg["_runtime_devices"].get("scanner") else None
                        )
                        _scanner_state["tuner_device"] = gd.label
                    except ImportError:
                        pass
            except Exception as e:
                logger.warning("Could not connect to gqrx: %s", e)
                gqrx_device = None
                cfg["_runtime_devices"]["tuner"] = {
                    "label": gd.label,
                    "driver": "gqrx",
                    "serial": gd.serial,
                    "status": f"unavailable: {e}",
                }

        # Set active_devices for SDR-only mode (no gqrx branch above)
        if device and not gqrx_device and not headless:
            try:
                from signaldeck.api.routes.scanner import _scanner_state
                _scanner_state["backend"] = "soapysdr"
                _scanner_state["active_devices"] = 1
                _scanner_state["scanner_device"] = (
                    cfg["_runtime_devices"]["scanner"]["label"]
                    if cfg["_runtime_devices"].get("scanner") else None
                )
                _scanner_state["tuner_device"] = None
            except ImportError:
                pass

        # Build scan ranges and scanner (only if we have an SDR device)
        scanner = None
        ranges = [ScanRange.from_config(r) for r in resolve_sweep_ranges(cfg["scanner"])]
        if device:
            scanner = FrequencyScanner(
                device=device,
                scan_ranges=ranges,
                fft_size=cfg["scanner"]["fft_size"],
                squelch_offset_db=cfg["scanner"]["squelch_offset"],
                dwell_time_s=cfg["scanner"]["dwell_time_ms"] / 1000.0,
            )

        from signaldeck.storage.models import Signal, ActivityEntry
        from signaldeck.engine.classifier import SignalClassifier
        from signaldeck.decoders.base import SignalInfo
        from signaldeck.decoders.ism import IsmDecoder, summarize_rtl433_json
        from signaldeck.api.routes.scanner import _scanner_state

        classifier = SignalClassifier()

        from signaldeck.decoders.rds import RdsDecoder
        rds_decoder = RdsDecoder()
        ism_decoder = IsmDecoder()
        ism_capture_cooldowns: dict[int, float] = {}

        # WebSocket broadcast (only when dashboard is running)
        ws_broadcast = None
        fft_broadcast_fn = None
        audio_stream_fn = None
        audio_request_fn = None
        if not headless:
            try:
                from signaldeck.api.websocket.live_signals import broadcast, signal_broadcast
                ws_broadcast = (broadcast, signal_broadcast)
            except ImportError:
                pass
            try:
                from signaldeck.api.websocket.audio_stream import send_audio_chunk, get_audio_request
                audio_stream_fn = send_audio_chunk
                audio_request_fn = get_audio_request
            except ImportError:
                pass
            try:
                from signaldeck.api.websocket.waterfall import broadcast_fft, fft_broadcast
                fft_broadcast_fn = (broadcast_fft, fft_broadcast)
            except ImportError:
                pass

        min_strength = cfg["scanner"].get("min_signal_strength", -50)

        async def _single_iq_source(iq_samples):
            yield iq_samples

        async def run_ism_burst_workflow(signal_id: int, classified: SignalInfo, peak_power: float) -> None:
            if not device or not cfg["scanner"].get("ism_burst_enabled", True):
                return

            freq_key = int(round(classified.frequency_hz / 5_000.0) * 5_000)
            cooldown_s = float(cfg["scanner"].get("ism_burst_cooldown_s", 20))
            now_mono = asyncio.get_running_loop().time()
            last_capture = ism_capture_cooldowns.get(freq_key)
            if last_capture is not None and now_mono - last_capture < cooldown_s:
                return
            ism_capture_cooldowns[freq_key] = now_mono

            burst_sample_rate = float(cfg["scanner"].get("ism_burst_sample_rate", 250_000))
            burst_duration_s = float(cfg["scanner"].get("ism_burst_duration_ms", 350)) / 1000.0
            iq_samples = await capture_iq_burst(
                device,
                classified.frequency_hz,
                sample_rate=burst_sample_rate,
                duration_s=burst_duration_s,
            )
            if iq_samples is None or len(iq_samples) < 256:
                return

            triage = triage_ism_burst(iq_samples, burst_sample_rate)
            triage_summary = summarize_burst_triage(classified.frequency_hz, triage)
            triage_activity = ActivityEntry(
                signal_id=signal_id,
                timestamp=datetime.now(timezone.utc),
                duration=burst_duration_s,
                strength=peak_power,
                decoder_used="ism_triage",
                result_type="burst",
                summary=triage_summary,
                raw_result=triage,
            )
            triage_activity_id = await db.insert_activity(triage_activity)
            await db.insert_decoder_result(
                triage_activity_id,
                decoder="ism_triage",
                protocol="ism",
                result_type="burst",
                content=triage,
            )

            if not ism_decoder.tool_available():
                return

            decode_signal = SignalInfo(
                frequency_hz=classified.frequency_hz,
                bandwidth_hz=classified.bandwidth_hz,
                peak_power=peak_power,
                modulation=classified.modulation,
                sample_rate=burst_sample_rate,
                protocol_hint="ism",
            )
            decoded_results = await ism_decoder.decode_to_list(decode_signal, _single_iq_source(iq_samples))
            for result in decoded_results[:10]:
                summary = summarize_rtl433_json(result.content)
                activity = ActivityEntry(
                    signal_id=signal_id,
                    timestamp=result.timestamp,
                    duration=burst_duration_s,
                    strength=peak_power,
                    decoder_used="rtl_433",
                    result_type=result.result_type,
                    summary=summary,
                    raw_result=result.content,
                )
                activity_id = await db.insert_activity(activity)
                await db.insert_decoder_result(
                    activity_id,
                    decoder="rtl_433",
                    protocol=result.protocol,
                    result_type=result.result_type,
                    content=result.content,
                )

        pending_signal_queue: asyncio.Queue = asyncio.Queue()

        async def on_signals(signals):
            now = datetime.now(timezone.utc)
            for sig in signals:
                if sig.peak_power < min_strength:
                    continue
                pending_signal_queue.put_nowait((sig, now))

        async def on_scan_progress(scan_range, freq_hz: float, step_index: int, total_steps: int):
            _scanner_state["current_range"] = {
                "label": scan_range.label or f"{scan_range.start_hz / 1e6:.3f}-{scan_range.end_hz / 1e6:.3f} MHz",
                "start_hz": scan_range.start_hz,
                "end_hz": scan_range.end_hz,
                "step_hz": scan_range.step_hz,
                "frequency_hz": freq_hz,
                "frequency_mhz": round(freq_hz / 1e6, 4),
                "step_index": step_index + 1,
                "step_count": total_steps,
            }

        def _fm_candidate_score(sig, classified: SignalInfo) -> tuple[float, float, float]:
            wide_bonus = 1.0 if sig.bandwidth_hz >= 120_000 else 0.0
            class_bonus = 1.0 if classified.signal_class == "broadcast_program" else 0.0
            return (wide_bonus + class_bonus, sig.bandwidth_hz, sig.peak_power)

        async def _signal_pipeline_worker():
            while True:
                first_item = await pending_signal_queue.get()
                batch = [first_item]
                batch_window_s = 0.2
                batch_limit = 200
                deadline = asyncio.get_running_loop().time() + batch_window_s
                while len(batch) < batch_limit:
                    timeout = deadline - asyncio.get_running_loop().time()
                    if timeout <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(pending_signal_queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        break
                    batch.append(item)
                try:
                    await _process_signal_batch(batch)
                finally:
                    for _ in batch:
                        pending_signal_queue.task_done()

        async def _process_signal_batch(batch: list[tuple[object, datetime]]) -> None:
            now = batch[0][1]
            ism_candidates: list[tuple[int, SignalInfo, float]] = []
            ws_messages: list[dict] = []
            normalized_batch: list[tuple[object, datetime, float, SignalInfo]] = []
            fm_by_channel: dict[float, tuple[object, datetime, float, SignalInfo]] = {}

            for sig, detected_at in batch:
                raw_freq_hz = channelize(sig.frequency_hz)
                signal_info = SignalInfo(
                    frequency_hz=raw_freq_hz,
                    bandwidth_hz=sig.bandwidth_hz,
                    peak_power=sig.peak_power,
                    modulation="unknown",
                    signal_features=sig.features or {},
                )
                classified = classifier.classify(signal_info)

                if classified.protocol_hint == "broadcast_fm":
                    existing = fm_by_channel.get(raw_freq_hz)
                    candidate = (sig, detected_at, raw_freq_hz, classified)
                    if existing is None or _fm_candidate_score(sig, classified) > _fm_candidate_score(existing[0], existing[3]):
                        fm_by_channel[raw_freq_hz] = candidate
                    continue

                normalized_batch.append((sig, detected_at, raw_freq_hz, classified))

            normalized_batch.extend(fm_by_channel.values())
            async with db._lock:
                for sig, detected_at, freq_hz, classified in normalized_batch:
                    now = detected_at
                    if 87_500_000 <= freq_hz <= 108_000_000 and sig.bandwidth_hz < 30_000:
                        continue

                    db_signal = Signal(
                        frequency=freq_hz,
                        bandwidth=sig.bandwidth_hz,
                        modulation=classified.modulation,
                        protocol=classified.protocol_hint or None,
                        first_seen=now,
                        last_seen=now,
                        hit_count=1,
                        avg_strength=sig.peak_power,
                        confidence=0.0,
                        classification_data={
                            "signal_class": classified.signal_class,
                            "content_confidence": classified.content_confidence,
                            "signal_features": sig.features or {},
                        },
                    )
                    signal_id = await db.upsert_signal(db_signal, commit=False)

                    proto_label = classified.protocol_hint or classified.modulation
                    entry = ActivityEntry(
                        signal_id=signal_id,
                        timestamp=now,
                        duration=cfg["scanner"]["dwell_time_ms"] / 1000.0,
                        strength=sig.peak_power,
                        decoder_used=None,
                        result_type=classified.protocol_hint or "unknown",
                        summary=f"{freq_hz / 1e6:.3f} MHz "
                                f"[{proto_label}] {sig.peak_power:.1f} dBFS",
                    )
                    await db.insert_activity(entry, commit=False)

                    if classified.protocol_hint == "ism":
                        ism_candidates.append((signal_id, classified, sig.peak_power))

                    if ws_broadcast:
                        _, msg_fn = ws_broadcast
                        ws_messages.append(
                            msg_fn(
                                frequency_hz=freq_hz,
                                bandwidth_hz=sig.bandwidth_hz,
                                power=sig.peak_power,
                                modulation=classified.modulation,
                                protocol=classified.protocol_hint,
                                signal_class=classified.signal_class,
                                content_confidence=classified.content_confidence,
                            )
                        )
                await db.commit()

            if ws_broadcast and ws_messages:
                broadcast_fn, _ = ws_broadcast
                if len(ws_messages) == 1:
                    await broadcast_fn(ws_messages[0])
                else:
                    from signaldeck.api.websocket.live_signals import signal_batch_broadcast
                    await broadcast_fn(signal_batch_broadcast(ws_messages))

            max_bursts = int(cfg["scanner"].get("ism_max_bursts_per_sweep", 3))
            ism_candidates.sort(key=lambda item: item[2], reverse=True)
            for signal_id, classified, peak_power in ism_candidates[:max_bursts]:
                try:
                    await run_ism_burst_workflow(signal_id, classified, peak_power)
                except Exception as e:
                    logger.warning(
                        "ISM burst workflow failed at %.3f MHz: %s",
                        classified.frequency_hz / 1e6,
                        e,
                    )

        # FFT broadcast callback for waterfall display
        async def on_fft(center_freq_hz, sample_rate, power_db):
            if fft_broadcast_fn:
                bcast_fn, msg_fn = fft_broadcast_fn
                msg = msg_fn(center_freq_hz, sample_rate, power_db)
                await bcast_fn(msg)

        # RDS IQ callback — processes FM broadcast IQ for RDS decoding
        async def on_rds(center_freq_hz, iq_samples):
            """Decode RDS from raw IQ samples captured during scanning."""
            signal_info = SignalInfo(
                frequency_hz=center_freq_hz,
                bandwidth_hz=200_000,
                peak_power=-30.0,
                modulation="FM",
                sample_rate=2_000_000,
                protocol_hint="broadcast_fm",
            )
            async for rds_result in rds_decoder.decode(signal_info, iq_samples):
                content = rds_result.content
                ps_name = content.get("ps_name", "")
                radio_text = content.get("radio_text", "")
                if ps_name:
                    logger.debug("RDS @ %.1f MHz: [%s] %s",
                                 center_freq_hz / 1e6, ps_name, radio_text)
                # Broadcast RDS data via WebSocket
                if ws_broadcast and ps_name:
                    broadcast_fn, msg_fn = ws_broadcast
                    msg = msg_fn(
                        frequency_hz=center_freq_hz,
                        bandwidth_hz=200_000,
                        power=-30.0,
                        modulation="FM",
                        protocol="broadcast_fm",
                    )
                    msg["rds"] = {
                        "ps_name": ps_name,
                        "radio_text": radio_text,
                        "pty_name": content.get("pty_name", ""),
                        "pi_code": content.get("pi_code"),
                    }
                    await broadcast_fn(msg)

        # Track gqrx tuning state so we don't re-send the same frequency
        _gqrx_tuned_freq = None

        # Map SignalDeck modulation labels to gqrx demod mode strings
        _MODULATION_TO_GQRX_MODE = {
            "FM": "WFM",       # broadcast FM → wideband FM
            "AM": "AM",
            "NFM": "FM",       # narrowband FM
            "USB": "USB",
            "LSB": "LSB",
            "CW": "CW",
        }

        def _gqrx_mode_for(modulation: str | None, freq_hz: float) -> str:
            """Pick the right gqrx demod mode from modulation label + frequency."""
            if modulation:
                mode = _MODULATION_TO_GQRX_MODE.get(modulation.upper())
                if mode:
                    return mode
                # "FM" from classifier could be narrowband or wideband
                if modulation.upper() == "FM":
                    if 87_500_000 <= freq_hz <= 108_000_000:
                        return "WFM"
                    return "FM"  # narrowband FM for VHF/UHF
            # Fallback: guess from frequency
            if 87_500_000 <= freq_hz <= 108_000_000:
                return "WFM"
            if 118_000_000 <= freq_hz <= 137_000_000:
                return "AM"
            return "FM"  # narrowband FM default

        async def _gqrx_tuning_loop():
            """Continuously poll for tuning requests and RDS data.

            Runs as a separate task so it responds immediately even while
            the scanner is mid-sweep.
            """
            nonlocal _gqrx_tuned_freq
            if not gqrx_device or not audio_request_fn:
                return
            _last_volume = None

            def _slider_to_gqrx_af_gain(level: float | None) -> float:
                # Map UI slider 0.0..1.0 to gqrx AF gain attenuation in dB.
                # 0.0 => -60 dB (very quiet), 1.0 => 0 dB (full scale).
                if level is None:
                    level = 0.2
                level = max(0.0, min(1.0, float(level)))
                return -60.0 + (level * 60.0)

            while True:
                try:
                    audio_req = audio_request_fn()

                    # Handle volume changes (0.0-1.0 -> -60 dB to 0 dB AF gain)
                    vol = audio_req.get("volume")
                    if vol is not None and vol != _last_volume:
                        af_gain = _slider_to_gqrx_af_gain(vol)
                        await gqrx_device._client.set_audio_gain(af_gain)
                        _last_volume = vol
                        logger.debug("gqrx: volume %.0f%% (AF gain %.1f dB)", vol * 100, af_gain)

                    if audio_req.get("active") and audio_req.get("frequency_hz"):
                        freq_hz = audio_req["frequency_hz"]
                        if freq_hz != _gqrx_tuned_freq:
                            # Set demodulation mode before tuning
                            mode = _gqrx_mode_for(audio_req.get("modulation"), freq_hz)
                            await gqrx_device.set_mode(mode)
                            await gqrx_device.tune(freq_hz)
                            # Ensure DSP is on, then apply the current slider value.
                            await gqrx_device._client.set_dsp(True)
                            af_gain = _slider_to_gqrx_af_gain(vol)
                            await gqrx_device._client.set_audio_gain(af_gain)
                            _last_volume = vol
                            _gqrx_tuned_freq = freq_hz
                            logger.info("gqrx: tuned to %.3f MHz (mode=%s)", freq_hz / 1e6, mode)
                            # Enable RDS for FM broadcast frequencies
                            if 87_500_000 <= freq_hz <= 108_000_000:
                                await gqrx_device.enable_rds()

                        # Poll gqrx for RDS data and broadcast it
                        if 87_500_000 <= freq_hz <= 108_000_000:
                            rds = await gqrx_device.get_rds()
                            if rds and rds.get("ps_name") and ws_broadcast:
                                broadcast_fn, msg_fn = ws_broadcast
                                msg = msg_fn(
                                    frequency_hz=freq_hz,
                                    bandwidth_hz=200_000,
                                    power=-30.0,
                                    modulation="FM",
                                    protocol="broadcast_fm",
                                )
                                msg["rds"] = rds
                                await broadcast_fn(msg)
                    else:
                        if _gqrx_tuned_freq is not None:
                            # Stop gqrx audio when user clicks Stop
                            await gqrx_device._client.set_dsp(False)
                            _last_volume = None
                            _gqrx_tuned_freq = None
                            logger.info("gqrx: stopped (DSP off)")
                except Exception as e:
                    logger.warning("gqrx tuning error: %s", e)
                await asyncio.sleep(0.3)

        # Clear stale signals from previous sessions
        await db.clear_signals()
        await db.clear_activity()
        logger.info("Cleared stale signals from previous session")

        # Respect auto_start config — only begin scanning if configured
        auto_start = cfg["scanner"].get("auto_start", False)
        if scanner:
            if auto_start:
                _scanner_state["status"] = "running"
                logger.info("Auto-starting sweep across %d range(s)...", len(ranges))
            else:
                _scanner_state["status"] = "idle"
                logger.info("Scanner ready — press Start in the dashboard to begin scanning")
        else:
            logger.info("gqrx-only mode — use the dashboard to tune frequencies")
        # Launch gqrx tuning as a separate concurrent task so it responds
        # immediately even while the scanner is mid-sweep
        gqrx_task = None
        if gqrx_device:
            gqrx_task = asyncio.create_task(_gqrx_tuning_loop())
        signal_pipeline_task = asyncio.create_task(_signal_pipeline_worker())

        idle_ticks = 0
        try:
            while True:
                if scanner:
                    # If no gqrx, SoapySDR can do audio (pauses scanning)
                    if not gqrx_device and audio_request_fn:
                        audio_req = audio_request_fn()
                        if audio_req.get("active") and audio_req.get("frequency_hz"):
                            logger.info("Audio streaming: tuning to %.3f MHz",
                                        audio_req["frequency_hz"] / 1e6)
                            await _stream_audio(device, audio_req["frequency_hz"],
                                                audio_stream_fn, audio_request_fn,
                                                sample_rate=2_000_000,
                                                fft_callback=on_fft,
                                                rds_callback=on_rds)
                            logger.info("Audio streaming ended, resuming scan")
                            continue

                    # Only sweep when scanner is set to running (via UI or auto_start)
                    if _scanner_state["status"] != "running":
                        await asyncio.sleep(0.5)
                        continue

                    # Apply settings changes from the UI to the running scanner
                    scanner._fft_size = cfg["scanner"]["fft_size"]
                    scanner._squelch_offset = cfg["scanner"]["squelch_offset"]
                    scanner._dwell_time = cfg["scanner"]["dwell_time_ms"] / 1000.0
                    scanner._scan_ranges = [
                        ScanRange.from_config(r) for r in resolve_sweep_ranges(cfg["scanner"])
                    ]
                    min_strength = cfg["scanner"].get("min_signal_strength", -50)
                    device.set_gain(cfg["devices"]["gain"])

                    # SoapySDR handles scanning — respect selected mode
                    scan_mode = _scanner_state.get("mode", "sweep")
                    if scan_mode == "bookmarks":
                        bookmarks = await db.get_all_bookmarks()
                        if bookmarks:
                            # Build temporary scan ranges from bookmark frequencies
                            bk_ranges = [
                                ScanRange(
                                    start_hz=bk.frequency - 100_000,
                                    end_hz=bk.frequency + 100_000,
                                    step_hz=200_000,
                                    label=bk.label,
                                )
                                for bk in bookmarks
                            ]
                            old_ranges = scanner._scan_ranges
                            scanner._scan_ranges = bk_ranges
                            signals = await scanner.sweep_once(
                                fft_callback=on_fft,
                                rds_callback=on_rds,
                                rds_sample_count=131_072,
                                signal_callback=on_signals,
                                progress_callback=on_scan_progress,
                            )
                            scanner._scan_ranges = old_ranges
                        else:
                            signals = []
                            await asyncio.sleep(1)  # no bookmarks, don't spin
                    else:
                        # "sweep" and "smart" both do a full sweep
                        signals = await scanner.sweep_once(
                            fft_callback=on_fft,
                            rds_callback=on_rds,
                            rds_sample_count=131_072,
                            signal_callback=on_signals,
                            progress_callback=on_scan_progress,
                        )
                else:
                    # gqrx-only mode: no scanning, just handle tuning
                    idle_ticks += 1
                    if idle_ticks % 20 == 1:  # every ~10s
                        logger.info("Idle — dashboard ready, %s",
                                    "gqrx connected" + (" (tuned to %.3f MHz)" % (_gqrx_tuned_freq / 1e6) if _gqrx_tuned_freq else " (idle)")
                                    if gqrx_device else "no gqrx")
                    await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            if gqrx_task:
                gqrx_task.cancel()
            signal_pipeline_task.cancel()
            _scanner_state["current_range"] = None
            if device:
                device.close()
            if gqrx_device:
                await gqrx_device.close()
            await db.close()
            if web_task:
                web_task.cancel()
            logger.info("Shutdown complete.")

    asyncio.run(_run())


@cli.command()
def status() -> None:
    """Show scanner status."""
    cfg = load_config(None)
    db_path = cfg["storage"]["database_path"]

    async def _status() -> None:
        from signaldeck.storage.database import Database
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = Database(db_path)
        await db.initialize()

        signals = await db.get_all_signals()
        recent = await db.get_recent_activity(limit=10)

        click.echo(f"SignalDeck v{__version__}")
        click.echo(f"Known signals: {len(signals)}")
        click.echo(f"Recent activity entries: {len(recent)}")

        if signals:
            click.echo("\nTop signals by hit count:")
            sorted_sigs = sorted(signals, key=lambda s: s.hit_count, reverse=True)
            for s in sorted_sigs[:10]:
                click.echo(
                    f"  {s.frequency / 1e6:>10.3f} MHz  "
                    f"mod={s.modulation:<8s}  "
                    f"hits={s.hit_count:<5d}  "
                    f"str={s.avg_strength:.1f} dBFS"
                )

        await db.close()

    asyncio.run(_status())


@cli.command()
def devices() -> None:
    """List connected SDR devices."""
    from signaldeck.engine.device_manager import DeviceManager
    mgr = DeviceManager()
    found = mgr.enumerate()
    if not found:
        click.echo("No SDR devices found.")
        return
    click.echo(f"Found {len(found)} device(s):")
    for d in found:
        click.echo(f"  {d.label}  driver={d.driver}  serial={d.serial}")


@cli.group()
def scan() -> None:
    """Scanner control commands."""


@scan.command()
@click.argument("range_spec", required=False)
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def sweep(range_spec: str | None, config_path: str | None) -> None:
    """Run a single sweep. Optional RANGE_SPEC like '118-137M'."""
    cfg = load_config(config_path)
    setup_logging(cfg["logging"]["level"])

    from signaldeck.engine.device_manager import DeviceManager
    from signaldeck.engine.scanner import FrequencyScanner, ScanRange

    if range_spec:
        parts = range_spec.upper().rstrip("M").split("-")
        start = float(parts[0]) * 1e6
        end = float(parts[1]) * 1e6
        ranges = [ScanRange(start_hz=start, end_hz=end, label=range_spec)]
    else:
        ranges = [ScanRange.from_config(r) for r in resolve_sweep_ranges(cfg["scanner"])]

    async def _sweep() -> None:
        mgr = DeviceManager()
        available = mgr.enumerate()
        sdr_devices = [d for d in available if d.driver not in ("audio",)]
        if not sdr_devices:
            click.echo("No SDR devices found. Connect a HackRF or RTL-SDR.")
            return

        device = mgr.open(driver=sdr_devices[0].driver,
                          serial=sdr_devices[0].serial)
        device.set_gain(cfg["devices"]["gain"])
        scanner = FrequencyScanner(
            device=device,
            scan_ranges=ranges,
            fft_size=cfg["scanner"]["fft_size"],
            squelch_offset_db=cfg["scanner"]["squelch_offset"],
            dwell_time_s=cfg["scanner"]["dwell_time_ms"] / 1000.0,
        )

        click.echo(f"Sweeping {len(ranges)} range(s)...")
        signals = await scanner.sweep_once()
        device.close()

        if not signals:
            click.echo("No signals detected.")
            return

        click.echo(f"Found {len(signals)} signal(s):")
        for s in signals:
            click.echo(
                f"  {s.frequency_hz / 1e6:>10.3f} MHz  "
                f"bw={s.bandwidth_hz / 1e3:.1f} kHz  "
                f"peak={s.peak_power:.1f} dBFS"
            )

    asyncio.run(_sweep())


@cli.group()
def bookmark() -> None:
    """Manage frequency bookmarks."""


@bookmark.command("list")
def bookmark_list() -> None:
    """List all bookmarks."""
    click.echo("Bookmarks not yet implemented.")


@bookmark.command("add")
@click.argument("frequency")
@click.option("--label", required=True)
@click.option("--decoder", default=None)
@click.option("--priority", default=3, type=int)
def bookmark_add(frequency: str, label: str, decoder: str | None, priority: int) -> None:
    """Add a frequency bookmark."""
    click.echo(f"Bookmark add not yet implemented: {frequency} ({label})")


if __name__ == "__main__":
    cli()

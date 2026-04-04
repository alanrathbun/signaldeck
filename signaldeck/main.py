import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import click

from signaldeck import __version__
from signaldeck.config import load_config
from signaldeck.engine.channelizer import channelize


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
                        chunk_duration_s: float = 0.1) -> None:
    """Tune to a frequency and continuously stream demodulated FM audio.

    Keeps streaming until the audio request becomes inactive.
    """
    import numpy as np
    from signaldeck.engine.audio_pipeline import fm_demodulate

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
            uvi_config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(uvi_config)
            web_task = asyncio.create_task(server.serve())
            logger.info("Web dashboard at http://%s:%d", host, port)

        # Discover devices
        mgr = DeviceManager()
        gqrx_cfg = cfg.get("devices", {})
        available = await mgr.enumerate_async(
            gqrx_auto_detect=gqrx_cfg.get("gqrx_auto_detect", True),
            gqrx_instances=gqrx_cfg.get("gqrx_instances", []),
        )

        # Separate SoapySDR scan devices from gqrx tuner
        hw_devices = [d for d in available if d.driver not in ("audio", "gqrx")]
        gqrx_devices = [d for d in available if d.driver == "gqrx"]

        if not hw_devices and not gqrx_devices:
            logger.error("No devices found. Connect an SDR or start gqrx with remote control enabled.")
            if web_task:
                web_task.cancel()
            await db.close()
            return

        # Open SoapySDR device for scanning (if available)
        device = None
        if hw_devices:
            try:
                device = mgr.open(driver=hw_devices[0].driver, serial=hw_devices[0].serial)
                # Test that we can actually use the device (USB interface may be busy)
                device.start_stream()
                test_buf = device.read_samples(1024)
                device.stop_stream()
                if test_buf is None:
                    raise RuntimeError("Device opened but cannot read samples (USB busy?)")
                device.set_gain(cfg["devices"]["gain"])
                logger.info("Scanning with: %s (%s)", hw_devices[0].label, hw_devices[0].driver)
            except Exception as e:
                logger.warning("Cannot use SDR device: %s — falling back to gqrx-only mode", e)
                try:
                    device.close()
                except Exception:
                    pass
                device = None
        if device is None:
            logger.info("No usable SoapySDR device — running in gqrx-only mode (no scanning)")

        # Open gqrx as tuner/player if available
        gqrx_device = None
        if gqrx_devices:
            try:
                gd = gqrx_devices[0]
                gqrx_host, gqrx_port_str = gd.serial.split(":")
                gqrx_device = await mgr.open_gqrx(host=gqrx_host, port=int(gqrx_port_str))
                logger.info("gqrx connected at %s — select a signal to tune", gd.serial)
                if not headless:
                    try:
                        from signaldeck.api.routes.scanner import _scanner_state
                        _scanner_state["backend"] = "gqrx"
                    except ImportError:
                        pass
            except Exception as e:
                logger.warning("Could not connect to gqrx: %s", e)
                gqrx_device = None

        # Build scan ranges and scanner (only if we have an SDR device)
        scanner = None
        ranges = [ScanRange.from_config(r) for r in cfg["scanner"]["sweep_ranges"]]
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

        classifier = SignalClassifier()

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

        async def on_signals(signals):
            now = datetime.now(timezone.utc)
            for sig in signals:
                # Filter out weak signals below the minimum strength threshold
                if sig.peak_power < min_strength:
                    continue
                # Snap to nearest standard channel frequency
                freq_hz = channelize(sig.frequency_hz)
                # Classify the signal
                signal_info = SignalInfo(
                    frequency_hz=freq_hz,
                    bandwidth_hz=sig.bandwidth_hz,
                    peak_power=sig.peak_power,
                    modulation="unknown",
                )
                classified = classifier.classify(signal_info)

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
                )
                signal_id = await db.upsert_signal(db_signal)

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
                await db.insert_activity(entry)

                # Broadcast to WebSocket clients
                if ws_broadcast:
                    broadcast_fn, msg_fn = ws_broadcast
                    msg = msg_fn(
                        frequency_hz=freq_hz,
                        bandwidth_hz=sig.bandwidth_hz,
                        power=sig.peak_power,
                        modulation=classified.modulation,
                        protocol=classified.protocol_hint,
                    )
                    await broadcast_fn(msg)

        # FFT broadcast callback for waterfall display
        async def on_fft(center_freq_hz, sample_rate, power_db):
            if fft_broadcast_fn:
                bcast_fn, msg_fn = fft_broadcast_fn
                msg = msg_fn(center_freq_hz, sample_rate, power_db)
                await bcast_fn(msg)

        # Track gqrx tuning state so we don't re-send the same frequency
        _gqrx_tuned_freq = None

        async def _handle_gqrx_tuning():
            """Check if user selected a frequency and tune gqrx to it."""
            nonlocal _gqrx_tuned_freq
            if not gqrx_device or not audio_request_fn:
                return
            audio_req = audio_request_fn()
            if audio_req.get("active") and audio_req.get("frequency_hz"):
                freq_hz = audio_req["frequency_hz"]
                if freq_hz != _gqrx_tuned_freq:
                    await gqrx_device.tune(freq_hz)
                    _gqrx_tuned_freq = freq_hz
                    logger.info("gqrx: tuned to %.3f MHz", freq_hz / 1e6)
            else:
                if _gqrx_tuned_freq is not None:
                    _gqrx_tuned_freq = None
                    logger.info("gqrx: idle")

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
                        logger.info("Idle — dashboard ready, %s",
                                    "gqrx connected" + (" (tuned to %.3f MHz)" % (_gqrx_tuned_freq / 1e6) if _gqrx_tuned_freq else " (idle)")
                                    if gqrx_device else "no gqrx")
                    await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
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
        ranges = [ScanRange.from_config(r) for r in cfg["scanner"]["sweep_ranges"]]

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

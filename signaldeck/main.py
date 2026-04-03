import asyncio
import logging
from pathlib import Path

import click

from signaldeck import __version__
from signaldeck.config import load_config


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """SignalDeck — SDR scanner, classifier, and decoder platform."""


async def _stream_audio(device, frequency_hz: float, send_fn, sample_rate: float = 2_000_000,
                        duration_s: float = 0.5) -> None:
    """Tune to a frequency, demodulate FM, and stream audio via WebSocket.

    Captures `duration_s` seconds of IQ, demodulates, and sends as PCM.
    """
    import numpy as np
    from signaldeck.engine.audio_pipeline import fm_demodulate

    num_samples = int(sample_rate * duration_s)
    device.tune(frequency_hz)
    await asyncio.sleep(0.01)  # settle time

    device.start_stream()
    samples = device.read_samples(num_samples)
    device.stop_stream()

    if samples is None or len(samples) < 1000:
        return

    # FM demodulate to 48 kHz audio
    audio = fm_demodulate(samples, sample_rate=sample_rate, audio_rate=48000)

    # Convert to 16-bit PCM bytes
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    await send_fn(frequency_hz, pcm16.tobytes())


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to config YAML file")
@click.option("--headless", is_flag=True, help="Start without web dashboard")
@click.option("--host", default="0.0.0.0", help="Web dashboard host")
@click.option("--port", default=8080, type=int, help="Web dashboard port")
def start(config_path: str | None, headless: bool, host: str, port: int) -> None:
    """Start the SignalDeck engine."""
    cfg = load_config(config_path)
    setup_logging(cfg["logging"]["level"])
    logger = logging.getLogger("signaldeck")

    logger.info("SignalDeck v%s starting...", __version__)

    from signaldeck.engine.device_manager import DeviceManager
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

        # Discover devices (skip audio devices, prefer SDR hardware)
        mgr = DeviceManager()
        available = mgr.enumerate()
        sdr_devices = [d for d in available if d.driver not in ("audio",)]
        if not sdr_devices:
            logger.error("No SDR devices found. Connect a HackRF or RTL-SDR and try again.")
            logger.error("Detected non-SDR devices: %s",
                         ", ".join(d.label for d in available) if available else "none")
            if web_task:
                web_task.cancel()
            await db.close()
            return

        logger.info("Found %d SDR device(s): %s", len(sdr_devices),
                     ", ".join(f"{d.label} ({d.driver})" for d in sdr_devices))
        device = mgr.open(driver=sdr_devices[0].driver,
                          serial=sdr_devices[0].serial)
        device.set_gain(cfg["devices"]["gain"])

        # Build scan ranges
        ranges = [ScanRange.from_config(r) for r in cfg["scanner"]["sweep_ranges"]]
        scanner = FrequencyScanner(
            device=device,
            scan_ranges=ranges,
            fft_size=cfg["scanner"]["fft_size"],
            squelch_offset_db=cfg["scanner"]["squelch_offset"],
            dwell_time_s=cfg["scanner"]["dwell_time_ms"] / 1000.0,
        )

        from datetime import datetime, timezone
        from signaldeck.storage.models import Signal, ActivityEntry
        from signaldeck.engine.classifier import SignalClassifier
        from signaldeck.decoders.base import SignalInfo

        classifier = SignalClassifier()

        # WebSocket broadcast (only when dashboard is running)
        ws_broadcast = None
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

        async def on_signals(signals):
            now = datetime.now(timezone.utc)
            for sig in signals:
                # Classify the signal
                signal_info = SignalInfo(
                    frequency_hz=sig.frequency_hz,
                    bandwidth_hz=sig.bandwidth_hz,
                    peak_power=sig.peak_power,
                    modulation="unknown",
                )
                classified = classifier.classify(signal_info)

                db_signal = Signal(
                    frequency=sig.frequency_hz,
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
                    summary=f"{sig.frequency_hz / 1e6:.3f} MHz "
                            f"[{proto_label}] {sig.peak_power:.1f} dBFS",
                )
                await db.insert_activity(entry)

                # Broadcast to WebSocket clients
                if ws_broadcast:
                    broadcast_fn, msg_fn = ws_broadcast
                    msg = msg_fn(
                        frequency_hz=sig.frequency_hz,
                        bandwidth_hz=sig.bandwidth_hz,
                        power=sig.peak_power,
                        modulation=classified.modulation,
                        protocol=classified.protocol_hint,
                    )
                    await broadcast_fn(msg)

        logger.info("Starting sweep across %d range(s)...", len(ranges))
        try:
            while True:
                # Check if audio streaming is requested
                if audio_request_fn:
                    audio_req = audio_request_fn()
                    if audio_req.get("active") and audio_req.get("frequency_hz"):
                        await _stream_audio(device, audio_req["frequency_hz"],
                                            audio_stream_fn, sample_rate=2_000_000)

                # Run one sweep cycle
                signals = await scanner.sweep_once()
                if signals:
                    await on_signals(signals)
        except KeyboardInterrupt:
            pass
        finally:
            device.close()
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

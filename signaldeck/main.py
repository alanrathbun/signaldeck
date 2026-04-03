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


@cli.command()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None,
              help="Path to config YAML file")
@click.option("--headless", is_flag=True, help="Start without web dashboard")
def start(config_path: str | None, headless: bool) -> None:
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

        # Discover devices
        mgr = DeviceManager()
        available = mgr.enumerate()
        if not available:
            logger.error("No SDR devices found. Connect a device and try again.")
            await db.close()
            return

        logger.info("Found %d device(s)", len(available))
        device = mgr.open(driver=available[0].driver)
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

        async def on_signals(signals):
            now = datetime.now(timezone.utc)
            for sig in signals:
                db_signal = Signal(
                    frequency=sig.frequency_hz,
                    bandwidth=sig.bandwidth_hz,
                    modulation="unknown",
                    protocol=None,
                    first_seen=now,
                    last_seen=now,
                    hit_count=1,
                    avg_strength=sig.peak_power,
                    confidence=0.0,
                )
                signal_id = await db.upsert_signal(db_signal)
                entry = ActivityEntry(
                    signal_id=signal_id,
                    timestamp=now,
                    duration=cfg["scanner"]["dwell_time_ms"] / 1000.0,
                    strength=sig.peak_power,
                    decoder_used=None,
                    result_type="unknown",
                    summary=f"Signal at {sig.frequency_hz / 1e6:.3f} MHz, "
                            f"{sig.peak_power:.1f} dBFS",
                )
                await db.insert_activity(entry)
            logger.info("Logged %d signals to database", len(signals))

        logger.info("Starting sweep across %d range(s)...", len(ranges))
        try:
            await scanner.run(callback=on_signals)
        except KeyboardInterrupt:
            scanner.stop()
        finally:
            device.close()
            await db.close()
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
        if not available:
            click.echo("No SDR devices found.")
            return

        device = mgr.open(driver=available[0].driver)
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

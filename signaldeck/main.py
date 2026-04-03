import asyncio
import logging
from pathlib import Path

import click

from signaldeck import __version__


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
@click.option("--config", type=click.Path(exists=True), default=None,
              help="Path to config YAML file")
@click.option("--headless", is_flag=True, help="Start without web dashboard")
def start(config: str | None, headless: bool) -> None:
    """Start the SignalDeck engine."""
    click.echo(f"SignalDeck v{__version__} starting...")
    click.echo("Engine not yet implemented.")


@cli.command()
def status() -> None:
    """Show scanner status."""
    click.echo("Status not yet implemented.")


@cli.command()
def devices() -> None:
    """List connected SDR devices."""
    click.echo("Devices not yet implemented.")


if __name__ == "__main__":
    cli()

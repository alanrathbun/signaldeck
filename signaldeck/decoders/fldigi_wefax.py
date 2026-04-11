"""HF Weather Fax (WEFAX) decoder via fldigi XML-RPC.

fldigi (http://www.w1hkj.com/) is a mature HF digital modes decoder
that includes WEFAX support. It runs as a GUI/daemon process and
exposes an XML-RPC control interface we can drive remotely.

### Installation

    sudo apt install fldigi

fldigi is in the standard Debian/Ubuntu repositories. No third-party
repo needed.

### Runtime setup

For SignalDeck to control fldigi, fldigi must be running with XML-RPC
enabled. Start it with:

    fldigi --xmlrpc-server-address 127.0.0.1 --xmlrpc-server-port 7362 &

The default XML-RPC port is 7362. SignalDeck connects to
`http://127.0.0.1:7362/RPC2` by default; override via the fldigi_host
and fldigi_port constructor arguments.

### Audio routing

fldigi expects audio input from a sound device or virtual loopback.
The cleanest path is to create a PulseAudio/PipeWire null sink and
route SignalDeck's decoded FM audio into it, then set fldigi to use
that sink as its input. This module does NOT automate that routing
— that's a system-level concern. See docs/references/wefax-setup.md
(future doc) for a step-by-step.

Until that's set up, this decoder is a no-op placeholder: it
detects "fldigi is running and reachable" and reports that setup
is incomplete in the logs.

### fldigi XML-RPC methods used

- `modem.set_by_name("WEFAX-IOC576")` — switch to WEFAX mode
- `main.rx()` — start receiving
- `main.tx()` — start transmitting (not used)
- `wefax.get_received_file()` — blocking call, returns the path
  of the next completed image file
- `wefax.skip_apt()` — skip automatic APT tone detection
- `wefax.skip_phasing(skip=True)` — skip phasing if signal quality is poor

See http://www.w1hkj.com/FldigiHelp/wefax_page.html for the full
fldigi WEFAX documentation, and
https://fldigi.sourceforge.io/xmlrpc/index.html for XML-RPC methods.
"""
from __future__ import annotations

import logging
import shutil
import socket
from datetime import datetime, timezone
from typing import AsyncIterator
from xmlrpc.client import ServerProxy, Fault, ProtocolError

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)


# HF WEFAX frequencies by region. The US NOAA fleet broadcasts on
# specific dial frequencies — SignalDeck matches against this list.
# Note: WEFAX uses USB with a 1.9 kHz audio carrier offset, so the
# "dial frequency" reported by the scanner is the USB suppressed-carrier.
HF_WEFAX_FREQUENCIES_HZ = [
    # NOAA Boston / Marshfield MA (NMF)
    4235_000,
    6340_500,
    9110_000,
    12750_000,
    # NOAA New Orleans LA (NMG)
    4317_900,
    8503_900,
    12789_900,
    17146_400,
    # NOAA Honolulu HI (KVM70)
    9982_500,
    11090_000,
    16135_000,
    23331_500,
    # NOAA Point Reyes CA (NMC) — decommissioned but still listed for
    # historical recordings
    4346_000,
    8682_000,
    12786_000,
    17151_200,
    22527_000,
]

# HF dial frequencies drift as the station's master oscillator warms up
# and as the propagation path shifts. A generous match window absorbs both.
_FREQ_TOLERANCE_HZ = 2_000


def tool_available() -> bool:
    """Return True if the fldigi binary is on PATH."""
    return shutil.which("fldigi") is not None


def _fldigi_xmlrpc_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if an fldigi XML-RPC server is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _frequency_in_wefax_band(freq_hz: float) -> bool:
    """Return True if the frequency is within tolerance of any known
    HF WEFAX station."""
    for nominal in HF_WEFAX_FREQUENCIES_HZ:
        if abs(freq_hz - nominal) <= _FREQ_TOLERANCE_HZ:
            return True
    return False


class FldigiWefaxDecoder(DecoderPlugin):
    """HF WEFAX decoder using fldigi's XML-RPC interface.

    This decoder is currently a **placeholder** — the actual audio
    routing between SignalDeck's PCM stream and fldigi's input is not
    yet wired up. When asked to decode, it detects whether fldigi is
    installed AND reachable via XML-RPC AND configured for WEFAX, and
    either returns a status-only DecoderResult or logs a setup warning.

    Once audio routing is in place, this decoder will:
    1. Tell fldigi to switch to WEFAX-IOC576 mode
    2. Start RX
    3. Block on `wefax.get_received_file()` until an image lands
    4. Yield a DecoderResult with the image path
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7362,
        image_dir: str = "data/images/wefax",
    ) -> None:
        self._host = host
        self._port = port
        self._image_dir = image_dir
        self._url = f"http://{host}:{port}/RPC2"

    @property
    def name(self) -> str:
        return "fldigi_wefax"

    @property
    def protocols(self) -> list[str]:
        return ["wefax"]

    @property
    def input_type(self) -> str:
        # Currently audio — will consume PCM from SignalDeck's audio
        # pipeline once routing is wired up.
        return "audio"

    def can_decode(self, signal: SignalInfo) -> float:
        if not tool_available():
            return 0.0
        if not _frequency_in_wefax_band(signal.frequency_hz):
            return 0.0
        # High confidence on a known HF WEFAX frequency.
        return 0.80

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        if not tool_available():
            logger.warning(
                "fldigi not installed — HF WEFAX decode skipped. "
                "Install with: sudo apt install fldigi"
            )
            return

        if not _fldigi_xmlrpc_reachable(self._host, self._port):
            logger.warning(
                "fldigi XML-RPC not reachable at %s:%d — start fldigi with "
                "`fldigi --xmlrpc-server-address %s --xmlrpc-server-port %d`",
                self._host,
                self._port,
                self._host,
                self._port,
            )
            return

        # Placeholder — try to set fldigi to WEFAX mode so the user can
        # at least see that this decoder reached fldigi. Full receive
        # loop requires audio routing that is not yet in place.
        try:
            proxy = ServerProxy(self._url)
            proxy.modem.set_by_name("WEFAX-IOC576")
            logger.info(
                "fldigi set to WEFAX-IOC576 for %.3f MHz (audio routing still manual)",
                signal.frequency_hz / 1e6,
            )
        except (Fault, ProtocolError, OSError) as e:
            logger.warning("fldigi XML-RPC call failed: %s", e)
            return

        # Return a status-only result so the dashboard shows something
        # happened. When audio routing lands, replace this with a real
        # wefax.get_received_file() loop + image parsing.
        yield DecoderResult(
            timestamp=datetime.now(timezone.utc),
            frequency=signal.frequency_hz,
            protocol="wefax",
            result_type="status",
            content={
                "message": "fldigi set to WEFAX-IOC576; audio routing not yet automated",
                "setup_required": True,
            },
            metadata={
                "decoder": "fldigi_wefax",
                "host": self._host,
                "port": self._port,
            },
        )

    async def decode_to_list(self, signal: SignalInfo, data_source) -> list[DecoderResult]:
        return [result async for result in self.decode(signal, data_source)]

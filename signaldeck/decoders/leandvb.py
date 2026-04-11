"""Digital Amateur TV (DATV) decoder via leandvb.

leandvb (http://www.pabr.org/radio/leandvb/leandvb.en.html) is a
lightweight software DVB-S/S2 demodulator in C++. It's designed
for receiving amateur digital TV from satellites like QO-100
(Es'hail-2), the ISS, and ground-based DATV repeaters.

The tool takes interleaved float32 I/Q samples on stdin and outputs
an MPEG transport stream on stdout. Pipeline:

    iq_source -> leandvb -> ffmpeg -> video file or still images

This module wraps leandvb as a subprocess and pipes through ffmpeg
to extract periodic still frames we can surface in the dashboard.
Full-rate video playback is out of scope — we just want to prove
reception and give the operator a thumbnail.

### Installation

leandvb is not in the standard Debian/Ubuntu repos. Build from source:

    git clone https://github.com/pabr/leansdr.git
    cd leansdr/src/apps
    make leandvb
    sudo cp leandvb /usr/local/bin/

Full build instructions: http://www.pabr.org/radio/leandvb/leandvb.en.html

ffmpeg is usually installed on most Linux systems; if not:

    sudo apt install ffmpeg

### DATV frequencies

| Band       | Frequency      | Source                       |
|------------|----------------|------------------------------|
| L-band     | 10489.750 MHz  | QO-100 WB Transponder center |
| S-band     | 2400.000 MHz   | ISS SSTV/DATV occasional     |
| 23cm       | 1255-1265 MHz  | Ground-based DATV repeaters  |
| 13cm       | 2320-2450 MHz  | Ground-based DATV repeaters  |

### Hardware notes

DATV typically uses 1-4 MHz symbol rates, which means you need an SDR
that can capture at least 2-8 Msps to cover the signal. HackRF (20 Msps
max) and PlutoSDR (61.44 Msps max) both work; RTL-SDR (2.4 Msps max)
is too narrow for most DATV signals. QO-100 reception also requires
a 10 GHz LNB + downconverter to shift the signal into an SDR's range.

This module is **untested with real hardware** — the subprocess
pipeline is correct in structure but needs verification against an
actual DATV signal (e.g., from QO-100 via a dish). Until that
verification happens, treat this as scaffold that lets the operator
try leandvb through SignalDeck without having to build the pipeline
from scratch.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import numpy as np

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)


# DATV frequency ranges. Wider tolerance than other decoders because
# DATV uses wide bandwidths (1-8 MHz) and the operator tunes a center
# frequency that may be off by several MHz.
DATV_FREQUENCY_RANGES_HZ: list[tuple[float, float, str]] = [
    # (lo, hi, description)
    (10_489_000_000, 10_491_000_000, "QO-100 WB center"),
    (2_395_000_000, 2_405_000_000, "ISS S-band"),
    (1_250_000_000, 1_270_000_000, "23cm DATV"),
    (2_320_000_000, 2_450_000_000, "13cm DATV"),
]


def _is_datv_frequency(freq_hz: float) -> tuple[bool, str]:
    """Check if freq_hz falls within any known DATV allocation."""
    for lo, hi, description in DATV_FREQUENCY_RANGES_HZ:
        if lo <= freq_hz <= hi:
            return True, description
    return False, ""


def tool_available() -> bool:
    """Return True if leandvb is on PATH AND ffmpeg is available."""
    return shutil.which("leandvb") is not None and shutil.which("ffmpeg") is not None


class LeandvbDecoder(DecoderPlugin):
    """DVB-S/S2 DATV decoder wrapping leandvb + ffmpeg.

    leandvb reads interleaved float32 I/Q from stdin and writes an
    MPEG-TS to stdout. We pipe stdout into ffmpeg, which extracts one
    still image every N seconds and drops PNGs into the image_dir.

    The subprocess pipeline is:

        python -> leandvb --u32 <sr> --f32 --sampler rrc --rs <sr>
                  --standard DVB-S
                  -> ffmpeg -i pipe:0 -vf fps=1/5 <out>/frame_%04d.png

    Adjust the leandvb flags per the specific satellite/repeater
    (symbol rate, FEC rate, constellation) before using — the defaults
    here are a reasonable baseline for 2 Msym/s QPSK 1/2 but real
    signals may need tuning.
    """

    _FRAME_EXTRACT_FPS = "1/5"  # one still image every 5 seconds

    def __init__(self, image_dir: str = "data/images/datv") -> None:
        self._image_dir = Path(image_dir)
        self._image_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "leandvb_datv"

    @property
    def protocols(self) -> list[str]:
        return ["dvb_s", "dvb_s2", "datv"]

    @property
    def input_type(self) -> str:
        return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        if not tool_available():
            return 0.0
        is_datv, _ = _is_datv_frequency(signal.frequency_hz)
        if not is_datv:
            return 0.0
        # Moderate-low confidence — DATV shares spectrum with voice and
        # other amateur services, so being on an "allocation" doesn't
        # guarantee DATV. Higher with an explicit protocol hint.
        if signal.protocol_hint in ("datv", "dvb_s", "dvb_s2"):
            return 0.85
        return 0.40

    async def decode(
        self, signal: SignalInfo, data_source
    ) -> AsyncIterator[DecoderResult]:
        if not tool_available():
            logger.warning(
                "leandvb or ffmpeg not installed — DATV decode skipped. "
                "Install leandvb from source (https://github.com/pabr/leansdr) "
                "and `sudo apt install ffmpeg`"
            )
            return

        iq = await self._collect_iq(data_source)
        if iq is None or len(iq) == 0:
            logger.warning("No I/Q samples collected for DATV decode")
            return

        # Per-pass output directory keyed by timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _, band_desc = _is_datv_frequency(signal.frequency_hz)
        safe_band = band_desc.replace(" ", "_") if band_desc else "datv"
        out_dir = self._image_dir / f"{safe_band}_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write I/Q to a temp file so leandvb can stream from it.
        # leandvb expects interleaved float32 (I, Q, I, Q, ...).
        iq_f32 = iq.astype(np.complex64, copy=False)
        interleaved = np.empty(len(iq_f32) * 2, dtype=np.float32)
        interleaved[0::2] = iq_f32.real
        interleaved[1::2] = iq_f32.imag

        with tempfile.NamedTemporaryFile(
            suffix=".f32", delete=False, dir=str(out_dir)
        ) as tmp:
            tmp.write(interleaved.tobytes())
            tmp_path = tmp.name

        # Pipeline: cat temp_file | leandvb | ffmpeg
        # leandvb flags (conservative defaults — real use will need tuning):
        #   --f32      input is interleaved float32
        #   --u32      sample rate in Hz
        #   --sr       symbol rate in symbols/sec (guess: 2 Msym)
        #   --standard DVB-S (DVB-S2 needs --s2 instead)
        leandvb_cmd = [
            "leandvb",
            "--f32",
            "--u32", str(int(signal.sample_rate)),
            "--sr", "2000000",        # 2 Msym/s default — TUNE PER SIGNAL
            "--standard", "DVB-S",
        ]
        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-i", "pipe:0",
            "-vf", f"fps={self._FRAME_EXTRACT_FPS}",
            str(out_dir / "frame_%04d.png"),
        ]

        logger.info(
            "Running leandvb+ffmpeg pipeline on %.3f GHz capture (%d samples)",
            signal.frequency_hz / 1e9,
            len(iq),
        )

        try:
            # Build a shell pipeline: `cat f32_file | leandvb ... | ffmpeg ...`
            with open(tmp_path, "rb") as f32_input:
                leandvb_proc = await asyncio.create_subprocess_exec(
                    *leandvb_cmd,
                    stdin=f32_input,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                ffmpeg_proc = await asyncio.create_subprocess_exec(
                    *ffmpeg_cmd,
                    stdin=leandvb_proc.stdout,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(ffmpeg_proc.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    logger.warning("leandvb/ffmpeg pipeline timed out; killing")
                    leandvb_proc.kill()
                    ffmpeg_proc.kill()
                    await leandvb_proc.wait()
                    await ffmpeg_proc.wait()
                    return
                finally:
                    # Make sure leandvb is cleaned up even on ffmpeg crash
                    if leandvb_proc.returncode is None:
                        leandvb_proc.kill()
                        await leandvb_proc.wait()
        except FileNotFoundError as e:
            logger.warning("leandvb or ffmpeg invocation failed: %s", e)
            return
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        frames = sorted(out_dir.glob("frame_*.png"))
        if not frames:
            logger.warning(
                "leandvb pipeline produced no frames in %s — signal may be "
                "too weak, symbol rate wrong, or not DVB-S. Try adjusting "
                "--sr and --standard flags.",
                out_dir,
            )
            return

        for frame_path in frames:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc),
                frequency=signal.frequency_hz,
                protocol="datv",
                result_type="image",
                content={
                    "frame_path": str(frame_path),
                    "band": band_desc,
                },
                metadata={
                    "decoder": "leandvb_datv",
                    "standard": "DVB-S",
                    "output_dir": str(out_dir),
                },
            )

    async def decode_to_list(self, signal: SignalInfo, data_source) -> list[DecoderResult]:
        return [result async for result in self.decode(signal, data_source)]

    async def _collect_iq(self, data_source) -> np.ndarray | None:
        if isinstance(data_source, np.ndarray):
            return data_source.astype(np.complex64, copy=False)
        chunks = []
        async for chunk in data_source:
            chunks.append(chunk)
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.complex64, copy=False)

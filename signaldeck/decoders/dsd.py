"""DSD-FME decoder for DMR, D-STAR, and NXDN digital voice protocols."""

import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for dsd-fme stderr output
# ---------------------------------------------------------------------------

# DMR sync line: "Sync: +DMR [slot1] slot2 | Color Code=01 | CSBK"
_DMR_SYNC = re.compile(r"Sync:.*DMR.*Color Code=(\d+)", re.IGNORECASE)

# DMR talkgroup grant: " Talkgroup Voice Channel Grant (TV_GRANT)"
_DMR_GRANT = re.compile(r"Talkgroup.*Grant", re.IGNORECASE)

# DMR LPCN/TS/Target/Source line
_DMR_TARGET_SOURCE = re.compile(
    r"LPCN:\s*(\d+);\s*TS:\s*(\d+);\s*Target:\s*(\d+)\s*-\s*Source:\s*(\d+)",
    re.IGNORECASE,
)

# D-STAR header line: "D-STAR Header: MY=W3ADO    YOUR=CQCQCQ  RPT1=W3ADO B RPT2=W3ADO G"
_DSTAR_HEADER = re.compile(
    r"D-STAR Header:\s*MY=(\S+)\s+YOUR=(\S+)\s+RPT1=(\S.*?)\s+RPT2=(\S.*?)$",
    re.IGNORECASE,
)

# NXDN line: "NXDN48: RAN=01 CC=001 TG=12345"
_NXDN = re.compile(r"NXDN\d*:\s*RAN=(\d+)\s+CC=(\d+)\s+TG=(\d+)", re.IGNORECASE)


def parse_dsd_stderr_line(line: str) -> dict | None:
    """Parse a single line of dsd-fme stderr output.

    Returns a dict of decoded fields, or None if the line is not recognised.
    """
    if not line or not line.strip():
        return None

    # DMR sync with color code
    m = _DMR_SYNC.search(line)
    if m:
        return {"protocol": "dmr", "type": "sync", "color_code": m.group(1)}

    # DMR talkgroup grant
    m = _DMR_GRANT.search(line)
    if m:
        return {"protocol": "dmr", "type": "grant"}

    # DMR LPCN / TS / Target / Source
    m = _DMR_TARGET_SOURCE.search(line)
    if m:
        lpcn, ts, target, source = m.groups()
        return {
            "protocol": "dmr",
            "type": "traffic",
            "lpcn": lpcn,
            "ts": ts,
            "target": target,
            "source": source,
        }

    # D-STAR header
    m = _DSTAR_HEADER.search(line)
    if m:
        my, your, rpt1, rpt2 = m.groups()
        return {
            "protocol": "dstar",
            "type": "header",
            "my_callsign": my.strip(),
            "your_callsign": your.strip(),
            "rpt1": rpt1.strip(),
            "rpt2": rpt2.strip(),
        }

    # NXDN
    m = _NXDN.search(line)
    if m:
        ran, cc, tg = m.groups()
        return {"protocol": "nxdn", "type": "frame", "ran": ran, "cc": cc, "tg": tg}

    return None


# ---------------------------------------------------------------------------
# Decoder class
# ---------------------------------------------------------------------------

class DsdDecoder(DecoderPlugin):
    """Wraps dsd-fme to decode DMR, D-STAR, and NXDN digital voice frames.

    Audio is collected from the data_source, written to a temporary WAV file,
    then passed to dsd-fme with ``-fa -i file.wav -o decoded.wav -N``.
    Stderr is captured and parsed line-by-line for diagnostic frame data.
    """

    def __init__(self, recording_dir: str | None = None) -> None:
        self._recording_dir = Path(recording_dir) if recording_dir else None

    # ------------------------------------------------------------------
    # DecoderPlugin interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "dsd"

    @property
    def protocols(self) -> list[str]:
        return ["dmr", "dstar", "nxdn"]

    @property
    def input_type(self) -> str:
        return "audio"

    def tool_available(self) -> bool:
        """Return True if dsd-fme is on PATH."""
        return shutil.which("dsd-fme") is not None

    def can_decode(self, signal: SignalInfo) -> float:
        """Return a confidence score for whether DSD-FME can handle this signal.

        Scoring:
          0.9  – protocol_hint is one of dmr / dstar / nxdn
          0.3  – narrowband FM in VHF/UHF (12.5 kHz or 25 kHz channel)
          0.0  – wideband or unrelated signal
        """
        hint = signal.protocol_hint.lower() if signal.protocol_hint else ""

        if hint in ("dmr", "dstar", "nxdn"):
            return 0.9

        # Narrowband digital signals in VHF/UHF bands
        if (
            signal.modulation.upper() == "FM"
            and signal.bandwidth_hz <= 25_000
            and hint not in ("broadcast_fm",)
        ):
            freq = signal.frequency_hz
            # VHF (136-174 MHz) or UHF (400-512 MHz) land-mobile bands
            if (136e6 <= freq <= 174e6) or (400e6 <= freq <= 512e6):
                return 0.3
            if hint == "narrowband_fm":
                return 0.3

        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        """Collect audio, write a WAV file, run dsd-fme, yield DecoderResults.

        Stderr from dsd-fme is parsed for frame diagnostics.  One
        DecoderResult is yielded per recognised frame line found in stderr,
        plus a summary result after the process completes.
        """
        import asyncio
        import numpy as np
        from signaldeck.engine.audio_pipeline import save_audio_wav

        if not self.tool_available():
            logger.error("dsd-fme is not installed; cannot decode digital voice")
            return

        # Collect all audio chunks into a single array
        chunks: list[np.ndarray] = []
        async for audio_chunk in data_source:
            chunks.append(np.asarray(audio_chunk, dtype=np.float32))

        if not chunks:
            logger.warning("DsdDecoder received no audio data")
            return

        audio = np.concatenate(chunks)

        # Write audio to a temporary WAV file
        tmp_dir = self._recording_dir or Path(tempfile.gettempdir())
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        wav_in = tmp_dir / f"dsd_in_{ts_str}.wav"
        wav_out = tmp_dir / f"dsd_out_{ts_str}.wav"

        save_audio_wav(audio, str(wav_in), sample_rate=48000)

        # Run dsd-fme, capturing stderr for frame diagnostics
        cmd = [
            "dsd-fme",
            "-fa",
            "-i", str(wav_in),
            "-o", str(wav_out),
            "-N",
        ]

        logger.debug("Running: %s", " ".join(cmd))

        frames: list[dict] = []
        stderr_lines: list[str] = []

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_bytes = await proc.communicate()
            stderr_text = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

            for raw_line in stderr_text.splitlines():
                stderr_lines.append(raw_line)
                parsed = parse_dsd_stderr_line(raw_line)
                if parsed:
                    frames.append(parsed)

        except OSError as exc:
            logger.error("Failed to launch dsd-fme: %s", exc)
            return
        finally:
            # Clean up input WAV; keep output WAV only if recording_dir is set
            try:
                wav_in.unlink(missing_ok=True)
            except Exception:
                pass
            if not self._recording_dir:
                try:
                    wav_out.unlink(missing_ok=True)
                except Exception:
                    pass

        # Yield one DecoderResult per decoded frame
        now = datetime.now(timezone.utc)
        for frame in frames:
            yield DecoderResult(
                timestamp=now,
                frequency=signal.frequency_hz,
                protocol=frame.get("protocol", "dsd"),
                result_type=frame.get("type", "frame"),
                content=frame,
                audio_path=str(wav_out) if self._recording_dir else None,
                metadata={
                    "strength": signal.peak_power,
                    "bandwidth_hz": signal.bandwidth_hz,
                },
            )

        # If no frames were decoded, still yield a summary so the caller
        # knows the decoder ran and what dsd-fme reported.
        if not frames:
            yield DecoderResult(
                timestamp=now,
                frequency=signal.frequency_hz,
                protocol="dsd",
                result_type="summary",
                content={"frames_decoded": 0, "stderr_lines": len(stderr_lines)},
                audio_path=str(wav_out) if self._recording_dir else None,
                metadata={"strength": signal.peak_power},
            )

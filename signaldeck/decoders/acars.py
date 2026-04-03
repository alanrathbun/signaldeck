import json
import logging
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator
from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

# Known ACARS VHF frequencies in Hz
ACARS_FREQS_HZ = [
    130.025e6,
    130.450e6,
    131.125e6,
    131.525e6,
    131.550e6,
    131.725e6,
    131.825e6,
    136.900e6,
]
ACARS_FREQ_TOLERANCE_HZ = 15_000.0


def parse_acars_json(line: str) -> dict | None:
    if not line.strip():
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


class AcarsDecoder(DecoderPlugin):
    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()

    @property
    def name(self) -> str:
        return "acars"

    @property
    def protocols(self) -> list[str]:
        return ["acars"]

    @property
    def input_type(self) -> str:
        return "iq"

    def tool_available(self) -> bool:
        return shutil.which("acarsdec") is not None

    def can_decode(self, signal: SignalInfo) -> float:
        if signal.protocol_hint == "acars":
            return 0.95
        for freq in ACARS_FREQS_HZ:
            if abs(signal.frequency_hz - freq) <= ACARS_FREQ_TOLERANCE_HZ:
                return 0.85
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        if not self.tool_available():
            logger.error("acarsdec not installed")
            return
        import tempfile
        import os
        import wave
        import struct
        import numpy as np

        chunks = []
        async for chunk in data_source:
            chunks.append(chunk)
        if not chunks:
            return

        iq_data = np.concatenate(chunks)

        # AM demodulate: magnitude of complex IQ
        am_audio = np.abs(iq_data)
        # Normalise to [-1, 1]
        peak = np.max(np.abs(am_audio)) or 1.0
        am_audio = (am_audio / peak) * 2.0 - 1.0

        # Convert to 16-bit PCM
        pcm = np.clip(am_audio * 32767, -32768, 32767).astype(np.int16)

        sample_rate = int(getattr(signal, "sample_rate", 2_000_000))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())

            results = []

            async def on_line(line: str) -> None:
                parsed = parse_acars_json(line)
                if parsed:
                    results.append(parsed)

            config = ProcessConfig(
                command=[
                    "acarsdec",
                    "--sndfile", wav_path,
                    "--output", "json:file:path=/dev/stdout",
                ],
                name="acarsdec",
            )
            await self._supervisor.run_once(config, on_output=on_line, timeout=60.0)

            for parsed in results:
                yield DecoderResult(
                    timestamp=datetime.now(timezone.utc),
                    frequency=signal.frequency_hz,
                    protocol="acars",
                    result_type="data",
                    content=parsed,
                    metadata={
                        "tail": parsed.get("tail"),
                        "flight": parsed.get("flight"),
                        "label": parsed.get("label"),
                    },
                )
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    async def start_monitoring(
        self,
        frequencies_hz: list[float],
        on_result,
        rtlsdr_index: int = 0,
    ) -> None:
        """Start long-running acarsdec monitoring via RTL-SDR."""
        freq_mhz_args = [str(f / 1e6) for f in frequencies_hz]
        command = [
            "acarsdec",
            "--rtlsdr", str(rtlsdr_index),
            "--output", "json:file:path=/dev/stdout",
        ] + freq_mhz_args

        async def on_line(line: str) -> None:
            parsed = parse_acars_json(line)
            if parsed:
                result = DecoderResult(
                    timestamp=datetime.now(timezone.utc),
                    frequency=parsed.get("freq", 0) * 1e6,
                    protocol="acars",
                    result_type="data",
                    content=parsed,
                    metadata={
                        "tail": parsed.get("tail"),
                        "flight": parsed.get("flight"),
                        "label": parsed.get("label"),
                    },
                )
                await on_result(result)

        config = ProcessConfig(command=command, name="acarsdec_monitor")
        await self._supervisor.start_process(config, on_output=on_line)

    async def stop(self) -> None:
        await self._supervisor.stop_all()

import logging
import re
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator
from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

_POCSAG_PATTERN = re.compile(
    r"POCSAG(\d+):\s+Address:\s*(\d+)\s+Function:\s*(\d+)\s+(Alpha|Numeric|Tone Only):\s*(.*)"
)
_FLEX_PATTERN = re.compile(r"FLEX:\s+(\S+)\s+(\S+)\s+\[(\d+)\]\s+(\S+)\s+(.*)")

def parse_multimon_pocsag(line: str) -> dict | None:
    if not line.strip():
        return None
    match = _POCSAG_PATTERN.match(line)
    if match:
        baud, address, function, msg_type, message = match.groups()
        return {"protocol": "pocsag", "baud": int(baud), "address": address.strip(),
                "function": int(function), "type": msg_type.lower().replace(" ", "_"),
                "message": message.strip()}
    match = _FLEX_PATTERN.match(line)
    if match:
        mode, capcode_group, address, msg_type, message = match.groups()
        return {"protocol": "flex", "mode": mode, "address": address.strip(),
                "type": msg_type.lower(), "message": message.strip()}
    return None

class PocsagDecoder(DecoderPlugin):
    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()

    @property
    def name(self) -> str:
        return "pocsag"

    @property
    def protocols(self) -> list[str]:
        return ["pocsag", "flex"]

    @property
    def input_type(self) -> str:
        return "audio"

    def tool_available(self) -> bool:
        return shutil.which("multimon-ng") is not None

    def can_decode(self, signal: SignalInfo) -> float:
        if signal.protocol_hint in ("pocsag", "flex"):
            return 0.9
        if signal.modulation.upper() == "FM" and signal.bandwidth_hz <= 25000:
            freq = signal.frequency_hz
            if 148e6 <= freq <= 174e6 or 450e6 <= freq <= 470e6:
                return 0.4
            if signal.protocol_hint == "narrowband_fm":
                return 0.3
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        if not self.tool_available():
            logger.error("multimon-ng not installed")
            return
        import numpy as np
        from scipy.signal import resample_poly
        from math import gcd
        config = ProcessConfig(
            command=["multimon-ng", "-t", "raw", "-a", "POCSAG512", "-a", "POCSAG1200",
                     "-a", "POCSAG2400", "-a", "FLEX", "-f", "alpha", "-"],
            name="multimon_pocsag", stdin_pipe=True,
        )
        results = []
        async def on_line(line: str):
            parsed = parse_multimon_pocsag(line)
            if parsed:
                results.append(parsed)
        managed = await self._supervisor.start_process(config, on_output=on_line)
        async for audio_chunk in data_source:
            divisor = gcd(48000, 22050)
            up = 22050 // divisor
            down = 48000 // divisor
            resampled = resample_poly(audio_chunk, up, down).astype(np.float32)
            pcm16 = (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16)
            await self._supervisor.write_stdin("multimon_pocsag", pcm16.tobytes())
        await self._supervisor.stop_process("multimon_pocsag")
        for parsed in results:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc), frequency=signal.frequency_hz,
                protocol=parsed["protocol"], result_type="text", content=parsed,
                metadata={"address": parsed.get("address", ""), "strength": signal.peak_power},
            )

    async def stop(self) -> None:
        await self._supervisor.stop_all()

import json
import logging
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator
from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.decoders.supervisor import ProcessSupervisor, ProcessConfig

logger = logging.getLogger(__name__)

def parse_rtl433_json(line: str) -> dict | None:
    if not line.strip(): return None
    try: return json.loads(line)
    except json.JSONDecodeError: return None

class IsmDecoder(DecoderPlugin):
    def __init__(self) -> None:
        self._supervisor = ProcessSupervisor()

    @property
    def name(self) -> str: return "ism"
    @property
    def protocols(self) -> list[str]: return ["rtl433"]
    @property
    def input_type(self) -> str: return "iq"

    def tool_available(self) -> bool:
        return shutil.which("rtl_433") is not None

    def can_decode(self, signal: SignalInfo) -> float:
        if signal.protocol_hint == "ism": return 0.9
        if 430e6 <= signal.frequency_hz <= 440e6: return 0.7
        if 902e6 <= signal.frequency_hz <= 928e6: return 0.7
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        if not self.tool_available():
            logger.error("rtl_433 not installed")
            return
        import tempfile, os, numpy as np
        chunks = []
        async for chunk in data_source:
            chunks.append(chunk)
        if not chunks: return
        iq_data = np.concatenate(chunks)
        i_u8 = np.clip((np.real(iq_data) + 1.0) * 127.5, 0, 255).astype(np.uint8)
        q_u8 = np.clip((np.imag(iq_data) + 1.0) * 127.5, 0, 255).astype(np.uint8)
        interleaved = np.empty(len(iq_data) * 2, dtype=np.uint8)
        interleaved[0::2] = i_u8
        interleaved[1::2] = q_u8
        with tempfile.NamedTemporaryFile(suffix=".cu8", delete=False) as tmp:
            tmp.write(interleaved.tobytes())
            tmp_path = tmp.name
        config = ProcessConfig(
            command=["rtl_433", "-r", tmp_path, "-F", "json", "-s", str(int(signal.sample_rate))],
            name="rtl_433",
        )
        results = []
        async def on_line(line: str):
            parsed = parse_rtl433_json(line)
            if parsed: results.append(parsed)
        await self._supervisor.run_once(config, on_output=on_line, timeout=30.0)
        try: os.unlink(tmp_path)
        except OSError: pass
        for parsed in results:
            yield DecoderResult(
                timestamp=datetime.now(timezone.utc), frequency=signal.frequency_hz,
                protocol="rtl433", result_type="data", content=parsed,
                metadata={"model": parsed.get("model", "unknown"), "id": parsed.get("id")},
            )

    async def stop(self) -> None:
        await self._supervisor.stop_all()

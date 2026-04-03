import logging
from typing import AsyncIterator
from signaldeck.decoders.base import DecoderPlugin, DecoderResult, SignalInfo
from signaldeck.engine.audio_pipeline import fm_demodulate, am_demodulate, AudioRecorder

logger = logging.getLogger(__name__)


class FmAmDecoder(DecoderPlugin):
    def __init__(self, recording_dir: str = "data/recordings") -> None:
        self._recording_dir = recording_dir

    @property
    def name(self) -> str: return "fm_am"

    @property
    def protocols(self) -> list[str]: return ["fm", "am"]

    @property
    def input_type(self) -> str: return "iq"

    def can_decode(self, signal: SignalInfo) -> float:
        mod = signal.modulation.upper()
        hint = signal.protocol_hint
        if mod == "FM" and hint in ("broadcast_fm", "narrowband_fm", "weather_radio", ""):
            return 0.7
        if mod == "AM" and hint in ("aviation", ""):
            return 0.7
        if mod == "UNKNOWN" and hint == "":
            if 25e6 <= signal.frequency_hz <= 512e6:
                return 0.2
        return 0.0

    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]:
        import numpy as np
        from datetime import datetime, timezone
        mod = signal.modulation.upper()
        is_am = (mod == "AM" or signal.protocol_hint == "aviation")
        recorder = AudioRecorder(output_dir=self._recording_dir, sample_rate=48000)
        label = f"{signal.frequency_hz / 1e6:.3f}MHz_{'am' if is_am else 'fm'}"
        audio_path = recorder.start(label)
        total_samples = 0
        async for iq_chunk in data_source:
            if is_am:
                audio = am_demodulate(iq_chunk, sample_rate=signal.sample_rate, audio_rate=48000)
            else:
                audio = fm_demodulate(iq_chunk, sample_rate=signal.sample_rate, audio_rate=48000)
            recorder.write(audio)
            total_samples += len(audio)
        recorder.stop()
        duration = total_samples / 48000.0
        yield DecoderResult(
            timestamp=datetime.now(timezone.utc),
            frequency=signal.frequency_hz,
            protocol="am" if is_am else "fm",
            result_type="voice",
            content={"modulation": "AM" if is_am else "FM", "duration_s": round(duration, 2), "sample_count": total_samples},
            audio_path=audio_path,
            metadata={"strength": signal.peak_power, "bandwidth_hz": signal.bandwidth_hz},
        )

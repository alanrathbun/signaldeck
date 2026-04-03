import logging
from signaldeck.decoders.base import DecoderPlugin, SignalInfo

logger = logging.getLogger(__name__)

class DecoderRegistry:
    def __init__(self) -> None:
        self._decoders: dict[str, DecoderPlugin] = {}

    def register(self, decoder: DecoderPlugin) -> None:
        self._decoders[decoder.name] = decoder

    def list_decoders(self) -> list[DecoderPlugin]:
        return list(self._decoders.values())

    def get(self, name: str) -> DecoderPlugin | None:
        return self._decoders.get(name)

    def find_decoders(self, signal: SignalInfo, min_confidence: float = 0.01) -> list[tuple[DecoderPlugin, float]]:
        matches = []
        for decoder in self._decoders.values():
            confidence = decoder.can_decode(signal)
            if confidence >= min_confidence:
                matches.append((decoder, confidence))
        matches.sort(key=lambda m: m[1], reverse=True)
        return matches

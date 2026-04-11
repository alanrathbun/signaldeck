from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator


@dataclass
class SignalInfo:
    frequency_hz: float
    bandwidth_hz: float
    peak_power: float
    modulation: str
    sample_rate: float = 2_000_000
    protocol_hint: str = ""
    signal_class: str = "unknown"
    content_confidence: float = 0.0
    signal_features: dict = field(default_factory=dict)


@dataclass
class DecoderResult:
    timestamp: datetime
    frequency: float
    protocol: str
    result_type: str
    content: dict
    audio_path: str | None = None
    metadata: dict = field(default_factory=dict)


class DecoderPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def protocols(self) -> list[str]: ...

    @property
    @abstractmethod
    def input_type(self) -> str: ...

    @abstractmethod
    def can_decode(self, signal: SignalInfo) -> float: ...

    @abstractmethod
    async def decode(self, signal: SignalInfo, data_source) -> AsyncIterator[DecoderResult]: ...

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

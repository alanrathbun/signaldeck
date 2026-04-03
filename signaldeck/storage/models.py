from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Signal:
    frequency: float          # Hz
    bandwidth: float          # Hz
    modulation: str           # "FM", "AM", "4FSK", "unknown", etc.
    protocol: str | None      # "p25", "dmr", None if unidentified
    first_seen: datetime
    last_seen: datetime
    hit_count: int
    avg_strength: float       # dBFS
    confidence: float         # 0.0-1.0
    id: int | None = None
    classification_data: dict = field(default_factory=dict)


@dataclass
class ActivityEntry:
    signal_id: int
    timestamp: datetime
    duration: float           # seconds
    strength: float           # dBFS
    decoder_used: str | None
    result_type: str          # "unknown", "voice", "data", "position", etc.
    summary: str
    id: int | None = None
    audio_path: str | None = None
    raw_result: dict = field(default_factory=dict)


@dataclass
class Bookmark:
    frequency: float          # Hz
    label: str
    modulation: str
    decoder: str | None
    priority: int             # 1-5
    camp_on_active: bool
    notes: str = ""
    id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

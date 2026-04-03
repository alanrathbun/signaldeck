import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BandProfile:
    """Statistical profile for a frequency band."""
    power_samples: list[float] = field(default_factory=list)
    bandwidth_samples: list[float] = field(default_factory=list)
    modulation_counts: dict[str, int] = field(default_factory=dict)
    observation_count: int = 0

    @property
    def power_mean(self) -> float:
        return np.mean(self.power_samples) if self.power_samples else 0.0

    @property
    def power_std(self) -> float:
        return np.std(self.power_samples) if len(self.power_samples) > 1 else 10.0

    @property
    def primary_modulation(self) -> str:
        if not self.modulation_counts:
            return "unknown"
        return max(self.modulation_counts, key=self.modulation_counts.get)

    def to_dict(self) -> dict:
        return {
            "power_samples": self.power_samples[-100:],  # keep last 100
            "bandwidth_samples": self.bandwidth_samples[-100:],
            "modulation_counts": self.modulation_counts,
            "observation_count": self.observation_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BandProfile":
        return cls(
            power_samples=data.get("power_samples", []),
            bandwidth_samples=data.get("bandwidth_samples", []),
            modulation_counts=data.get("modulation_counts", {}),
            observation_count=data.get("observation_count", 0),
        )


class AnomalyDetector:
    """Detects anomalous signals by comparing against learned band profiles.

    Maintains a statistical profile per frequency band (power distribution,
    typical modulation, bandwidth). Flags signals that deviate significantly
    from the learned normal.
    """

    def __init__(self, anomaly_threshold: float = 2.5) -> None:
        self._profiles: dict[str, BandProfile] = {}
        self._threshold = anomaly_threshold

    @property
    def num_profiles(self) -> int:
        return len(self._profiles)

    def update(self, band_name: str, power: float, bandwidth: float, modulation: str) -> None:
        """Update the profile for a frequency band with a new observation."""
        if band_name not in self._profiles:
            self._profiles[band_name] = BandProfile()

        profile = self._profiles[band_name]
        profile.power_samples.append(power)
        profile.bandwidth_samples.append(bandwidth)
        profile.modulation_counts[modulation] = profile.modulation_counts.get(modulation, 0) + 1
        profile.observation_count += 1

        # Keep rolling window
        if len(profile.power_samples) > 200:
            profile.power_samples = profile.power_samples[-100:]
        if len(profile.bandwidth_samples) > 200:
            profile.bandwidth_samples = profile.bandwidth_samples[-100:]

    def check(
        self, band_name: str, power: float, bandwidth: float, modulation: str
    ) -> tuple[bool, float, list[str]]:
        """Check if a signal is anomalous.

        Returns:
            (is_anomaly, anomaly_score, reasons) tuple.
            anomaly_score is 0.0 (normal) to 1.0 (highly anomalous).
        """
        reasons = []
        scores = []

        if band_name not in self._profiles:
            return True, 0.8, ["New/unknown frequency band"]

        profile = self._profiles[band_name]

        if profile.observation_count < 5:
            return False, 0.0, []

        # Power anomaly
        z_power = abs(power - profile.power_mean) / max(profile.power_std, 0.1)
        if z_power > self._threshold:
            reasons.append(f"Unusual power level ({power:.1f} dBFS, expected ~{profile.power_mean:.1f})")
            scores.append(min(z_power / 5.0, 1.0))

        # Modulation anomaly
        if modulation not in profile.modulation_counts:
            reasons.append(f"New modulation type '{modulation}' (expected {profile.primary_modulation})")
            scores.append(0.7)

        # Bandwidth anomaly
        if profile.bandwidth_samples:
            bw_mean = np.mean(profile.bandwidth_samples)
            bw_std = max(np.std(profile.bandwidth_samples), 100)
            z_bw = abs(bandwidth - bw_mean) / bw_std
            if z_bw > self._threshold:
                reasons.append(f"Unusual bandwidth ({bandwidth:.0f} Hz, expected ~{bw_mean:.0f})")
                scores.append(min(z_bw / 5.0, 1.0))

        if not scores:
            return False, 0.0, []

        anomaly_score = max(scores)
        return anomaly_score > 0.5, anomaly_score, reasons

    def save(self, path: str) -> None:
        """Save profiles to JSON."""
        data = {name: p.to_dict() for name, p in self._profiles.items()}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved %d band profiles to %s", len(data), path)

    def load(self, path: str) -> None:
        """Load profiles from JSON."""
        with open(path) as f:
            data = json.load(f)
        self._profiles = {name: BandProfile.from_dict(d) for name, d in data.items()}
        logger.info("Loaded %d band profiles from %s", len(self._profiles), path)

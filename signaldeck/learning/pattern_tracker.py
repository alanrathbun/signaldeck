import json
import logging
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


class PatternTracker:
    """Tracks frequency activity patterns using a 7×24 matrix per signal.

    Each cell represents (day_of_week, hour_of_day) and stores
    cumulative activity minutes and observation count.
    """

    def __init__(self) -> None:
        # signal_id -> (7×24 activity_minutes, 7×24 observation_count)
        self._matrices: dict[int, tuple[NDArray[np.float64], NDArray[np.int32]]] = {}

    @property
    def num_signals(self) -> int:
        return len(self._matrices)

    def record(self, signal_id: int, timestamp: datetime, duration_minutes: float) -> None:
        """Record signal activity at a given time."""
        if signal_id not in self._matrices:
            self._matrices[signal_id] = (
                np.zeros((7, 24), dtype=np.float64),
                np.zeros((7, 24), dtype=np.int32),
            )

        day = timestamp.weekday()  # 0=Monday
        hour = timestamp.hour

        activity, counts = self._matrices[signal_id]
        activity[day, hour] += duration_minutes
        counts[day, hour] += 1

    def get_matrix(self, signal_id: int) -> NDArray[np.float64]:
        """Get the 7×24 activity matrix for a signal.

        Returns activity minutes per (day, hour) cell.
        """
        if signal_id not in self._matrices:
            return np.zeros((7, 24), dtype=np.float64)
        return self._matrices[signal_id][0].copy()

    def get_likelihood(self, signal_id: int, timestamp: datetime) -> float:
        """Get likelihood (0-1) that a signal is active at the given time.

        Based on historical activity for this day-of-week and hour.
        """
        if signal_id not in self._matrices:
            return 0.0

        day = timestamp.weekday()
        hour = timestamp.hour
        activity, counts = self._matrices[signal_id]

        if counts[day, hour] == 0:
            return 0.0

        # Normalize: activity minutes / max activity across all cells
        max_activity = np.max(activity)
        if max_activity == 0:
            return 0.0

        return min(activity[day, hour] / max_activity, 1.0)

    def get_active_signals(
        self, timestamp: datetime, min_likelihood: float = 0.3
    ) -> list[tuple[int, float]]:
        """Get signals likely active at the given time.

        Returns:
            List of (signal_id, likelihood) tuples, sorted by likelihood descending.
        """
        results = []
        for signal_id in self._matrices:
            likelihood = self.get_likelihood(signal_id, timestamp)
            if likelihood >= min_likelihood:
                results.append((signal_id, likelihood))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def save(self, path: str) -> None:
        """Save patterns to JSON."""
        data = {}
        for signal_id, (activity, counts) in self._matrices.items():
            data[str(signal_id)] = {
                "activity": activity.tolist(),
                "counts": counts.tolist(),
            }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved patterns for %d signals", len(data))

    def load(self, path: str) -> None:
        """Load patterns from JSON."""
        with open(path) as f:
            data = json.load(f)
        self._matrices = {}
        for signal_id_str, matrices in data.items():
            self._matrices[int(signal_id_str)] = (
                np.array(matrices["activity"], dtype=np.float64),
                np.array(matrices["counts"], dtype=np.int32),
            )
        logger.info("Loaded patterns for %d signals", len(self._matrices))

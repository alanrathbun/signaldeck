import logging
from typing import Iterator

from signaldeck.storage.models import Bookmark

logger = logging.getLogger(__name__)


class BookmarkMonitor:
    """Cycles through bookmarked frequencies based on priority.

    Higher priority bookmarks are visited more frequently.
    Priority 5 is visited 5x as often as priority 1.
    """

    def __init__(self, bookmarks: list[Bookmark], dwell_time_s: float = 1.0) -> None:
        self._bookmarks = sorted(bookmarks, key=lambda b: b.priority, reverse=True)
        self._dwell_time = dwell_time_s
        self._schedule = self._build_schedule()
        self._index = 0

    @property
    def num_bookmarks(self) -> int:
        return len(self._bookmarks)

    def _build_schedule(self) -> list[float]:
        """Build a weighted frequency schedule.

        Higher priority bookmarks appear more times in the cycle.
        """
        schedule = []
        for bk in self._bookmarks:
            # Repeat proportional to priority
            schedule.extend([bk.frequency] * bk.priority)
        return schedule

    def get_schedule(self) -> list[float]:
        """Return the current scan schedule."""
        return list(self._schedule)

    def get_next_frequency(self) -> float | None:
        """Get the next frequency to monitor."""
        if not self._schedule:
            return None
        freq = self._schedule[self._index % len(self._schedule)]
        self._index += 1
        return freq

    def get_bookmark_for_frequency(self, frequency: float) -> Bookmark | None:
        """Look up the bookmark for a given frequency."""
        for bk in self._bookmarks:
            if abs(bk.frequency - frequency) < 1000:
                return bk
        return None

    def update_bookmarks(self, bookmarks: list[Bookmark]) -> None:
        """Update the bookmark list and rebuild schedule."""
        self._bookmarks = sorted(bookmarks, key=lambda b: b.priority, reverse=True)
        self._schedule = self._build_schedule()
        self._index = 0
        logger.info("Bookmark monitor updated with %d bookmarks", len(bookmarks))

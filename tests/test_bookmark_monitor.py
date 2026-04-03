import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from signaldeck.engine.bookmark_monitor import BookmarkMonitor
from signaldeck.storage.models import Bookmark


def _make_bookmarks():
    return [
        Bookmark(id=1, frequency=162_400_000, label="NOAA Weather", modulation="FM",
                 decoder="weather_radio", priority=5, camp_on_active=True),
        Bookmark(id=2, frequency=460_500_000, label="Local Repeater", modulation="FM",
                 decoder=None, priority=3, camp_on_active=False),
        Bookmark(id=3, frequency=144_390_000, label="APRS", modulation="FM",
                 decoder="aprs", priority=4, camp_on_active=False),
    ]


def test_bookmark_monitor_init():
    bookmarks = _make_bookmarks()
    monitor = BookmarkMonitor(bookmarks=bookmarks, dwell_time_s=1.0)
    assert monitor.num_bookmarks == 3


def test_bookmark_ordering_by_priority():
    """Higher priority bookmarks are visited more often."""
    bookmarks = _make_bookmarks()
    monitor = BookmarkMonitor(bookmarks=bookmarks, dwell_time_s=0.5)
    schedule = monitor.get_schedule()
    # Priority 5 bookmark should appear more often
    count_5 = sum(1 for f in schedule if f == 162_400_000)
    count_3 = sum(1 for f in schedule if f == 460_500_000)
    assert count_5 >= count_3


def test_get_next_frequency():
    bookmarks = _make_bookmarks()
    monitor = BookmarkMonitor(bookmarks=bookmarks, dwell_time_s=0.5)
    # Should cycle through frequencies
    seen = set()
    for _ in range(10):
        freq = monitor.get_next_frequency()
        seen.add(freq)
    # Should have visited all bookmarks
    assert len(seen) == 3


def test_empty_bookmarks():
    monitor = BookmarkMonitor(bookmarks=[], dwell_time_s=1.0)
    assert monitor.num_bookmarks == 0
    assert monitor.get_next_frequency() is None

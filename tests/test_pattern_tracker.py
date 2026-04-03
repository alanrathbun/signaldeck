from datetime import datetime, timezone

import numpy as np
import pytest

from signaldeck.learning.pattern_tracker import PatternTracker


def test_tracker_starts_empty():
    tracker = PatternTracker()
    assert tracker.num_signals == 0


def test_record_activity():
    tracker = PatternTracker()
    dt = datetime(2026, 4, 3, 14, 30, tzinfo=timezone.utc)  # Thursday 2PM
    tracker.record(signal_id=1, timestamp=dt, duration_minutes=5.0)
    assert tracker.num_signals == 1


def test_get_activity_matrix():
    tracker = PatternTracker()
    # Record activity on Thursday at 2PM
    dt = datetime(2026, 4, 2, 14, 30, tzinfo=timezone.utc)  # Thursday
    for _ in range(5):
        tracker.record(signal_id=1, timestamp=dt, duration_minutes=2.0)
    matrix = tracker.get_matrix(signal_id=1)
    assert matrix.shape == (7, 24)
    # Thursday = day 3, hour 14 should have activity
    assert matrix[3, 14] > 0


def test_get_likelihood():
    """Likelihood for a time when signal is usually active should be high."""
    tracker = PatternTracker()
    # Record lots of activity on Monday at 9AM
    for _ in range(20):
        dt = datetime(2026, 3, 30, 9, 0, tzinfo=timezone.utc)  # Monday
        tracker.record(signal_id=1, timestamp=dt, duration_minutes=10.0)
    # Monday 9AM should have high likelihood
    monday_9am = datetime(2026, 4, 6, 9, 0, tzinfo=timezone.utc)
    likelihood = tracker.get_likelihood(signal_id=1, timestamp=monday_9am)
    assert likelihood > 0.5

    # Tuesday 3AM should have low likelihood
    tuesday_3am = datetime(2026, 4, 7, 3, 0, tzinfo=timezone.utc)
    low = tracker.get_likelihood(signal_id=1, timestamp=tuesday_3am)
    assert low < likelihood


def test_unknown_signal_likelihood():
    """Unknown signal returns 0 likelihood."""
    tracker = PatternTracker()
    now = datetime.now(timezone.utc)
    assert tracker.get_likelihood(signal_id=999, timestamp=now) == 0.0


def test_get_active_signals():
    """Returns signals likely active at a given time."""
    tracker = PatternTracker()
    # Signal 1 active Monday mornings
    for _ in range(10):
        tracker.record(signal_id=1, timestamp=datetime(2026, 3, 30, 9, 0, tzinfo=timezone.utc), duration_minutes=30.0)
    # Signal 2 active Friday evenings
    for _ in range(10):
        tracker.record(signal_id=2, timestamp=datetime(2026, 4, 3, 20, 0, tzinfo=timezone.utc), duration_minutes=30.0)

    monday_9am = datetime(2026, 4, 6, 9, 0, tzinfo=timezone.utc)
    active = tracker.get_active_signals(monday_9am)
    assert 1 in [s[0] for s in active]


def test_save_and_load(tmp_path):
    tracker = PatternTracker()
    for _ in range(5):
        tracker.record(signal_id=1, timestamp=datetime(2026, 4, 3, 14, 0, tzinfo=timezone.utc), duration_minutes=5.0)
    path = str(tmp_path / "patterns.json")
    tracker.save(path)

    tracker2 = PatternTracker()
    tracker2.load(path)
    assert tracker2.num_signals == 1
    matrix = tracker2.get_matrix(signal_id=1)
    assert matrix[4, 14] > 0  # April 3 2026 is Friday (weekday=4)

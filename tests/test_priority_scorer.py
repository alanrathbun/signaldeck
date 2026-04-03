from datetime import datetime, timezone

import pytest

from signaldeck.learning.priority_scorer import PriorityScorer, ScoredFrequency


def test_score_bookmarked_frequency():
    """Bookmarked frequencies get a priority boost."""
    scorer = PriorityScorer()
    scored = scorer.score(
        frequency_hz=162.4e6,
        user_priority=5,
        activity_likelihood=0.0,
        last_seen_minutes_ago=999,
        is_new=False,
    )
    assert isinstance(scored, ScoredFrequency)
    assert scored.score > 0
    assert scored.frequency_hz == 162.4e6


def test_higher_priority_scores_higher():
    scorer = PriorityScorer()
    low = scorer.score(frequency_hz=100e6, user_priority=1, activity_likelihood=0.5,
                       last_seen_minutes_ago=60, is_new=False)
    high = scorer.score(frequency_hz=100e6, user_priority=5, activity_likelihood=0.5,
                        last_seen_minutes_ago=60, is_new=False)
    assert high.score > low.score


def test_active_frequency_scores_higher():
    scorer = PriorityScorer()
    inactive = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.0,
                            last_seen_minutes_ago=60, is_new=False)
    active = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.9,
                          last_seen_minutes_ago=60, is_new=False)
    assert active.score > inactive.score


def test_recent_signal_gets_recency_bonus():
    scorer = PriorityScorer()
    old = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.5,
                       last_seen_minutes_ago=120, is_new=False)
    recent = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.5,
                          last_seen_minutes_ago=5, is_new=False)
    assert recent.score > old.score


def test_new_signal_gets_novelty_bonus():
    scorer = PriorityScorer()
    known = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.5,
                         last_seen_minutes_ago=60, is_new=False)
    novel = scorer.score(frequency_hz=100e6, user_priority=3, activity_likelihood=0.5,
                         last_seen_minutes_ago=60, is_new=True)
    assert novel.score > known.score


def test_rank_frequencies():
    """rank() sorts frequencies by score descending."""
    scorer = PriorityScorer()
    freqs = [
        {"frequency_hz": 100e6, "user_priority": 1, "activity_likelihood": 0.1,
         "last_seen_minutes_ago": 120, "is_new": False},
        {"frequency_hz": 162.4e6, "user_priority": 5, "activity_likelihood": 0.9,
         "last_seen_minutes_ago": 5, "is_new": False},
        {"frequency_hz": 433e6, "user_priority": 3, "activity_likelihood": 0.5,
         "last_seen_minutes_ago": 30, "is_new": True},
    ]
    ranked = scorer.rank(freqs)
    assert len(ranked) == 3
    assert ranked[0].score >= ranked[1].score >= ranked[2].score
    # The high-priority, recently active bookmark should be first
    assert ranked[0].frequency_hz == 162.4e6

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScoredFrequency:
    """A frequency with its computed scan priority score."""
    frequency_hz: float
    score: float
    components: dict  # breakdown of score components


class PriorityScorer:
    """Computes scan priority scores for frequencies.

    Score formula:
        score = (user_priority × 3) + (activity_likelihood × 2) + recency_bonus + novelty_bonus

    Components:
        - user_priority: from bookmarks (1-5), default 0 for unbookmarked
        - activity_likelihood: 0-1 from the PatternTracker for current time
        - recency_bonus: decays over time since last seen
        - novelty_bonus: high for newly discovered, unclassified signals
    """

    def __init__(
        self,
        priority_weight: float = 3.0,
        activity_weight: float = 2.0,
        recency_decay_minutes: float = 30.0,
        novelty_bonus_value: float = 3.0,
    ) -> None:
        self._priority_weight = priority_weight
        self._activity_weight = activity_weight
        self._recency_decay = recency_decay_minutes
        self._novelty_bonus = novelty_bonus_value

    def score(
        self,
        frequency_hz: float,
        user_priority: int = 0,
        activity_likelihood: float = 0.0,
        last_seen_minutes_ago: float = 999.0,
        is_new: bool = False,
    ) -> ScoredFrequency:
        """Compute priority score for a frequency.

        Args:
            frequency_hz: The frequency.
            user_priority: Bookmark priority 0-5 (0 = not bookmarked).
            activity_likelihood: 0-1 from pattern tracker.
            last_seen_minutes_ago: Minutes since last detection.
            is_new: Whether this is a newly discovered signal.

        Returns:
            ScoredFrequency with score and component breakdown.
        """
        priority_score = user_priority * self._priority_weight
        activity_score = activity_likelihood * self._activity_weight

        # Recency bonus: exponential decay
        recency_bonus = max(0, self._recency_decay - last_seen_minutes_ago) / self._recency_decay
        recency_bonus *= 2.0  # scale to max 2.0

        novelty_bonus = self._novelty_bonus if is_new else 0.0

        total = priority_score + activity_score + recency_bonus + novelty_bonus

        return ScoredFrequency(
            frequency_hz=frequency_hz,
            score=total,
            components={
                "priority": priority_score,
                "activity": activity_score,
                "recency": round(recency_bonus, 2),
                "novelty": novelty_bonus,
            },
        )

    def rank(self, frequency_params: list[dict]) -> list[ScoredFrequency]:
        """Score and rank a list of frequencies.

        Args:
            frequency_params: List of dicts with keys matching score() parameters.

        Returns:
            List of ScoredFrequency sorted by score descending.
        """
        scored = [self.score(**params) for params in frequency_params]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

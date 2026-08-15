"""Pure metric functions for the eval harness.

Deliberately free of any LLM / IO so they can be unit-tested offline and
reused across every suite. Retrieval treats `relevant` as a set (any expected
source counts as a hit); classification metrics compare aligned prediction /
expected sequences.
"""

from collections import Counter
from collections.abc import Iterable, Sequence


def accuracy(predictions: Sequence, expected: Sequence) -> float:
    """Fraction of positions where prediction == expected."""
    if not expected:
        return 0.0
    correct = sum(1 for p, e in zip(predictions, expected, strict=True) if p == e)
    return correct / len(expected)


def confusion_counts(predictions: Sequence, expected: Sequence) -> dict[tuple[str, str], int]:
    """Map (expected, predicted) -> count, for spotting systematic mis-routing."""
    counts: Counter = Counter()
    for e, p in zip(expected, predictions, strict=True):
        counts[(e, p)] += 1
    return dict(counts)


def rank_of_first_hit(retrieved: Sequence, relevant: Iterable) -> int | None:
    """1-based rank of the first retrieved item present in `relevant`, else None."""
    relevant_set = set(relevant)
    for index, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return index
    return None


def hit_at_k(retrieved: Sequence, relevant: Iterable, k: int) -> bool:
    """True if any relevant item appears within the top-k retrieved."""
    return rank_of_first_hit(retrieved[:k], relevant) is not None


def reciprocal_rank(retrieved: Sequence, relevant: Iterable) -> float:
    """1/rank of the first hit (0.0 if none) — averaged, this is MRR."""
    rank = rank_of_first_hit(retrieved, relevant)
    return 1.0 / rank if rank else 0.0


def recall_at_k(retrieved: Sequence, relevant: Iterable, k: int) -> float:
    """Fraction of the relevant set recovered within the top-k retrieved."""
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    found = relevant_set.intersection(retrieved[:k])
    return len(found) / len(relevant_set)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0

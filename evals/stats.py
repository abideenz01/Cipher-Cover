"""Small-sample statistics for the evaluation, with the standard library only.

Binary proportions (a decision right or wrong) get a Wilson score interval,
which behaves at small n and at 0% or 100%. Continuous measures (payout error,
seconds, tokens) get the median, the 90th percentile and the range, plus a
bootstrap interval for the median once n is at least BOOTSTRAP_MIN. Every
figure carries its n, and any n under SUFFICIENT is flagged.
"""

import math
import random
from typing import Any

Z95 = 1.959964
SUFFICIENT = 30
BOOTSTRAP_MIN = 20
BOOTSTRAP_REPS = 2000


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Return the Wilson score interval for a proportion, or None when n is 0."""
    if n == 0:
        return None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = (z / (1 + z * z / n)) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, n: int) -> dict[str, Any]:
    """Describe a binary proportion with its Wilson interval."""
    ci = wilson(successes, n)
    return {
        "kind": "proportion",
        "k": successes,
        "n": n,
        "rate": successes / n if n else None,
        "ci95": list(ci) if ci else None,
        "sufficient_sample": n >= SUFFICIENT,
    }


def percentile(values: list[float], q: float) -> float:
    """Return the q-th percentile (0 to 100) by linear interpolation."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def bootstrap_median(values: list[float], seed: int = 0) -> tuple[float, float]:
    """Return a 95% percentile-bootstrap interval for the median, seeded."""
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    medians = sorted(
        percentile([rng.choice(values) for _ in values], 50)
        for _ in range(BOOTSTRAP_REPS)
    )
    return percentile(medians, 2.5), percentile(medians, 97.5)


def distribution(values: list[float]) -> dict[str, Any]:
    """Describe a continuous measure: median, p90 and range, with n."""
    n = len(values)
    if n == 0:
        return {"kind": "distribution", "n": 0, "sufficient_sample": False}
    return {
        "kind": "distribution",
        "n": n,
        "median": percentile(values, 50),
        "p90": percentile(values, 90),
        "min": min(values),
        "max": max(values),
        "median_ci95": list(bootstrap_median(values)) if n >= BOOTSTRAP_MIN else None,
        "sufficient_sample": n >= SUFFICIENT,
    }


def overlap(a: list[float] | None, b: list[float] | None) -> bool | None:
    """Return whether two intervals overlap, or None if either is missing."""
    if not a or not b:
        return None
    return a[0] <= b[1] and b[0] <= a[1]

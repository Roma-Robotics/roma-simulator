"""Seeded stochastic samplers.

All randomness in the engine flows through a single `numpy.random.Generator`
constructed from the run seed. That guarantees per-seed reproducibility:
the same `(scenario_version, policy_version, seed)` triple produces the same
event log, byte-for-byte, on the same Python+NumPy build.

Cross-platform bitwise determinism is *not* a goal at Tier 1; statistical
reproducibility per-seed is.
"""

from __future__ import annotations

import numpy as np


class DurationSampler:
    """Truncated-normal duration sampler.

    Samples from `N(mean, std)` clipped to `[mean * 0.1, mean * 5]` so a single
    bad draw can't produce a negative or absurd duration.
    """

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng

    def sample(self, mean: float, std: float) -> float:
        if mean <= 0:
            raise ValueError(f"duration mean must be positive, got {mean}")
        if std <= 0:
            return float(mean)
        lo = mean * 0.1
        hi = mean * 5.0
        # Resample-on-reject is fine; the probability of >5 std is tiny.
        for _ in range(16):
            x = float(self._rng.normal(mean, std))
            if lo <= x <= hi:
                return x
        return float(np.clip(mean, lo, hi))


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)

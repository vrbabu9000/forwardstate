"""Stationary block bootstrap (Politis & Romano 1994) of whole rows of joint daily returns."""

from __future__ import annotations

import numpy as np

MEAN_BLOCK_LENGTH = 5.0


def seed_from_hash(hex_digest: str) -> int:
    """64-bit RNG seed from a ``stable_hash`` hex digest."""
    return int(hex_digest[:16], 16)


def stationary_bootstrap_indices(
    n_obs: int, n_paths: int, n_days: int, seed: int, mean_block: float = MEAN_BLOCK_LENGTH
) -> np.ndarray:
    """Row indices, shape (n_paths, n_days). Each step continues the current block (wrapping
    around the end of the sample) with probability 1 - 1/mean_block, otherwise jumps to a new
    random start. Whole rows are drawn, so the cross-asset correlation of each day is kept."""
    if n_obs <= 0 or n_days <= 0:
        return np.zeros((n_paths, max(n_days, 0)), dtype=np.int64)
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    starts = rng.integers(0, n_obs, size=(n_paths, n_days))
    jump = rng.random((n_paths, n_days)) < p
    idx = np.empty((n_paths, n_days), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for t in range(1, n_days):
        idx[:, t] = np.where(jump[:, t], starts[:, t], (idx[:, t - 1] + 1) % n_obs)
    return idx

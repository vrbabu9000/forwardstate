"""Test and demo helpers: synthetic dataset and in-memory point-in-time store."""

from .fixture_store import FixtureStore
from .synthetic import SyntheticDataset, build_synthetic_dataset, synthetic_as_of

__all__ = ["FixtureStore", "SyntheticDataset", "build_synthetic_dataset", "synthetic_as_of"]

"""Run provenance (AC-06): an append-only JSONL log of every computing POST.

Each line of ``state_dir/runs.jsonl`` is one ``RunRecord``. Lines are never rewritten or
deleted. An in-memory index gives fast lookups by ``run_id``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from forwardstate.contracts import ReproduceResult, RunKind, RunRecord, stable_hash

log = logging.getLogger("forwardstate.api.runs")

# Keys that legitimately differ between two runs of the same request. They are removed
# (recursively) before the output hash. ``alert_id`` is kept: it is deterministic.
# Lifecycle fields (status, superseded_by) change by user action, not computation.
VOLATILE_KEYS = frozenset({"run_id", "created_at", "reproduced_run_id", "status", "superseded_by"})


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def strip_volatile(obj: Any) -> Any:
    """Return a copy of a JSON-like object with every volatile key removed, at any depth."""
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [strip_volatile(x) for x in obj]
    return obj


def output_hash(response: Any) -> str:
    """Stable hash of a response (model, list of models or dict) without volatile keys."""
    return stable_hash(strip_volatile(_to_jsonable(response)))


class RunRegistry:
    """Append-only run log plus an in-memory index. Thread-safe."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "runs.jsonl"
        self._lock = threading.Lock()
        self._records: dict[str, RunRecord] = {}
        self._order: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = RunRecord.model_validate_json(line)
                except ValidationError as e:
                    log.warning("Skipping unreadable run record at %s:%d (%s)", self.path, lineno, e)
                    continue
                if rec.run_id not in self._records:
                    self._order.append(rec.run_id)
                self._records[rec.run_id] = rec

    def __contains__(self, run_id: str) -> bool:
        return run_id in self._records

    def __len__(self) -> int:
        return len(self._records)

    def add(self, record: RunRecord) -> RunRecord:
        with self._lock:
            if record.run_id in self._records:
                raise ValueError(f"run_id '{record.run_id}' is already recorded")
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")
            self._records[record.run_id] = record
            self._order.append(record.run_id)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def list(self, kind: RunKind | None = None, limit: int = 50) -> list[RunRecord]:
        """Newest first."""
        out: list[RunRecord] = []
        for run_id in reversed(self._order):
            rec = self._records[run_id]
            if kind is None or rec.kind == kind:
                out.append(rec)
                if len(out) >= limit:
                    break
        return out

    def reproduce(self, run_id: str, rerun: Any) -> ReproduceResult:
        """Re-run a stored run and compare output hashes.

        ``rerun(record) -> (new_record, notes)`` re-executes ``record.request`` with
        ``record.as_of`` and records the new run. Raises ``KeyError`` for an unknown run_id.
        """
        original = self.get(run_id)
        if original is None:
            raise KeyError(run_id)
        new, notes = rerun(original)
        match = new.output_hash == original.output_hash
        if new.config_hash != original.config_hash:
            notes.append("Settings changed since the original run (config_hash differs).")
        if new.input_hash != original.input_hash:
            notes.append("Inputs differ (request, as_of or source status changed).")
        if new.data_origin != original.data_origin:
            notes.append(
                f"Data origin changed: {original.data_origin.value} -> {new.data_origin.value}."
            )
        if new.model_version != original.model_version:
            notes.append(
                f"Model version changed: {original.model_version} -> {new.model_version}."
            )
        if not match and not notes:
            notes.append("Same inputs and settings but a different output: the run is not deterministic.")
        return ReproduceResult(
            run_id=run_id,
            reproduced_run_id=new.run_id,
            original_output_hash=original.output_hash,
            reproduced_output_hash=new.output_hash,
            match=match,
            note=" ".join(notes) or None,
        )

"""Regression coverage for mutation telemetry history."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_history.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_history", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules[spec.name]


def sample(**overrides):
    payload = {
        "source": "packages/example.py",
        "source_hash": "source-hash",
        "test_scope_hash": "tests-hash",
        "baseline_test_seconds": 2.0,
        "mutation_seconds": 100.0,
        "mutant_count": 50,
        "viable_mutants": 40,
        "killed_mutants": 38,
        "surviving_mutants": 2,
        "non_viable_mutants": 8,
        "invalid_mutants": 1,
        "undetermined_mutants": 1,
        "kill_rate": 0.95,
        "runner": "ubuntu-latest",
        "python_version": "3.12.9",
        "cosmic_ray_version": "8.4.3",
        "pytest_version": "8.4.1",
        "tool_fingerprint": "fingerprint",
        "verified_commit": "abc123",
        "verified_at": "2026-08-15T00:00:00Z",
        "complete": True,
    }
    payload.update(overrides)
    return payload


def test_first_complete_sample_initializes_history(module) -> None:
    history = {"entries": {}}
    result = module.merge(history, [sample()])
    entry = result["entries"]["packages/example.py"]
    assert entry["sample_count"] == 1
    assert entry["ewma_mutation_seconds"] == 100.0
    assert entry["ewma_baseline_test_seconds"] == 2.0
    assert entry["viable_mutants"] == 40
    assert entry["killed_mutants"] == 38
    assert entry["surviving_mutants"] == 2
    assert entry["non_viable_mutants"] == 8
    assert entry["last_verified_commit"] == "abc123"


def test_recent_runtime_receives_more_ewma_weight(module) -> None:
    first = module.merge({"entries": {}}, [sample(mutation_seconds=100.0)])
    second = module.merge(first, [sample(mutation_seconds=200.0)])
    entry = second["entries"]["packages/example.py"]
    assert entry["sample_count"] == 2
    assert entry["ewma_mutation_seconds"] == pytest.approx(135.0)


def test_incomplete_sample_is_rejected(module) -> None:
    with pytest.raises(ValueError, match="incomplete"):
        module.merge({"entries": {}}, [sample(complete=False)])


def test_missing_environment_fingerprint_is_rejected(module) -> None:
    payload = sample()
    del payload["tool_fingerprint"]
    with pytest.raises(ValueError, match="tool_fingerprint"):
        module.merge({"entries": {}}, [payload])

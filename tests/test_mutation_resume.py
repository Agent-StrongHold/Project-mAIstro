"""Regression coverage for continuation-aware mutation checkpoints."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_resume.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_resume", SCRIPT)
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


def write_tree(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_source.py").write_text("def test_value(): assert True\n", encoding="utf-8")
    return source, tests


def checkpoint(module, source: Path, tests: Path, **overrides):
    row = {
        "source": str(source),
        "source_hash": module.tree_hash(str(source)),
        "test_scope_hash": module.tree_hash(str(tests)),
        "tool_fingerprint": "tools-v1",
        "verified_commit": "abc123",
        "verified_at": "2026-08-15T20:00:00+00:00",
        "complete": True,
    }
    row.update(overrides)
    return row


def test_matching_checkpoint_is_reused(module, tmp_path: Path) -> None:
    source, tests = write_tree(tmp_path)
    row = checkpoint(module, source, tests)
    pending, reused = module.filter_targets(
        [(str(source), str(tests))],
        {str(source): [row]},
        commit="abc123",
        tool_fingerprint="tools-v1",
    )
    assert pending == []
    assert reused == [row]


@pytest.mark.parametrize(
    "overrides",
    [
        {"complete": False},
        {"verified_commit": "other"},
        {"tool_fingerprint": "tools-v2"},
        {"source_hash": "stale"},
        {"test_scope_hash": "stale"},
    ],
)
def test_stale_or_incomplete_checkpoint_does_not_skip_work(
    module, tmp_path: Path, overrides: dict[str, object]
) -> None:
    source, tests = write_tree(tmp_path)
    row = checkpoint(module, source, tests, **overrides)
    pending, reused = module.filter_targets(
        [(str(source), str(tests))],
        {str(source): [row]},
        commit="abc123",
        tool_fingerprint="tools-v1",
    )
    assert pending == [(str(source), str(tests))]
    assert reused == []


def test_content_change_invalidates_checkpoint(module, tmp_path: Path) -> None:
    source, tests = write_tree(tmp_path)
    row = checkpoint(module, source, tests)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    pending, reused = module.filter_targets(
        [(str(source), str(tests))],
        {str(source): [row]},
        commit="abc123",
        tool_fingerprint="tools-v1",
    )
    assert pending
    assert not reused


def test_runtime_test_caches_do_not_change_scope_hash(module, tmp_path: Path) -> None:
    _source, tests = write_tree(tmp_path)
    before = module.tree_hash(str(tests))
    cache = tests / "__pycache__"
    cache.mkdir()
    (cache / "test_source.cpython-312-pytest.pyc").write_bytes(b"runtime cache")
    pytest_cache = tests / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "README.md").write_text("generated\n", encoding="utf-8")
    assert module.tree_hash(str(tests)) == before


def test_checkpoint_reader_groups_sources(module, tmp_path: Path) -> None:
    source, tests = write_tree(tmp_path)
    root = tmp_path / "checkpoints"
    root.mkdir()
    row = checkpoint(module, source, tests)
    (root / "one.checkpoint.json").write_text(json.dumps(row), encoding="utf-8")
    assert module.read_checkpoints(root) == {str(source): [row]}

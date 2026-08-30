from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-branch-independence.py"
spec = importlib.util.spec_from_file_location("_branch_independence", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _registry(*surfaces, frozen=()):
    return {
        "version": 1,
        "goal": "test",
        "quality_roots": ["quality"],
        "frozen_legacy_paths": list(frozen),
        "surfaces": list(surfaces),
    }


def _surface(surface_id, kind, *paths, target_kind=None):
    value = {
        "id": surface_id,
        "kind": kind,
        "paths": list(paths),
        "reason": "test representation",
    }
    if target_kind is not None:
        value["target_kind"] = target_kind
    return value


def test_repository_json_must_be_classified(tmp_path):
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "known.json").write_text("{}\n")
    (quality / "surprise.json").write_text("{}\n")
    registry = _registry(_surface("known", "specification", "quality/known.json"))

    errors = mod.coverage_errors(registry, mod.discover_quality_json(tmp_path, registry))

    assert "unclassified quality state: quality/surprise.json" in errors


def test_overlapping_surfaces_fail(tmp_path):
    quality = tmp_path / "quality"
    quality.mkdir()
    (quality / "same.json").write_text("{}\n")
    registry = _registry(
        _surface("one", "specification", "quality/*.json"),
        _surface("two", "specification", "quality/same.json"),
    )

    errors = mod.coverage_errors(registry, mod.discover_quality_json(tmp_path, registry))

    assert any("matches multiple surfaces: quality/same.json" in error for error in errors)


def test_unknown_kind_fails():
    registry = _registry(_surface("bad", "shared_blob", "quality/bad.json"))

    assert any("unknown kind" in error for error in mod.registry_errors(registry))


def test_legacy_paths_must_be_exact():
    pattern = "quality/*-baseline.json"
    registry = _registry(
        _surface(
            "legacy",
            "legacy_shared_aggregate",
            pattern,
            target_kind="base_derived",
        ),
        frozen=(pattern,),
    )

    errors = mod.registry_errors(registry)

    assert any("legacy path must be exact" in error for error in errors)
    assert any("frozen legacy path must be exact" in error for error in errors)


def test_new_legacy_path_fails_the_frozen_set():
    old = "quality/old.json"
    new = "quality/new.json"
    registry = _registry(
        _surface(
            "old",
            "legacy_shared_aggregate",
            old,
            target_kind="base_derived",
        ),
        _surface(
            "new",
            "legacy_shared_aggregate",
            new,
            target_kind="base_derived",
        ),
        frozen=(old,),
    )

    assert any(new in error and "forbidden" in error for error in mod.registry_errors(registry))


def test_removing_legacy_path_requires_removing_it_from_the_freeze():
    old = "quality/old.json"
    registry = _registry(_surface("old", "specification", old), frozen=(old,))

    assert any(old in error and "remove them" in error for error in mod.registry_errors(registry))


def test_trusted_base_refuses_candidate_expansion_even_if_candidate_edits_freeze():
    old = "quality/old.json"
    new = "quality/new.json"
    base = _registry(
        _surface(
            "old",
            "legacy_shared_aggregate",
            old,
            target_kind="base_derived",
        ),
        frozen=(old,),
    )
    candidate = _registry(
        _surface(
            "old",
            "legacy_shared_aggregate",
            old,
            target_kind="base_derived",
        ),
        _surface(
            "new",
            "legacy_shared_aggregate",
            new,
            target_kind="base_derived",
        ),
        frozen=(old, new),
    )

    assert mod.trusted_base_errors(candidate, base) == [
        "candidate expands the trusted legacy freeze: quality/new.json"
    ]


def test_folded_note_pattern_covers_independent_notes(tmp_path):
    notes = tmp_path / "quality" / "ac-state-notes"
    notes.mkdir(parents=True)
    (notes / "agent-a.json").write_text("{}\n")
    (notes / "agent-b.json").write_text("{}\n")
    registry = _registry(_surface("notes", "folded_notes", "quality/ac-state-notes/*.json"))

    errors = mod.coverage_errors(registry, mod.discover_quality_json(tmp_path, registry))

    assert errors == []

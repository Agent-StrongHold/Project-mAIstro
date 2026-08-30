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


def test_missing_root_is_silently_skipped(tmp_path):
    """A registered root that does not exist on disk yet contributes nothing,
    rather than failing discovery -- the bootstrap case for a fresh checkout."""
    registry = _registry(_surface("known", "specification", "quality/known.json"))

    assert mod.discover_quality_json(tmp_path, registry) == set()


def test_registered_exact_path_must_actually_exist(tmp_path):
    quality = tmp_path / "quality"
    quality.mkdir()
    registry = _registry(_surface("known", "specification", "quality/known.json"))

    errors = mod.coverage_errors(registry, mod.discover_quality_json(tmp_path, registry))

    assert any(
        "registered exact path does not exist: known: quality/known.json" in error
        for error in errors
    )


def test_load_registry_rejects_unreadable_missing_or_malformed_files(tmp_path):
    missing = tmp_path / "absent.json"
    assert any("cannot read" in str(exc) for exc in [_raises(lambda: mod.load_registry(missing))])

    not_json = tmp_path / "not-json.json"
    not_json.write_text("{not json", encoding="utf-8")
    assert any(
        "not valid JSON" in str(exc) for exc in [_raises(lambda: mod.load_registry(not_json))]
    )

    not_object = tmp_path / "not-object.json"
    not_object.write_text("[]", encoding="utf-8")
    assert any(
        "must contain a JSON object" in str(exc)
        for exc in [_raises(lambda: mod.load_registry(not_object))]
    )


def _raises(fn):
    try:
        fn()
    except mod.BranchIndependenceError as exc:
        return exc
    raise AssertionError("expected BranchIndependenceError, none was raised")


def test_registry_version_and_roots_are_validated():
    registry = _registry()
    registry["version"] = 2
    registry["quality_roots"] = []

    errors = mod.registry_errors(registry)

    assert "registry version must be 1" in errors
    assert "quality_roots must be a non-empty list of paths" in errors


def test_frozen_legacy_paths_must_be_a_list_without_duplicates():
    dup = "quality/dup.json"
    registry = _registry(
        _surface("dup", "legacy_shared_aggregate", dup, target_kind="base_derived"),
        frozen=(dup, dup),
    )

    assert "frozen_legacy_paths contains duplicates" in mod.registry_errors(registry)

    malformed = _registry()
    malformed["frozen_legacy_paths"] = "not-a-list"

    assert "frozen_legacy_paths must be a list of exact paths" in mod.registry_errors(malformed)


def test_surfaces_list_must_be_present_and_each_entry_an_object():
    empty = _registry()
    empty["surfaces"] = []
    assert "surfaces must be a non-empty list" in mod.registry_errors(empty)

    malformed = _registry()
    malformed["surfaces"] = ["not-an-object"]
    assert "surface[0] must be an object" in mod.registry_errors(malformed)


def test_surface_must_have_a_non_empty_unique_id():
    unnamed = {"kind": "specification", "paths": ["quality/x.json"], "reason": "r"}
    registry = _registry(unnamed)
    assert "surface[0] has no id" in mod.registry_errors(registry)

    dup_id = _registry(
        _surface("dup", "specification", "quality/a.json"),
        _surface("dup", "specification", "quality/b.json"),
    )
    assert "duplicate surface id: dup" in mod.registry_errors(dup_id)


def test_surface_must_declare_at_least_one_path_and_a_reason():
    no_paths = {"id": "empty", "kind": "specification", "paths": [], "reason": "r"}
    registry = _registry(no_paths)
    assert any("must list at least one path or glob" in e for e in mod.registry_errors(registry))

    no_reason = _surface("bare", "specification", "quality/bare.json")
    del no_reason["reason"]
    registry = _registry(no_reason)
    assert any("must explain its representation" in e for e in mod.registry_errors(registry))


def test_legacy_surface_without_a_migration_target_fails():
    registry = _registry(
        {
            "id": "legacy",
            "kind": "legacy_shared_aggregate",
            "paths": ["quality/legacy.json"],
            "reason": "r",
        },
        frozen=("quality/legacy.json",),
    )

    assert any("needs a non-legacy target_kind" in e for e in mod.registry_errors(registry))

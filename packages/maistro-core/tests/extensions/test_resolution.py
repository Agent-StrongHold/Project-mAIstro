"""Deterministic dependency resolution and lock state (M9-C2, #956).

Each test names the acceptance criterion it pins:

* identical catalog + manifests → identical lock state (byte-level, and
  invariant to catalog input order);
* incompatible constraints and cycles fail before activation (resolution is
  pure metadata — nothing is fetched, verified, or activated on failure);
* lock entries carry the immutable version/digest/source identity;
* optional dependencies never silently become required authority — every
  optional failure mode becomes a recorded skip, never a failed install or an
  overridden selection;
* the lock explains itself: constraints, rejected candidates, skip reasons.

Fail-before evidence (mutations, reverted before commit): replacing
``max(candidates, …)`` with ``min`` fails the version-policy and
determinism tests; muting the cycle raise fails both cycle tests; making
optional-branch failures raise instead of skip fails every
"optional never escalates" test.
"""

from __future__ import annotations

from typing import Any

import pytest

from extensions.extension_fixtures import (
    CATALOG_SNAPSHOT,
    CATALOG_URL,
    PACKAGE_BYTES,
    catalog_entry,
    install_bundle,
)
from maistro.extensions.resolution import (
    ROOT_REQUEST_ORIGIN,
    DependencyCycle,
    ExtensionCatalog,
    ExtensionDependency,
    LockFormatError,
    LockKind,
    LockState,
    ResolutionConflict,
    RootRequest,
    UnresolvableDependency,
    diff_locks,
    resolve_lock,
)

_SNAPSHOT = CATALOG_SNAPSHOT


def _entry(
    name: str,
    version: str,
    *,
    deps: tuple[tuple[str, str, bool], ...] = (),
    source: str = CATALOG_URL,
    snapshot: str = _SNAPSHOT,
    package_bytes: bytes = PACKAGE_BYTES,
) -> Any:
    """One catalog entry; deps are (target, range, required) triples."""
    bundle = install_bundle(name=name, version=version, package_bytes=package_bytes)
    dependencies = tuple(
        ExtensionDependency(target=target, range_text=range_text, required=required)
        for target, range_text, required in deps
    )
    return catalog_entry(bundle, source=source, snapshot=snapshot, dependencies=dependencies)


def _one_root(name: str = "tool-a", range_text: str = "*") -> list[RootRequest]:
    return [RootRequest(extension_name=name, range_text=range_text)]


# ---------------------------------------------------------------------------
# Acceptance: identical catalog + manifests produce identical lock state.
# ---------------------------------------------------------------------------


def test_identical_catalogs_produce_byte_identical_locks() -> None:
    entries = [
        _entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True),)),
        _entry("lib-b", "1.2.0"),
    ]
    # The same entries, offered in a different catalog order.
    forward = resolve_lock(_one_root(), _cat(list(entries)))
    backward = resolve_lock(_one_root(), _cat(list(reversed(entries))))
    assert forward.to_json() == backward.to_json()
    assert forward.lock_digest() == backward.lock_digest()


def test_repeated_resolution_is_deterministic() -> None:
    catalog = _cat(
        [
            _entry(
                "tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True), ("opt-c", ">=1.0.0", False))
            ),
            _entry("lib-b", "1.2.0"),
            _entry("opt-c", "1.0.0"),
        ]
    )
    first = resolve_lock(_one_root(), catalog)
    second = resolve_lock(_one_root(), catalog)
    assert first == second
    assert first.to_json() == second.to_json()


def test_lock_state_carries_no_wall_clock_inputs() -> None:
    # Reproducibility means nothing time-dependent may leak into the lock.
    lock = resolve_lock(_one_root(), _cat([_entry("tool-a", "1.0.0")]))
    serialized = lock.to_json()
    assert "installed_at" not in serialized
    assert "timestamp" not in serialized


# ---------------------------------------------------------------------------
# Version selection policy: highest satisfying version, deterministic ties.
# ---------------------------------------------------------------------------


def test_highest_satisfying_version_is_selected() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0"),
            _entry("tool-a", "1.4.0"),
            _entry("tool-a", "1.9.0"),
        ]
    )
    lock = resolve_lock(_one_root(range_text=">=1.0.0,<1.5.0"), catalog)
    entry = lock.get("tool-a")
    assert entry is not None
    assert entry.semantic_version == "1.4.0"
    # Both excluded versions are recorded: 1.9.0 failed the range, while
    # 1.0.0 satisfied it and lost only the deterministic tie-break.
    assert {rejected.semantic_version for rejected in entry.rejected} == {"1.0.0", "1.9.0"}
    reasons = {r.semantic_version: r.reason for r in entry.rejected}
    assert "'<1.5.0'" in reasons["1.9.0"]
    assert ROOT_REQUEST_ORIGIN in reasons["1.9.0"]
    assert "tie-break" in reasons["1.0.0"]


def test_highest_version_is_semantic_not_lexicographic() -> None:
    # Regression: ``2.0.0`` sorts above ``10.0.0`` as a string, so the
    # catalog-order key must compare the parsed SemVer, not the raw text.
    catalog = _cat(
        [
            _entry("tool-a", "2.0.0"),
            _entry("tool-a", "10.0.0"),
        ]
    )
    lock = resolve_lock(_one_root(range_text="*"), catalog)
    entry = lock.get("tool-a")
    assert entry is not None
    assert entry.semantic_version == "10.0.0"


def test_same_version_tie_breaks_on_digest_deterministically() -> None:
    low_digest = _entry("tool-a", "1.0.0", package_bytes=b"package one\n")
    high_digest = _entry("tool-a", "1.0.0", package_bytes=b"package two\n")
    forward = resolve_lock(_one_root(), _cat([low_digest, high_digest]))
    backward = resolve_lock(_one_root(), _cat([high_digest, low_digest]))
    assert forward == backward
    chosen = forward.get("tool-a")
    assert chosen is not None
    # The policy picks the lexicographically greater digest; the loser is
    # recorded as having lost the tie-break, not as constraint-incompatible.
    assert chosen.package_sha256 == max(
        low_digest.identity.package_sha256, high_digest.identity.package_sha256
    )
    assert len(chosen.rejected) == 1
    assert "tie-break" in chosen.rejected[0].reason


# ---------------------------------------------------------------------------
# Acceptance: incompatible constraints and cycles fail before activation.
# ---------------------------------------------------------------------------


def test_conflicting_constraints_fail_naming_every_origin() -> None:
    catalog = _cat(
        [
            # "add-on" sorts before "lib-b", so both constraints accumulate
            # before lib-b is selected — the no-candidate diagnostic path.
            _entry("add-on", "1.0.0", deps=(("lib-b", ">=2.0.0", True),)),
            _entry("lib-b", "1.0.0"),
            _entry("lib-b", "1.2.0"),
        ]
    )
    requests = [
        RootRequest(extension_name="add-on"),
        RootRequest(extension_name="lib-b", range_text="<2.0.0"),
    ]
    with pytest.raises(ResolutionConflict) as excinfo:
        resolve_lock(requests, catalog)
    message = str(excinfo.value)
    # The diagnostic names the extension, both constraint origins, both
    # available versions, and why each was excluded.
    assert "'lib-b'" in message
    assert ROOT_REQUEST_ORIGIN in message
    assert "add-on" in message
    assert "1.0.0" in message and "1.2.0" in message
    assert "'>=2.0.0'" in message and "'<2.0.0'" in message


def test_constraint_arriving_after_selection_conflicts_without_backtracking() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("lib-b", "<2.0.0", True),)),
            _entry("zed", "1.0.0", deps=(("lib-b", ">=2.0.0", True),)),
            _entry("lib-b", "1.5.0"),
        ]
    )
    # lib-b resolves (under tool-a's constraint) before zed is even selected;
    # zed's later, incompatible constraint must conflict loudly.
    with pytest.raises(ResolutionConflict) as excinfo:
        resolve_lock(
            [RootRequest(extension_name="tool-a"), RootRequest(extension_name="zed")], catalog
        )
    message = str(excinfo.value)
    assert "1.5.0 was already selected" in message
    assert "zed" in message
    assert "does not backtrack" in message


def test_required_dependency_absent_from_catalog_fails() -> None:
    catalog = _cat([_entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True),))])
    with pytest.raises(ResolutionConflict) as excinfo:
        resolve_lock(_one_root(), catalog)
    assert "the catalog offers no versions" in str(excinfo.value)


def test_required_cycle_fails_naming_the_path() -> None:
    catalog = _cat(
        [
            _entry("alpha", "1.0.0", deps=(("beta", ">=1.0.0", True),)),
            _entry("beta", "1.0.0", deps=(("alpha", ">=1.0.0", True),)),
        ]
    )
    with pytest.raises(DependencyCycle) as excinfo:
        resolve_lock(_one_root("alpha"), catalog)
    assert "alpha -> beta -> alpha" in str(excinfo.value)


def test_self_dependency_cycle_fails() -> None:
    catalog = _cat([_entry("lonely", "1.0.0", deps=(("lonely", ">=1.0.0", True),))])
    with pytest.raises(DependencyCycle) as excinfo:
        resolve_lock(_one_root("lonely"), catalog)
    assert "lonely -> lonely" in str(excinfo.value)


def test_resolution_failure_means_nothing_to_install() -> None:
    # The resolver only ever reads manifest metadata: a failing resolution
    # cannot have fetched, verified, or activated anything. Pinned by the
    # fact that the conflict carries no records — the caller has no lock to
    # materialize — and by the materialize tests, where activation runs only
    # after a complete fetch. Here: a cycle raises and there is no lock.
    catalog = _cat(
        [
            _entry("alpha", "1.0.0", deps=(("beta", ">=1.0.0", True),)),
            _entry("beta", "1.0.0", deps=(("alpha", ">=1.0.0", True),)),
        ]
    )
    with pytest.raises(DependencyCycle):
        resolve_lock(_one_root("alpha"), catalog)


def test_malformed_declared_range_fails_resolution() -> None:
    catalog = _cat([_entry("tool-a", "1.0.0", deps=(("lib-b", "not-a-range", True),))])
    with pytest.raises(UnresolvableDependency) as excinfo:
        resolve_lock(_one_root(), catalog)
    assert "not-a-range" in str(excinfo.value)
    assert "tool-a" in str(excinfo.value)


def test_empty_target_declaration_fails_resolution() -> None:
    catalog = _cat([_entry("tool-a", "1.0.0", deps=(("", ">=1.0.0", True),))])
    with pytest.raises(UnresolvableDependency):
        resolve_lock(_one_root(), catalog)


# ---------------------------------------------------------------------------
# The happy path: transitive required resolution and lock shape.
# ---------------------------------------------------------------------------


def test_transitive_required_chain_is_fully_locked() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True),)),
            _entry("lib-b", "1.2.0", deps=(("lib-core", ">=0.1.0", True),)),
            _entry("lib-core", "0.3.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    assert {entry.extension_name for entry in lock.entries} == {"tool-a", "lib-b", "lib-core"}
    tool = lock.get("tool-a")
    core = lock.get("lib-core")
    assert tool is not None and core is not None
    assert tool.required_by == (ROOT_REQUEST_ORIGIN,)
    assert core.required_by == ("lib-b",)
    assert core.kind is LockKind.REQUIRED
    assert all(entry.kind is LockKind.REQUIRED for entry in lock.entries)


def test_lock_records_carry_immutable_identity_and_source() -> None:
    entry = _entry("tool-a", "1.0.0", source="https://catalog.example/x.json")
    lock = resolve_lock(_one_root(), _cat([entry]))
    locked = lock.get("tool-a")
    assert locked is not None
    # The acceptance criterion's immutable identity: version, both digests,
    # and the exact source — plus which catalog snapshot claimed them.
    assert locked.semantic_version == "1.0.0"
    assert locked.package_sha256 == entry.identity.package_sha256
    assert locked.manifest_sha256 == entry.identity.manifest_sha256
    assert locked.source == "https://catalog.example/x.json"
    assert locked.catalog_snapshot_sha256 == _SNAPSHOT
    assert locked.identity == entry.identity
    assert locked.publisher_id == entry.publisher_id
    assert locked.signature == entry.signature


def test_lock_json_round_trips_equal_with_equal_digest() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True), ("opt-c", "*", False))),
            _entry("lib-b", "1.2.0"),
            _entry("opt-c", "1.0.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    rebuilt = LockState.from_json(lock.to_json())
    assert rebuilt == lock
    assert rebuilt.lock_digest() == lock.lock_digest()


def test_lock_digest_distinguishes_different_catalogs() -> None:
    lock_v1 = resolve_lock(_one_root(), _cat([_entry("tool-a", "1.0.0")]))
    lock_v2 = resolve_lock(_one_root(), _cat([_entry("tool-a", "1.1.0")]))
    assert lock_v1.lock_digest() != lock_v2.lock_digest()


@pytest.mark.parametrize(
    ("mutation"),
    [
        "format",  # wrong format tag
        "truncated",  # cut mid-document
        "version",  # semantic_version not MAJOR.MINOR.PATCH
        "digest",  # package_sha256 not hex64
        "source",  # empty source
        "kind",  # unknown kind
        "signature",  # empty signature
    ],
)
def test_lock_from_json_fails_closed_on_corruption(mutation: str) -> None:
    catalog = _cat([_entry("tool-a", "1.0.0")])
    raw = resolve_lock(_one_root(), catalog).to_json()
    import json

    if mutation == "truncated":
        corrupted = raw[: len(raw) // 2]
    else:
        payload: dict[str, Any] = json.loads(raw)
        entry: dict[str, Any] = payload["entries"][0]
        if mutation == "format":
            payload["format"] = "maistro-extension-lock:v9"
        elif mutation == "version":
            entry["semantic_version"] = "1.0"
        elif mutation == "digest":
            entry["package_sha256"] = "nothex"
        elif mutation == "source":
            entry["source"] = ""
        elif mutation == "kind":
            entry["kind"] = "best-effort"
        elif mutation == "signature":
            entry["signature"] = ""
        corrupted = json.dumps(payload)
    with pytest.raises(LockFormatError):
        LockState.from_json(corrupted)


# ---------------------------------------------------------------------------
# Acceptance: optional dependencies never silently become required authority.
# ---------------------------------------------------------------------------


def test_absent_optional_dependency_still_installs_with_recorded_skip() -> None:
    catalog = _cat([_entry("tool-a", "1.0.0", deps=(("opt-c", ">=1.0.0", False),))])
    lock = resolve_lock(_one_root(), catalog)
    # The requiring extension is fully locked; the optional branch is absent.
    assert [entry.extension_name for entry in lock.entries] == ["tool-a"]
    assert len(lock.skipped_optional) == 1
    skip = lock.skipped_optional[0]
    assert (skip.requirer, skip.target, skip.range_text) == ("tool-a", "opt-c", ">=1.0.0")
    assert "cannot resolve" in skip.reason


def test_resolvable_optional_dependency_is_pinned_as_optional() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=1.0.0", False),)),
            _entry("opt-c", "1.0.0", deps=(("opt-c-lib", ">=0.1.0", True),)),
            _entry("opt-c-lib", "0.2.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    assert {entry.extension_name for entry in lock.entries} == {"tool-a", "opt-c", "opt-c-lib"}
    head = lock.get("opt-c")
    assert head is not None
    assert head.kind is LockKind.OPTIONAL
    assert head.optional_for == ("tool-a",)
    assert head.required_by == ("tool-a",)
    # The branch's own required dependencies came along — but as optional
    # branch members, never as unconditional authority.
    member = lock.get("opt-c-lib")
    assert member is not None
    assert member.required_by == ("opt-c",)
    assert member.optional_for == ()


def test_optional_branch_failure_does_not_fail_the_install() -> None:
    # The optional branch's own required dependency is unsatisfiable: the
    # branch is skipped with the reason, and tool-a still installs.
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=1.0.0", False),)),
            _entry("opt-c", "1.0.0", deps=(("lib-x", ">=9.0.0", True),)),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    assert [entry.extension_name for entry in lock.entries] == ["tool-a"]
    assert len(lock.skipped_optional) == 1
    assert "lib-x" in lock.skipped_optional[0].reason


def test_optional_branch_cycle_is_skipped_not_fatal() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=1.0.0", False),)),
            _entry("opt-c", "1.0.0", deps=(("opt-d", ">=1.0.0", True),)),
            _entry("opt-d", "1.0.0", deps=(("opt-c", ">=1.0.0", True),)),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    assert [entry.extension_name for entry in lock.entries] == ["tool-a"]
    assert len(lock.skipped_optional) == 1
    assert "cycle" in lock.skipped_optional[0].reason


def test_optional_range_violating_locked_version_is_skipped() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=2.0.0", False),)),
            _entry("opt-c", "1.0.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    # opt-c exists but only at a version the optional range refuses: the
    # branch cannot resolve (its own required selection finds no candidate),
    # so it is skipped with the reason; tool-a is unaffected and opt-c is
    # NOT locked.
    assert [entry.extension_name for entry in lock.entries] == ["tool-a"]
    assert "cannot resolve" in lock.skipped_optional[0].reason


def test_optional_never_overrides_a_required_selection() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=2.0.0", False),)),
            _entry("opt-c", "1.0.0"),
            _entry("opt-c", "2.0.0"),
        ]
    )
    requests = [
        RootRequest(extension_name="tool-a"),
        RootRequest(extension_name="opt-c", range_text="<2.0.0"),
    ]
    lock = resolve_lock(requests, catalog)
    locked = lock.get("opt-c")
    assert locked is not None
    # The required selection (<2.0.0) stands; the optional >=2.0.0 cannot
    # upgrade it and is recorded as skipped instead.
    assert locked.semantic_version == "1.0.0"
    assert locked.kind is LockKind.REQUIRED
    assert any(skip.target == "opt-c" for skip in lock.skipped_optional)


def test_optional_dependency_on_satisfying_locked_version_only_associates() -> None:
    # tool-a requires lib-b AND optionally depends on it (two declarations on
    # one entry): the required selection stands, the optional edge adds only
    # the association and its recorded (optional) constraint.
    catalog = _cat(
        [
            _entry(
                "tool-a",
                "1.0.0",
                deps=(("lib-b", ">=1.0.0", True), ("lib-b", ">=1.0.0", False)),
            ),
            _entry("lib-b", "1.2.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    locked = lock.get("lib-b")
    assert locked is not None
    assert locked.kind is LockKind.REQUIRED
    assert locked.optional_for == ("tool-a",)
    assert any(not constraint.required for constraint in locked.constraints)
    assert locked.required_by == ("tool-a",)
    assert lock.skipped_optional == ()


def test_first_optional_branch_wins_and_the_second_is_recorded() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("shared", ">=1.0.0", False),)),
            _entry("tool-b", "1.0.0", deps=(("shared", "<1.0.0", False),)),
            _entry("shared", "0.9.0"),
            _entry("shared", "1.5.0"),
        ]
    )
    lock = resolve_lock(
        [RootRequest(extension_name="tool-a"), RootRequest(extension_name="tool-b")], catalog
    )
    # Edges process in (requirer, target, range) order: tool-a's >=1.0.0 pins
    # shared@1.5.0; tool-b's <1.0.0 cannot re-select and is skipped.
    shared = lock.get("shared")
    assert shared is not None
    assert shared.kind is LockKind.OPTIONAL
    assert shared.optional_for == ("tool-a",)
    assert len(lock.skipped_optional) == 1
    assert lock.skipped_optional[0].requirer == "tool-b"
    assert "does not satisfy" in lock.skipped_optional[0].reason


def test_optional_entries_contribute_their_own_optional_edges() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("opt-c", ">=1.0.0", False),)),
            _entry("opt-c", "1.0.0", deps=(("opt-d", "*", False),)),
            _entry("opt-d", "1.0.0"),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    assert {entry.extension_name for entry in lock.entries} == {"tool-a", "opt-c", "opt-d"}
    deep = lock.get("opt-d")
    assert deep is not None
    assert deep.kind is LockKind.OPTIONAL
    assert deep.optional_for == ("opt-c",)


# ---------------------------------------------------------------------------
# Explain: the operator answer to "why this extension, why this version".
# ---------------------------------------------------------------------------


def test_explain_reports_request_reason_constraints_and_rejections() -> None:
    catalog = _cat(
        [
            _entry("tool-a", "1.0.0"),
            _entry("tool-a", "1.4.0"),
            _entry("tool-a", "2.0.0"),
        ]
    )
    lock = resolve_lock(_one_root(range_text=">=1.0.0,<2.0.0"), catalog)
    explanation = lock.explain("tool-a")
    assert explanation is not None
    assert explanation.entry.semantic_version == "1.4.0"
    assert explanation.present_because == "requested directly by the install request"
    assert explanation.policy
    assert [constraint.origin for constraint in explanation.constraints] == [ROOT_REQUEST_ORIGIN]
    assert {rejected.semantic_version for rejected in explanation.rejected} == {"1.0.0", "2.0.0"}
    assert explanation.skipped_optional == ()


def test_explain_reports_required_and_optional_reasons_and_skips() -> None:
    catalog = _cat(
        [
            _entry(
                "tool-a",
                "1.0.0",
                deps=(
                    ("lib-b", ">=1.0.0", True),
                    ("opt-c", "*", False),
                    ("opt-failing", "*", False),
                ),
            ),
            _entry("lib-b", "1.2.0"),
            _entry("opt-c", "1.0.0"),
            _entry("opt-failing", "1.0.0", deps=(("lib-x", ">=9.0.0", True),)),
        ]
    )
    lock = resolve_lock(_one_root(), catalog)
    lib_b = lock.explain("lib-b")
    assert lib_b is not None
    assert lib_b.present_because == "required by tool-a"
    opt_c = lock.explain("opt-c")
    assert opt_c is not None
    assert opt_c.present_because.startswith("optional dependency of tool-a")
    tool_a = lock.explain("tool-a")
    assert tool_a is not None
    assert [skip.target for skip in tool_a.skipped_optional] == ["opt-failing"]
    assert "cannot resolve" in tool_a.skipped_optional[0].reason


def test_explain_of_an_unlocked_extension_is_none() -> None:
    lock = resolve_lock(_one_root(), _cat([_entry("tool-a", "1.0.0")]))
    assert lock.explain("no-such-extension") is None


# ---------------------------------------------------------------------------
# diff_locks: the update-time identity view.
# ---------------------------------------------------------------------------


def test_diff_locks_reports_added_removed_and_changed_identities() -> None:
    old_catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True),)),
            _entry("lib-b", "1.2.0"),
            _entry("going-away", "1.0.0"),
        ]
    )
    new_catalog = _cat(
        [
            _entry("tool-a", "1.0.0", deps=(("lib-b", ">=1.0.0", True),)),
            _entry("lib-b", "1.3.0"),
            _entry("fresh", "2.0.0"),
        ]
    )
    old = resolve_lock(
        [RootRequest(extension_name="tool-a"), RootRequest(extension_name="going-away")],
        old_catalog,
    )
    new = resolve_lock(
        [RootRequest(extension_name="tool-a"), RootRequest(extension_name="fresh")],
        new_catalog,
    )
    diff = diff_locks(old, new)
    assert [identity.extension_name for identity in diff.added] == ["fresh"]
    assert [identity.extension_name for identity in diff.removed] == ["going-away"]
    assert len(diff.changed) == 1
    old_identity, new_identity = diff.changed[0]
    assert old_identity.semantic_version == "1.2.0"
    assert new_identity.semantic_version == "1.3.0"


def _cat(entries: list[Any]) -> ExtensionCatalog:
    return ExtensionCatalog(entries=tuple(entries))

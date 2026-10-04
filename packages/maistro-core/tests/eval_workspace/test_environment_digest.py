"""Environment-digest determinism (#107).

The environment digest is the identity every matched comparison stands on.
These tests pin the two properties it must have: the same environment hashes
the same in every construction, and any difference that would invalidate a
comparison -- fixture content, egress, resources, isolation floor, projection
schema -- hashes differently.
"""

from __future__ import annotations

import hashlib

import pytest

from maistro.eval_workspace.digest import (
    DIGEST_SCHEMA_VERSION,
    canonical_json,
    content_digest,
    environment_digest,
)
from maistro.eval_workspace.model import FixtureEntry, FixtureManifest

from .conftest import fixture_digest, sandbox_config, scoped_grant


def _digest(sandbox: object = None, fixtures: FixtureManifest | None = None) -> str:
    return environment_digest(
        image="python:3.12-slim",
        sandbox=sandbox if sandbox is not None else sandbox_config(),
        fixtures_digest=(fixtures or FixtureManifest()).digest,
    )


def test_same_environment_same_digest_across_constructions() -> None:
    """Equal environments hash equal -- digest identity, not object identity."""
    assert _digest() == _digest()


def test_fixture_content_change_changes_digest() -> None:
    """Different fixture bytes are a different environment, not a warm hit."""
    a = FixtureManifest(
        entries=(FixtureEntry(name="task.json", content_sha256=fixture_digest(b"v1")),)
    )
    b = FixtureManifest(
        entries=(FixtureEntry(name="task.json", content_sha256=fixture_digest(b"v2")),)
    )
    assert a.digest != b.digest
    assert _digest(fixtures=a) != _digest(fixtures=b)


def test_manifest_digest_independent_of_entry_order() -> None:
    """The same fixture set in a different order is the same manifest."""
    entries = [
        FixtureEntry(name=f"f{i}.txt", content_sha256=fixture_digest(f"c{i}".encode()))
        for i in range(4)
    ]
    assert (
        FixtureManifest(entries=tuple(entries)).digest
        == FixtureManifest(entries=tuple(reversed(entries))).digest
    )


def test_duplicate_fixture_names_rejected() -> None:
    """Two entries with one name is an ambiguous fixture set."""
    entry = FixtureEntry(name="task.json", content_sha256=fixture_digest(b"x"))
    manifest = FixtureManifest(entries=(entry, entry.model_copy()))
    try:
        manifest.validate_unique_names()
    except ValueError as exc:
        assert "unique" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate fixture names were accepted")


def test_egress_grant_change_changes_digest() -> None:
    """A wider egress grant is a different environment."""
    deny = _digest()
    scoped = environment_digest(
        image="python:3.12-slim",
        sandbox=sandbox_config(egress=scoped_grant("pypi.org:443")),
        fixtures_digest=FixtureManifest().digest,
    )
    assert deny != scoped


def test_resource_limits_change_digest() -> None:
    assert _digest() != _digest(sandbox=sandbox_config(memory_mb=512))


def test_isolation_floor_change_changes_digest() -> None:
    assert _digest() != _digest(sandbox=sandbox_config(min_isolation="gvisor"))


def test_env_and_path_ordering_irrelevant() -> None:
    """Canonicalization: insertion order never changes the digest."""
    one = sandbox_config(env={"A": "1", "B": "2"}, writable_paths=["/tmp", "/work"])
    two = sandbox_config(env={"B": "2", "A": "1"}, writable_paths=["/work", "/tmp"])
    assert _digest(one) == _digest(two)


def test_canonical_json_is_stable_and_sorted() -> None:
    assert canonical_json({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'
    assert canonical_json({"b": 1, "a": [2, 1]}) == canonical_json({"a": [2, 1], "b": 1})


def test_content_digest_is_sha256_of_bytes() -> None:
    assert content_digest(b"state") == hashlib.sha256(b"state").hexdigest()
    # Empty content is a state, not an absence.
    assert content_digest(b"") == hashlib.sha256(b"").hexdigest()


def test_projection_version_bump_fails_digests_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema bump changes every digest: old and new never compare equal."""
    assert DIGEST_SCHEMA_VERSION == 1
    before = _digest()
    monkeypatch.setattr("maistro.eval_workspace.digest.DIGEST_SCHEMA_VERSION", 2)
    assert _digest() != before

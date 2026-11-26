"""Grants and the least-authority context (#974)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from maistro_ext_harness import (
    ExtensionHost,
    GrantPolicy,
    GrantPolicyError,
    build_context,
    reference_fixtures,
    resolve_grants,
)
from maistro_ext_harness.manifest import load_manifest_bytes


def _manifest(valid_manifest: dict[str, Any], **overrides: object) -> Any:
    rich = {
        **valid_manifest,
        "capabilities": ["workspace.read", "agent.read", "run.read"],
        "data": {"scopes": ["workspace"]},
        **overrides,
    }
    return load_manifest_bytes(json.dumps(rich))


def test_full_declaration_becomes_the_grant(valid_manifest: dict[str, Any]) -> None:
    manifest = _manifest(valid_manifest)
    grant = resolve_grants(manifest)
    assert grant.equals_declaration(manifest)
    assert grant.has_capability("workspace.read")


def test_policy_narrows_the_declaration(valid_manifest: dict[str, Any]) -> None:
    manifest = _manifest(valid_manifest)
    grant = resolve_grants(manifest, GrantPolicy(capabilities={"workspace.read"}))
    assert grant.capabilities == frozenset({"workspace.read"})
    assert not grant.has_capability("agent.read")
    assert grant.data_scopes == frozenset({"workspace"})


def test_policy_naming_undeclared_authority_fails_loudly(
    valid_manifest: dict[str, Any],
) -> None:
    """A policy is a restriction; a name the manifest never declared is a
    configuration error, not a silent grant of nothing."""
    manifest = _manifest(valid_manifest)
    with pytest.raises(GrantPolicyError, match=r"secrets\.read"):
        resolve_grants(manifest, GrantPolicy(capabilities={"secrets.read"}))


def test_context_hides_views_without_their_capability(
    valid_manifest: dict[str, Any],
) -> None:
    manifest = _manifest(valid_manifest)
    grant = resolve_grants(manifest, GrantPolicy(capabilities={"workspace.read"}))
    fx = reference_fixtures()
    context = build_context(
        grant, identity=fx.identity, workspace=fx.workspace, invocation=fx.invocation
    )
    assert context.workspace is not None
    assert context.workspace.workspace_id.startswith("fx-")
    assert context.identity is None  # agent.read not granted: invisible, not denied
    assert context.invocation is None
    assert not context.has_capability("agent.read")
    assert not context.has_capability("not-an-authority-name")


def test_host_applies_policy_at_load(
    make_extension: Any,
) -> None:
    """The lifecycle's grant stage is where the policy bites; the loaded
    context must reflect the narrowed grant, not the declaration."""
    from maistro_ext_harness.manifest import ManifestRejected  # noqa: F401

    root = make_extension(
        manifest={
            "id": "acme.widget",
            "publisher": "acme",
            "version": "1.0.0",
            "title": "t",
            "description": "d",
            "contract": ">=1.0.0,<2.0.0",
            "family": "tool",
            "capabilities": ["workspace.read", "agent.read"],
            "effects": ["read-only"],
            "data": {"scopes": []},
            "entrypoint": {"module": "acme_widget.plugin", "object": "PLUGIN"},
        },
    )
    host = ExtensionHost(policy=GrantPolicy(capabilities={"workspace.read"}))
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)
    try:
        assert loaded.context.capabilities == frozenset({"workspace.read"})
        assert loaded.context.identity is None
    finally:
        host.release(loaded)

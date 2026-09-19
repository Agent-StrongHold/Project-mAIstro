"""Task admission scope HTTP contract coverage (#234)."""

import pytest

from maistro.tasks.http_contract import (
    sign_delegation_context,
    sign_workspace_scope,
    verify_delegation_context,
    verify_workspace_scope_signature,
)


def test_delegation_context_preserves_service_and_originating_principals() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="alice",
        key="bridge-key",
        now=100,
        delegation_id="stable-evidence",
    )

    context = verify_delegation_context(token, "bridge-key", now=120)

    assert context.service_principal == "conductor"
    assert context.originating_principal == "alice"
    assert context.delegation_id == "stable-evidence"
    assert context.expires_at == 400


def test_delegation_context_rejects_tampering_wrong_key_and_expiry() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="alice",
        key="bridge-key",
        now=100,
    )

    with pytest.raises(ValueError):
        verify_delegation_context(token + "x", "bridge-key", now=100)
    with pytest.raises(ValueError):
        verify_delegation_context(token, "wrong-key", now=100)
    with pytest.raises(ValueError, match="expired"):
        verify_delegation_context(token, "bridge-key", now=401)


def test_system_delegation_has_an_explicit_system_actor() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="system",
        principal_kind="system",
        key="bridge-key",
        now=100,
    )

    assert verify_delegation_context(token, "bridge-key", now=100).principal_kind == "system"


def test_workspace_scope_signature_is_bound_to_workspace_and_key() -> None:
    signature = sign_workspace_scope("workspace-a", "key-a")

    assert verify_workspace_scope_signature("workspace-a", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-b", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-a", signature, "key-b")

"""Task admission scope HTTP contract coverage (#234)."""

from maistro.tasks.http_contract import sign_workspace_scope, verify_workspace_scope_signature


def test_workspace_scope_signature_is_bound_to_workspace_and_key() -> None:
    signature = sign_workspace_scope("workspace-a", "key-a")

    assert verify_workspace_scope_signature("workspace-a", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-b", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-a", signature, "key-b")

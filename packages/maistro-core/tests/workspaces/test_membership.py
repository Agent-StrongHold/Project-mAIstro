from __future__ import annotations

import pytest

from maistro.workspaces import WorkspaceMembership, WorkspaceRole


@pytest.mark.parametrize(
    ("role", "can_use", "can_contribute", "can_administer"),
    [
        (WorkspaceRole.MEMBER, True, False, False),
        (WorkspaceRole.CONTRIBUTOR, True, True, False),
        (WorkspaceRole.OWNER, True, True, True),
    ],
)
def test_workspace_role_tiers(
    role: WorkspaceRole,
    can_use: bool,
    can_contribute: bool,
    can_administer: bool,
) -> None:
    membership = WorkspaceMembership(workspace_id="ws-1", user_id="alice", role=role)
    assert membership.can_use is can_use
    assert membership.can_contribute is can_contribute
    assert membership.can_administer is can_administer


def test_membership_represents_ownership_separately_from_workspace_identity() -> None:
    owner = WorkspaceMembership(
        workspace_id="ws-1",
        user_id="alice",
        role=WorkspaceRole.OWNER,
    )
    co_owner = WorkspaceMembership(
        workspace_id="ws-1",
        user_id="bob",
        role=WorkspaceRole.OWNER,
    )

    assert owner.workspace_id == co_owner.workspace_id
    assert owner.user_id != co_owner.user_id
    assert owner.can_administer is True
    assert co_owner.can_administer is True

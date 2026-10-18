"""Admission identity for canonical Runs (#1152).

Reads are scoped by :mod:`maistro.runs.scoped_reads` (Workspace membership,
foreign == missing). This module holds the other half of the seam: who a Run
is *admitted as*. ``RunAuthorization`` carries the authenticated principal and,
when execution is delegated, the acting principal it stands in for; admission
resolves the immutable identity facts from it, so accounting attribution can
never be minted from caller text or Run metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maistro.runs.store_boundary import require_admitted_actor
from maistro.security.sentinel.authz_types import Principal

if TYPE_CHECKING:
    from maistro.graph.definitions import Graph


@dataclass(frozen=True, slots=True)
class RunAuthorization:
    """Authenticated and, optionally, delegated identity for Run admission.

    ``authenticated_principal`` is the identity that crossed the auth boundary.
    ``acting_principal`` is the identity on whose behalf the execution runs;
    it must be the authenticated identity or an agent owned by it. Keeping both
    facts prevents delegation from being collapsed into a caller-controlled
    ``actor_principal_id`` string.
    """

    workspace_id: str
    project_id: str
    authenticated_principal: Principal
    acting_principal: Principal | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not self.project_id.strip():
            raise ValueError("Run authorization requires non-empty scope identity")
        acting = self.acting_principal or self.authenticated_principal
        if acting.id != self.authenticated_principal.id and (
            acting.kind != "agent" or acting.owner != self.authenticated_principal.id
        ):
            raise ValueError("acting principal must be authenticated or owned by the authenticator")

    @property
    def initiating_principal_id(self) -> str:
        return self.authenticated_principal.id

    @property
    def acting_principal_id(self) -> str:
        return (self.acting_principal or self.authenticated_principal).id


def admission_identity_fields(
    graph: Graph,
    *,
    authorization: RunAuthorization | None,
    legacy_actor_principal_id: str | None,
) -> dict[str, str]:
    """Resolve immutable Run identity facts before a Run can be persisted."""
    if authorization is None:
        actor = require_admitted_actor(legacy_actor_principal_id)
        return {
            "actor_principal_id": actor,
            "initiating_principal_id": actor,
            "acting_principal_id": actor,
        }
    if (
        authorization.workspace_id != graph.workspace_id
        or authorization.project_id != graph.project_id
    ):
        raise ValueError("Run authorization scope must match the Graph scope")
    if (
        legacy_actor_principal_id is not None
        and legacy_actor_principal_id != authorization.acting_principal_id
    ):
        raise ValueError("actor_principal_id does not match the authenticated acting principal")
    return {
        "actor_principal_id": authorization.acting_principal_id,
        "initiating_principal_id": authorization.initiating_principal_id,
        "acting_principal_id": authorization.acting_principal_id,
    }


__all__ = [
    "RunAuthorization",
    "admission_identity_fields",
    "require_admitted_actor",
]

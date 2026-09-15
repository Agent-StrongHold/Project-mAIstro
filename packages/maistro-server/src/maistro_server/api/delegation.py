"""Shared Conductor delegation resolution for task and Run boundaries."""

from __future__ import annotations

import os

from fastapi import HTTPException, status

from maistro.tasks.http_contract import verify_delegation_context
from maistro_server.api.principal import AuthenticatedPrincipal


def resolve_delegated_identity(
    auth: AuthenticatedPrincipal | None,
    delegation: str | None,
) -> tuple[str, str, str | None, str]:
    """Resolve an effective actor from service auth and signed delegation.

    The request body and ordinary user-id headers are never authority. A
    delegation is accepted only when its signed service claim matches the
    independently authenticated bearer principal.
    """
    if delegation is None:
        owner = "dev" if auth is None else auth.user_id
        service = owner
        actor_kind = "service" if auth is not None else "system"
        return owner, service, None, actor_kind
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delegation requires an authenticated service principal",
        )
    try:
        context = verify_delegation_context(delegation, os.getenv("TASK_DELEGATION_KEY", ""))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delegation assertion is not authorized",
        ) from exc
    if context.service_principal != auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delegation service principal does not match authenticated caller",
        )
    return (
        context.originating_principal,
        context.service_principal,
        context.delegation_id,
        context.principal_kind,
    )


__all__ = ["resolve_delegated_identity"]

"""Small convergence contract for package-local event projections (#61).

This does not ban domain event objects. It makes the dangerous fields visible:
identity, stream ordering and cross-execution correlation are universal Event
concerns. A package projection may carry one of these only when a migration
explicitly classifies it as metadata rather than treating it as canonical.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

CANONICAL_EVENT_AUTHORITY_FIELDS = frozenset(
    {
        "event_id",
        "sequence",
        "stream_id",
        "workspace_id",
        "correlation_id",
        "causation_id",
    }
)


class ParallelEventAuthority(ValueError):
    """A package event projection claims canonical Event authority fields."""


def event_authority_fields(model: type[Any] | Any) -> frozenset[str]:
    """Return universal authority-shaped fields declared by ``model``."""
    target = model if isinstance(model, type) else type(model)
    if is_dataclass(target):
        names = {field.name for field in fields(target)}
    else:
        names = set(getattr(target, "__annotations__", {}))
    return frozenset(names & CANONICAL_EVENT_AUTHORITY_FIELDS)


def require_metadata_only_projection(
    model: type[Any] | Any,
    *,
    metadata_fields: frozenset[str] = frozenset(),
) -> None:
    """Reject undeclared package-local universal Event authority.

    ``metadata_fields`` is intentionally explicit at each migration seam. For
    example, a transport-local counter may remain useful for debugging, but it
    must be named as metadata rather than silently competing with the canonical
    per-Workspace sequence assigned by ``EventStore``.
    """
    authority = event_authority_fields(model)
    undeclared = authority - metadata_fields
    if undeclared:
        names = ", ".join(sorted(undeclared))
        raise ParallelEventAuthority(f"package event projection owns canonical fields: {names}")


__all__ = [
    "CANONICAL_EVENT_AUTHORITY_FIELDS",
    "ParallelEventAuthority",
    "event_authority_fields",
    "require_metadata_only_projection",
]

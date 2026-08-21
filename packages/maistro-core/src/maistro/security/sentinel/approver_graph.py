"""Approver graph — declarative policy-matrix resolution (SPEC-246 / ADR-068 §C)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from maistro.security.sentinel.authz_types import Principal

DEFAULT_APPROVER = "role:admin"


@dataclass(frozen=True)
class ApproverBinding:
    """A configurable (action, for-scope) -> approved-by relational binding."""

    action: str
    for_scope: str
    approved_by: str


def _scope_prefix(scope: str) -> str:
    return scope.partition(":")[0]


class ApproverGraph:
    """Resolves who may satisfy a delegated-approval for a given action/scope pair."""

    def __init__(
        self, bindings: Sequence[ApproverBinding], principals: Sequence[Principal] = ()
    ) -> None:
        """Store the ordered bindings and the principal directory used by members()."""
        self._bindings = list(bindings)
        self._principals = list(principals)

    def resolve(self, action: str, requester_scope: str) -> str:
        """Most-specific (action, for_scope) match's approved_by; "role:admin" if none."""
        for binding in self._bindings:
            if binding.action == action and binding.for_scope == requester_scope:
                return binding.approved_by

        requester_prefix = _scope_prefix(requester_scope)
        for binding in self._bindings:
            if binding.action != action:
                continue
            wildcard_prefix, _, suffix = binding.for_scope.partition(":")
            if suffix == "*" and wildcard_prefix == requester_prefix:
                return binding.approved_by

        return DEFAULT_APPROVER

    def members(self, scope: str) -> set[str]:
        """Resolve a scope string to current principal IDs; unknown scopes return an empty set."""
        prefix, _, value = scope.partition(":")
        if prefix == "role":
            return {p.id for p in self._principals if value in p.roles}
        if prefix:
            return {p.id for p in self._principals if scope in p.scopes}
        return set()

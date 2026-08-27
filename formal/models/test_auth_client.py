"""I28: Service Key Client Headers — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.client import ServiceKeyClient


def _make_identity(scopes=None):
    return ServiceIdentity(
        name="test-service",
        key_hash="a" * 64,
        scopes=frozenset(scopes or {Scope.TASK_READ}),
    )

"""Shared fixtures for eval-workspace tests (#107)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.eval_workspace.digest import sha256_hex
from maistro.eval_workspace.pool import WorkspacePool
from maistro.eval_workspace.service import EvalWorkspaceService
from maistro.eval_workspace.store import InMemoryEvalWorkspaceStore
from maistro.sandbox.network import EgressGrant, EgressMode
from maistro.sandbox.protocol import SandboxConfig


#: A fixture content helper -- tests name fixtures and hash bytes through the
#: same digest path the substrate uses, so a test cannot diverge from it.
def fixture_digest(content: bytes) -> str:
    return sha256_hex(content)


@pytest.fixture
def store() -> InMemoryEvalWorkspaceStore:
    return InMemoryEvalWorkspaceStore()


@pytest.fixture
def service(store: InMemoryEvalWorkspaceStore) -> EvalWorkspaceService:
    return EvalWorkspaceService(store)


@pytest.fixture
def pool(store: InMemoryEvalWorkspaceStore, service: EvalWorkspaceService) -> WorkspacePool:
    return WorkspacePool(store=store, service=service)


def sandbox_config(**overrides: Any) -> SandboxConfig:
    defaults: dict[str, Any] = {
        "memory_mb": 256,
        "cpu_cores": 1.0,
        "timeout_s": 120,
        "min_isolation": "container",
    }
    defaults.update(overrides)
    return SandboxConfig(**defaults)


def scoped_grant(*allow: str) -> EgressGrant:
    return EgressGrant(
        mode=EgressMode.SCOPED,
        allow=tuple(allow),
        reason="eval harness under test grants these destinations",
    )

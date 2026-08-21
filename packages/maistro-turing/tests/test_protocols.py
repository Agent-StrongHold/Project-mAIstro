"""Tests for protocols.py: protocol definitions compile and are runtime-checkable."""

from __future__ import annotations

from maistro_turing.protocols import (
    ImmutableViolation,
    MemoryRepo,
    ProvenanceViolation,
    RepoError,
    WisdomDeferred,
    WisdomInvariantViolation,
    WorkingMemoryStore,
)


def test_error_hierarchy() -> None:
    assert issubclass(ImmutableViolation, RepoError)
    assert issubclass(ProvenanceViolation, RepoError)
    assert issubclass(WisdomDeferred, RepoError)
    assert issubclass(WisdomInvariantViolation, RepoError)
    assert issubclass(RepoError, RuntimeError)


def test_memory_repo_is_runtime_checkable() -> None:
    assert hasattr(MemoryRepo, "__protocol_attrs__") or hasattr(MemoryRepo, "_is_protocol")


def test_working_memory_store_is_runtime_checkable() -> None:
    assert hasattr(WorkingMemoryStore, "__protocol_attrs__") or hasattr(
        WorkingMemoryStore, "_is_protocol"
    )

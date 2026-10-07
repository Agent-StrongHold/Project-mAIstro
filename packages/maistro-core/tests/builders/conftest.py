"""Shared builders test defaults for canonical Run admission."""

from __future__ import annotations

import pytest

from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

TEST_ACTOR_PRINCIPAL_ID = DEFAULT_TEST_ACTOR_PRINCIPAL_ID


@pytest.fixture(autouse=True)
def _default_builders_actor_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default missing principals for compatibility canonical entrypoints in builders."""
    import maistro.runs.store as run_store

    original = run_store.require_admitted_actor

    def _require(actor_principal_id: str | None) -> str:
        if actor_principal_id is None or not str(actor_principal_id).strip():
            return DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        return original(actor_principal_id)

    monkeypatch.setattr(run_store, "require_admitted_actor", _require)

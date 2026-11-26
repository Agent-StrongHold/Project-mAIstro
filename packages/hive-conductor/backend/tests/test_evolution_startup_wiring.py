"""Evolve startup wiring (#1064): store selection, attach guards, restore fallbacks.

The durable-snapshot and restart-replay suites prove the happy restore path
against real stores. This module proves the *startup decision surface* a
restarted process walks before any cycle can run:

* ``select_domain_store`` must honestly pick the backend the deployment can
  back — the canonical owner's asyncpg pool (production fence), a sqlite
  file URL (single-instance twin), or nothing (memory-backed deployments
  must not pretend a cross-process ledger exists);
* ``attach_domain_store`` must refuse to attach over live domain state and
  ignore double attaches, or the durable truth and live memory could drift;
* ``restore_or_initialize_domain_state`` must fall back to the historical
  fresh init — recording an honest public failure, not a fabricated restore
  — when the workspace key is missing, the store is broken, or no snapshot
  exists;
* ``workspace_id`` must resolve (or honestly refuse to resolve) the durable
  ledger key from the canonical owner.

All cases are service-free: the canonical owner is a double, so the
no-services coverage producer measures every branch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import services.evolution as evolution_module
import services.evolution_graph as evolution_graph_module
from services.evolution import EvolutionUnavailableError
from services.evolve_domain_store import (
    InMemoryEvolveDomainStore,
    PgEvolveDomainStore,
    SqliteEvolveDomainStore,
)


def _fresh_service() -> Any:
    """A real _EvolutionService with no engine configured (owner unavailable)."""
    return evolution_module._EvolutionService()


# ----- select_domain_store: the honest backend pick -----


def test_select_domain_store_prefers_the_owner_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The container contract: ``pg_pool`` is the asyncpg pool (``db_pool`` is
    # a separate SQLite connection), so PostgreSQL is selected only from it.
    pool = object()
    owner = SimpleNamespace(db_pool=None, pg_pool=pool)
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)

    store = evolution_module.select_domain_store()

    assert isinstance(store, PgEvolveDomainStore)
    assert store.backend == "postgres"
    assert store._pool is pool


def test_select_domain_store_never_takes_a_sqlite_db_pool_for_postgres(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Regression (Codex review): a real SQLite-backed container's ``db_pool"

    is its sqlite3 connection — selecting PostgreSQL from it produced a
    ``PgEvolveDomainStore`` whose ``ensure_schema`` fails on the missing
    ``acquire()``. The sqlite URL must win instead.
    """

    db_path = tmp_path / "conductor.db"
    owner = SimpleNamespace(
        db_pool=object(),  # sqlite3 connection stand-in: no acquire()
        pg_pool=None,
        config=SimpleNamespace(database_url=f"sqlite:///{db_path}"),
    )
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)

    store = evolution_module.select_domain_store()

    assert not isinstance(store, PgEvolveDomainStore)
    assert isinstance(store, SqliteEvolveDomainStore)
    assert store.backend == "sqlite"
    assert store._path == str(db_path)


def test_select_domain_store_sqlite_file_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    db_path = tmp_path / "conductor.db"
    owner = SimpleNamespace(
        db_pool=None,
        pg_pool=None,
        config=SimpleNamespace(database_url=f"sqlite:///{db_path}"),
    )
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)

    store = evolution_module.select_domain_store()

    assert isinstance(store, SqliteEvolveDomainStore)
    assert store.backend == "sqlite"
    assert store._path == str(db_path)


def test_select_domain_store_refuses_memory_sqlite_and_unbacked_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An in-memory sqlite URL would silently pretend cross-process durability.
    memory_owner = SimpleNamespace(config=SimpleNamespace(database_url="sqlite://:memory:"))
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: memory_owner)
    assert evolution_module.select_domain_store() is None

    # A non-sqlite URL has no honest file-backed twin.
    postgres_url_owner = SimpleNamespace(
        config=SimpleNamespace(database_url="postgresql://maistro:maistro@db/x")
    )
    monkeypatch.setattr(
        evolution_graph_module, "canonical_execution_owner", lambda: postgres_url_owner
    )
    assert evolution_module.select_domain_store() is None

    # Owner doubles (and degraded engines) may carry no config at all.
    configless_owner = SimpleNamespace(db_pool=None, pg_pool=None, config=None)
    monkeypatch.setattr(
        evolution_graph_module, "canonical_execution_owner", lambda: configless_owner
    )
    assert evolution_module.select_domain_store() is None


# ----- workspace_id: the durable ledger key -----


def test_workspace_id_resolves_from_owner_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(config=SimpleNamespace(workspace_id="ws-7"))
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)
    assert _fresh_service().workspace_id == "ws-7"


def test_workspace_id_is_none_without_owner_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evolution_graph_module,
        "canonical_execution_owner",
        lambda: SimpleNamespace(config=None),
    )
    assert _fresh_service().workspace_id is None

    empty_config_owner = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(
        evolution_graph_module,
        "canonical_execution_owner",
        lambda: empty_config_owner,
    )
    assert _fresh_service().workspace_id is None


def test_workspace_id_is_none_when_no_canonical_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> None:
        raise evolution_graph_module.CanonicalExecutionUnavailable("no engine")

    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", _raise)
    assert _fresh_service().workspace_id is None


# ----- attach_domain_store: refuse drift between durable truth and live state -----


def test_attach_domain_store_is_idempotent() -> None:
    service = _fresh_service()
    store = InMemoryEvolveDomainStore()
    service.attach_domain_store(store)

    replacement = InMemoryEvolveDomainStore()
    service.attach_domain_store(replacement)

    assert service.domain_store is store


def test_attach_domain_store_refuses_live_domain_state() -> None:
    service = _fresh_service()
    service._population = object()
    service._tournament = object()

    with pytest.raises(RuntimeError, match="before initialize_domain_state"):
        service.attach_domain_store(InMemoryEvolveDomainStore())


# ----- restore_or_initialize_domain_state: honest fallbacks -----


async def _restore_with_workspace(
    service: Any, workspace: str | None, monkeypatch: pytest.MonkeyPatch
) -> bool:
    monkeypatch.setattr(
        evolution_module._EvolutionService,
        "workspace_id",
        property(lambda self: workspace),
    )
    return await service.restore_or_initialize_domain_state()


async def test_restore_without_workspace_key_initializes_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _fresh_service()
    service.attach_domain_store(InMemoryEvolveDomainStore())

    restored = await _restore_with_workspace(service, None, monkeypatch)

    assert restored is False
    assert service.domain_restore is None
    # The historical fresh init ran: inspectable state, not a durable restore.
    assert service._population is not None
    assert service._tournament is not None
    # No durable restore was attempted, so nothing is fail-closed.
    assert service._restore_failed_reason is None


async def test_restore_with_broken_store_falls_back_and_records_public_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenStore(InMemoryEvolveDomainStore):
        async def latest_snapshot(self, workspace_id: str, *, kind: str | None = None) -> None:
            raise RuntimeError("disk on fire")

    service = _fresh_service()
    service.attach_domain_store(_BrokenStore())

    restored = await _restore_with_workspace(service, "ws-1", monkeypatch)

    assert restored is False
    assert service.domain_restore is None
    # The failure is honest: the public kind-only text (no exception message),
    # surfaced exactly as /status would report it.
    assert service._last_cycle_error == ("RuntimeError: evolution failed; see server logs")
    # A broken durable store must not fabricate a restore — but the process
    # still ends with inspectable fresh state.
    assert service._population is not None


async def test_broken_restore_fails_closed_against_admission_and_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed durable restore must keep execution/publication blocked.

    The historical fallback fresh state is honest for inspection, but a
    healthy canonical engine must not let manual/cadence admission capture
    that fabricated population as the newest snapshot and advance the
    journal watermark past the durable battles a later restore must replay.
    """

    class _BrokenStore(InMemoryEvolveDomainStore):
        async def latest_snapshot(self, workspace_id: str, *, kind: str | None = None) -> None:
            raise RuntimeError("disk on fire")

    service = _fresh_service()
    service.attach_domain_store(_BrokenStore())
    await _restore_with_workspace(service, "ws-1", monkeypatch)

    # Even with a healthy canonical engine, availability stays off and the
    # reason names the restore, not the engine.
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: object())
    service._refresh_execution_availability()
    assert service._execution_available is False
    assert service._availability == "unavailable"
    assert "restore" in (service._availability_reason or "")

    # The manual admission boundary refuses the same way (the /cycle route
    # maps this to a 503).
    with pytest.raises(EvolutionUnavailableError, match="restore"):
        await service._run_one_cycle_locked()
    assert service._execution_available is False

    # ...and the failure is observable in the /status payload.
    assert "restore" in (service.status()["restore_failed"] or "")


async def test_restore_without_any_snapshot_initializes_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _fresh_service()
    service.attach_domain_store(InMemoryEvolveDomainStore())

    restored = await _restore_with_workspace(service, "ws-1", monkeypatch)

    assert restored is False
    assert service.domain_restore is None
    assert service._population is not None
    assert service._tournament is not None
    # An empty-but-healthy store is not a restore failure: nothing fail-closed.
    assert service._restore_failed_reason is None


def test_domain_restore_property_reports_the_last_restore() -> None:
    service = _fresh_service()
    assert service.domain_restore is None

    report = {"run_id": "run-1", "kind": "committed"}
    service._domain_restore = report
    assert service.domain_restore is report

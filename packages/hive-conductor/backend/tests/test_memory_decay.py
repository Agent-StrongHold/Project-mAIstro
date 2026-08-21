"""Episodic memory-decay cadence in the conductor (SPEC-080126-9e42).

The gap being closed (#344) was that `tick_decay` had no production caller. So the
test that matters here is the one that goes through the **real app lifespan** — the
same path a deployed conductor takes — rather than constructing a driver by hand.
If that wiring is removed, `test_lifespan_starts_the_decay_cadence` fails.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
import services.memory_decay as decay_mod
from fastapi.testclient import TestClient
from main import app

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier


@pytest.fixture(autouse=True)
async def _reset_driver():
    """Each test owns the module singleton; never leak a live task across tests."""
    await decay_mod.stop_memory_decay()
    yield
    await decay_mod.stop_memory_decay()


def _mem(memory_id: str = "m1", weight: float = 0.8) -> EpisodicMemory:
    from datetime import UTC, datetime, timedelta

    return EpisodicMemory(
        memory_id=memory_id,
        tier=MemoryTier.LESSON,
        weight=weight,
        content="a thing that happened",
        org_id="org-1",
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        decay_rate=1.0,
        last_accessed_at=datetime.now(UTC) - timedelta(hours=1),
    )


async def _seeded_store() -> InMemoryEpisodicStore:
    store = InMemoryEpisodicStore()
    await store.store(_mem())
    return store


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: object) -> None:
    monkeypatch.setattr(decay_mod, "_resolve_episodic_store", lambda: store)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **fields: object) -> None:
    """Override `Settings` fields; `get_settings` is lru_cached so env won't do.

    `main` did `from config import get_settings`, so its module-level binding has
    to be patched too or the lifespan keeps reading the real settings.
    """
    from config import get_settings

    base = get_settings()

    class _S:
        def __getattr__(self, name: str) -> object:
            return fields[name] if name in fields else getattr(base, name)

    monkeypatch.setattr("config.get_settings", lambda: _S())
    monkeypatch.setattr("main.get_settings", lambda: _S())


@pytest.fixture
def isolated_lifespan(monkeypatch: pytest.MonkeyPatch):
    """Run the app's real lifespan without letting its other subsystems fight the suite.

    `lifespan` shuts the foundation down on exit, which closes the process-wide
    SQLite state writer that the rest of the session-scoped suite still needs — so
    booting the app for real inside a test poisons every test after it.

    The subject here is the decay wiring, so only the unrelated collaborators are
    neutralised. `main.lifespan` itself, its call to `start_memory_decay`, the
    driver, and its background task are all the genuine article: if the wiring in
    `main.py` is removed, these tests fail.
    """
    import main as main_mod

    class _NoopService:
        async def start_foundation(self, *a: object, **k: object) -> None: ...
        async def stop_foundation(self, *a: object, **k: object) -> None: ...
        async def start_engine(self, *a: object, **k: object) -> None: ...
        async def stop_engine(self, *a: object, **k: object) -> None: ...

    noop = _NoopService()
    monkeypatch.setattr(main_mod, "foundation_service", noop)
    monkeypatch.setattr(main_mod, "engine_service", noop)
    monkeypatch.setattr("settings_defaults.apply_default_settings_if_needed", lambda: None)
    monkeypatch.setattr("services.dag_run_store.install_pm_event_bridge", lambda: None)
    monkeypatch.setattr("services.scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("services.scheduler.stop_scheduler", lambda: None)

    async def _anoop(*a: object, **k: object) -> None: ...

    monkeypatch.setattr("services.design_service.start_design_service", _anoop)
    monkeypatch.setattr("services.design_service.stop_design_service", _anoop)
    monkeypatch.setattr("services.evolution.start_evolution", _anoop)
    monkeypatch.setattr("services.evolution.stop_evolution", _anoop)
    yield


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("timed out waiting for the decay cadence")


class TestRealSchedulingPath:
    async def test_lifespan_starts_the_decay_cadence(
        self, monkeypatch: pytest.MonkeyPatch, isolated_lifespan: None
    ) -> None:
        """The whole point: booting the app makes episodic memory actually forget.

        Nothing here calls `tick_decay`, `apply_decay` or `run_once`. The app's
        lifespan starts the driver and its background task does the work.
        """
        store = await _seeded_store()
        _patch_store(monkeypatch, store)
        _patch_settings(monkeypatch, memory_decay_interval_s=0.02)

        with TestClient(app):  # runs the real lifespan
            driver = decay_mod.get_decay_driver()
            assert driver is not None, "lifespan did not start the decay driver"
            await _wait_until(lambda: driver.ticks >= 1)

        assert store._memories[0].weight < 0.8, "cadence ran but the store did not decay"

    async def test_lifespan_stops_the_cadence_on_shutdown(
        self, monkeypatch: pytest.MonkeyPatch, isolated_lifespan: None
    ) -> None:
        store = await _seeded_store()
        _patch_store(monkeypatch, store)
        _patch_settings(monkeypatch, memory_decay_interval_s=0.02)

        with TestClient(app):
            driver = decay_mod.get_decay_driver()
            await _wait_until(lambda: driver.ticks >= 1)

        assert decay_mod.get_decay_driver() is None
        assert driver.running is False


class TestServiceWiring:
    async def test_start_returns_a_running_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = await _seeded_store()
        _patch_store(monkeypatch, store)
        _patch_settings(monkeypatch, memory_decay_interval_s=0.02)
        from config import get_settings

        driver = await decay_mod.start_memory_decay(get_settings())

        assert driver.enabled is True
        assert driver.state() == "running"

    async def test_start_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_store(monkeypatch, await _seeded_store())
        _patch_settings(monkeypatch, memory_decay_interval_s=0.02)
        from config import get_settings

        first = await decay_mod.start_memory_decay(get_settings())
        second = await decay_mod.start_memory_decay(get_settings())

        assert first is second

    async def test_missing_episodic_store_is_reported_not_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stub mode has no episodic memory — say so rather than pretend decay runs."""
        _patch_store(monkeypatch, None)
        _patch_settings(monkeypatch, memory_decay_interval_s=3600)
        from config import get_settings

        with caplog.at_level(logging.WARNING):
            driver = await decay_mod.start_memory_decay(get_settings())

        assert driver.state() == "no_store"
        assert "memory_decay_not_running" in caplog.text

    async def test_engine_exposes_no_episodic_store_in_stub_mode(self) -> None:
        """Stub mode has no core Container, so no episodic store — and says None."""
        from adapters.maistro_core import StubAgentPort
        from services.engine import EngineService

        svc = EngineService()
        svc._agent_port = StubAgentPort()

        assert svc.episodic_store is None

    async def test_engine_exposes_the_container_store_when_bridged(self) -> None:
        from services.engine import EngineService

        class _Container:
            episodic_store = "the-store"

        class _Bridge:
            container = _Container()

        svc = EngineService()
        svc._agent_port = _Bridge()

        assert svc.episodic_store == "the-store"


class TestDisabledIsLoud:
    """F3 precedent: a degraded mode indistinguishable from the bug is the defect."""

    async def test_disabled_driver_does_not_mutate_the_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = await _seeded_store()
        _patch_store(monkeypatch, store)
        _patch_settings(monkeypatch, memory_decay_interval_s=0)
        from config import get_settings

        driver = await decay_mod.start_memory_decay(get_settings())
        await asyncio.sleep(0.05)

        assert driver.enabled is False
        assert store._memories[0].weight == pytest.approx(0.8)

    async def test_disabled_warns_at_startup(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _patch_store(monkeypatch, await _seeded_store())
        _patch_settings(monkeypatch, memory_decay_interval_s=0)
        from config import get_settings

        with caplog.at_level(logging.WARNING):
            await decay_mod.start_memory_decay(get_settings())

        assert "episodic_decay_disabled" in caplog.text
        assert "MEMORY_DECAY_INTERVAL_S" in caplog.text

    def test_health_reports_degraded_when_decay_is_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_API_BASE", "http://gateway.example")
        monkeypatch.setattr(
            decay_mod,
            "memory_decay_status",
            lambda: {"enabled": False, "state": "disabled"},
        )

        data = TestClient(app).get("/health").json()

        assert data["status"] == "ok"  # still a 200 liveness probe, not an outage
        assert data["llm_configured"] is True
        assert data["memory_decay_enabled"] is False
        assert data["memory_decay"]["state"] == "disabled"
        assert data["degraded"] is True

    def test_health_reports_unwired_decay_as_degraded_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Configured decay is not healthy until a real driver/store is running."""
        monkeypatch.setenv("LITELLM_API_BASE", "http://gateway.example")

        data = TestClient(app).get("/health").json()

        assert data["memory_decay_enabled"] is False
        assert data["memory_decay"]["state"] != "running"
        assert data["degraded"] is True

    def test_ready_exposes_decay_without_flipping_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            decay_mod,
            "memory_decay_status",
            lambda: {"enabled": False, "state": "disabled"},
        )

        body = TestClient(app).get("/health/ready").json()

        assert body["checks"]["memory_decay"] is False
        assert body["ready"] is True


class TestObservability:
    async def test_status_reports_what_the_last_tick_touched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = await _seeded_store()
        await store.store(_mem("m2", weight=0.7))
        _patch_store(monkeypatch, store)
        _patch_settings(monkeypatch, memory_decay_interval_s=0.02)
        from config import get_settings

        driver = await decay_mod.start_memory_decay(get_settings())
        await _wait_until(lambda: driver.ticks >= 1)

        status = decay_mod.memory_decay_status()
        assert status["enabled"] is True
        assert status["ticks"] >= 1
        assert status["last_tick"]["scanned"] == 2

    def test_status_before_start_reports_from_configuration(self) -> None:
        status = decay_mod.memory_decay_status()

        assert status["enabled"] is True
        assert status["state"] == "stopped"

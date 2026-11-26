"""The app lifespan's startup recovery wiring (#1823, AC-4).

A crash between the Goal and brief writes — or after the durable commit but
before its response — leaves a resumable commit record behind. The lifespan is
what resumes them on the next boot: the recovery protocol itself is held
against real PostgreSQL by `test_brief_commit.py`; what only these tests can
hold is the *wiring* — that the shipped app lifespan actually calls the sweep
at startup, reports what it resumed, and that a recovery failure is caught and
logged instead of aborting the boot (the same containment the scheduler's
start-failure warning above it in `lifespan` gets).

They run the real `main.lifespan` with every unrelated subsystem neutralised,
the same way `test_memory_decay.py` isolates the cadence wiring: if the
recovery block is removed from `main.py`, both tests fail.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

pytestmark = [pytest.mark.contract("boundary")]


@pytest.fixture
def isolated_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boot the real lifespan with the collaborators recovery does not own
    turned off. Mirrors `test_memory_decay.py`'s fixture of the same name:
    `lifespan` shuts the foundation down on exit, which would close the
    process-wide SQLite state writer the rest of the session still needs."""
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
    monkeypatch.setattr("services.scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("services.scheduler.stop_scheduler", lambda: None)

    async def _anoop(*a: object, **k: object) -> None: ...

    monkeypatch.setattr("services.design_service.start_design_service", _anoop)
    monkeypatch.setattr("services.design_service.stop_design_service", _anoop)
    monkeypatch.setattr("services.evolution.start_evolution", _anoop)
    monkeypatch.setattr("services.evolution.stop_evolution", _anoop)
    monkeypatch.setattr("services.memory_decay.start_memory_decay", _anoop)
    monkeypatch.setattr("services.memory_decay.stop_memory_decay", _anoop)


def _boot() -> None:
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app):
        pass


def test_lifespan_reports_the_commits_startup_resumed(
    isolated_lifespan: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Startup runs the recovery sweep and logs how many interrupted commits
    it resumed — the deterministic resume AC-4 asks for, visible on boot."""
    from services.brief_commit import CommitOutcome

    async def _one_pending(*a: Any, **k: Any) -> list[CommitOutcome]:
        return [
            CommitOutcome(
                status="committed",
                goal_id="g-resumed",
                goal_revision=1,
                brief_id="b-resumed",
                lineage_id="l-resumed",
                brief_version=1,
                recovered=True,
            )
        ]

    monkeypatch.setattr("services.brief_commit.recover_pending_commits", _one_pending)

    with caplog.at_level(logging.INFO, logger="hive.lifespan"):
        _boot()

    resumed = [r for r in caplog.records if "interrupted commit(s) resumed" in r.getMessage()]
    assert resumed, "the lifespan never reported the resumed commit"
    assert resumed[0].levelno == logging.INFO
    assert "brief_commit_recovery: 1" in resumed[0].getMessage()


def test_lifespan_survives_a_recovery_failure(
    isolated_lifespan: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A recovery sweep that cannot run (durable stores unreachable) is
    contained: the warning names the failure and the boot continues — an
    interrupted commit must not take the whole conductor down."""
    from services import brief_commit as brief_commit_mod

    async def _explodes(*a: Any, **k: Any) -> list[Any]:
        raise RuntimeError("goal store unreachable during recovery")

    monkeypatch.setattr(brief_commit_mod, "recover_pending_commits", _explodes)

    with caplog.at_level(logging.WARNING, logger="hive.lifespan"):
        _boot()

    failures = [r for r in caplog.records if "brief_commit_recovery_failed" in r.getMessage()]
    assert failures, "the recovery failure was swallowed silently"
    assert failures[0].levelno == logging.WARNING
    assert "goal store unreachable during recovery" in failures[0].getMessage()

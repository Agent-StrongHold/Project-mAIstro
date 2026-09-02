"""Application-local bootstrap state used by the startup health probe."""

from __future__ import annotations

from enum import StrEnum

from fastapi import FastAPI


class StartupPhase(StrEnum):
    """Lifecycle phases relevant to serving the configured application role."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    COMPLETE = "complete"
    FAILED = "failed"


_STATE_ATTRIBUTE = "maistro_startup_phase"


def get_startup_phase(app: FastAPI) -> StartupPhase:
    """Return the app's phase, failing closed for missing or invalid state."""
    phase = getattr(app.state, _STATE_ATTRIBUTE, StartupPhase.NOT_STARTED)
    return phase if isinstance(phase, StartupPhase) else StartupPhase.FAILED


def set_startup_phase(app: FastAPI, phase: StartupPhase) -> None:
    """Record a lifecycle transition on this app instance."""
    setattr(app.state, _STATE_ATTRIBUTE, phase)

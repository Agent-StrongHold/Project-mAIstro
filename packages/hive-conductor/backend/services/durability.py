"""Declared state durability — SPEC-082926-87bb, ADR-082926-87bb.

`Foundation._init_state` used to catch every exception from opening SQLite,
wiring the stores and loading them, and fall through to in-memory stores. The
process reported healthy and lost everything at restart (#333).

The repair is not a better `except`. It is that **ephemeral state is a declared
mode**: `CONDUCTOR_DURABILITY` says whether this deployment requires state that
outlives the process, and in `durable` mode a failure is *recorded* — readiness
false, writes refused — rather than substituted with an in-memory stand-in
wearing the same interface.

One `StateStatus` is recorded at startup and every surface that describes state
durability reads it, so `/health`, `/health/ready` and the settings record
cannot disagree about what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args

DurabilityMode = Literal["durable", "ephemeral"]

#: The declared modes, derived from the type so the two cannot drift.
MODES: tuple[str, ...] = get_args(DurabilityMode)


class InvalidDurabilityMode(ValueError):
    """`CONDUCTOR_DURABILITY` was set to something that is not a mode."""


class StoreUnavailableError(RuntimeError):
    """A store promised durability and did not get it, so it refuses writes.

    Raised by `ModelStore`/`JsonStore` mutation, and translated to `503` at the
    HTTP boundary. Reads are deliberately not refused: a reader that gets a 503
    learns nothing that the failed write has not already told the operator, and
    seeded read-only data is still useful.
    """


@dataclass(frozen=True)
class StateStatus:
    """What was asked for, what was obtained, and why they differ."""

    requested: DurabilityMode
    backend: str
    durable: bool
    writes_refused: bool
    error: str | None = None

    @property
    def satisfied(self) -> bool:
        """Whether the deployment got the durability it declared."""
        return self.durable or self.requested == "ephemeral"

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "backend": self.backend,
            "durable": self.durable,
            "writes_refused": self.writes_refused,
            "error": self.error,
            "satisfied": self.satisfied,
        }


_status: StateStatus | None = None


def read_mode(raw: str | None) -> DurabilityMode:
    """Parse a declared mode, refusing anything else.

    An unset value is the documented default. An unrecognised one is not: a
    mode is a declaration, and silently defaulting an unreadable declaration is
    the same class of mistake as inferring ephemeral state from a stack trace.
    """
    if raw is None or not raw.strip():
        return "durable"
    value = raw.strip().lower()
    if value not in MODES:
        raise InvalidDurabilityMode(
            f"CONDUCTOR_DURABILITY must be one of {', '.join(MODES)}; got {raw!r}"
        )
    return "durable" if value == "durable" else "ephemeral"


def record(status: StateStatus) -> None:
    """Record the startup outcome. Called once, by the Foundation."""
    global _status
    _status = status


def status() -> StateStatus | None:
    """The recorded outcome, or None if startup has not recorded one.

    None and a failed status mean different things and callers must not
    conflate them: None is "state initialisation has not run", which is what an
    app object built without a lifespan looks like. Reporting that as a
    durability failure would make every such caller unready for a requirement
    nothing has yet tried to meet.
    """
    return _status


def reset() -> None:
    """Forget the recorded outcome. For tests and re-initialisation."""
    global _status
    _status = None


def writes_refused() -> bool:
    """Whether a recorded outcome says durable writes cannot be taken."""
    return _status is not None and _status.writes_refused


def health_view() -> dict[str, Any]:
    """The `state` block for `/health`."""
    if _status is None:
        return {
            "requested": None,
            "backend": "unstarted",
            "durable": False,
            "writes_refused": False,
            "error": None,
            "satisfied": True,
        }
    return _status.as_dict()


def durability_satisfied() -> bool:
    """Readiness input: did a declared durability requirement fail?

    True when nothing has been recorded — see `status()`.
    """
    return _status is None or _status.satisfied

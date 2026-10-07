"""Test-only deterministic failpoint machinery (#883 prototype).

Three pieces, each smaller than the seams it instruments:

:class:`CrashPoint`
    A transparent wrapper over any store object that raises
    :class:`CrashSimulated` at one named method -- before the write commits or
    after it lands. This is the forced-interleaving discipline the existing
    kill-recovery evidence already uses (`tests/runs/test_crash_window_invariants.py`,
    `tests/capabilities/test_invocation_reconciliation.py`), generalized so one
    wrapper can carry any store's seam instead of every test hand-rolling its
    own `_KillAt`. A crash is a `BaseException`, not an `Exception`: no executor
    boundary may absorb what a real SIGKILL never delivers. The wrapper fires
    at most once and must be armed explicitly -- machinery that crashes on its
    own is machinery no other test can share a process with.

:class:`StatusJournal`
    Records every status observation a scenario makes, in order, and reports
    regressions: once an entity is observed terminal it must never be observed
    non-terminal again. "Terminal state cannot regress" is one of the issue's
    key properties; this is the oracle that checks it over the whole timeline
    rather than at one endpoint.

:class:`EffectLedger`
    The remote system's own record of applied effects. The provider call count
    a test asserts is evidence only if the ledger is the ground truth the
    provider writes before the crash can hit the ledger's persistence -- so
    the executor writes here first and the crash lands after, which is exactly
    the ambiguous ordering a real crash-after-effect produces.

Nothing here is imported by anything under `packages/*/src`. The
`test_failpoint_machinery_inert` suite holds that boundary and the
armed-before-firing contract.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


class CrashSimulated(BaseException):
    """A process death at a named failpoint.

    `BaseException` deliberately: the execution spine catches `Exception` at
    several layers to record honest failure evidence, and none of them may see
    this. A real SIGKILL writes no disposition, and neither does the crash
    this stands in for.
    """

    def __init__(self, failpoint: str, mode: str) -> None:
        super().__init__(f"process killed at failpoint {failpoint!r} ({mode} the write)")
        self.failpoint = failpoint
        self.mode = mode


def _always(*_args: Any, **_kwargs: Any) -> bool:
    return True


@dataclass(frozen=True)
class Failpoint:
    """One named crash point carried by one store method.

    `when` discriminates among the calls the method receives (a
    `transition_run` also carries non-terminal targets), so a seam can be
    "the COMPLETED write" rather than "the third write". `before=True` kills
    instead of the write; `before=False` lets the write commit and kills
    before anything after it runs -- the crash-after-effect ordering.
    """

    name: str
    method: str
    when: Callable[..., bool] = _always
    before: bool = False


class CrashPoint:
    """A store whose process dies at one armed failpoint, exactly once.

    Disarmed, the wrapper is pass-through: identical results, no bookkeeping
    between the caller and the store. Arming is explicit, which is what keeps
    the machinery from altering the semantics of any scenario that did not ask
    to crash.
    """

    def __init__(self, inner: Any, failpoints: Iterable[Failpoint] = ()) -> None:
        self._inner = inner
        self._failpoints: dict[str, Failpoint] = {f.name: f for f in failpoints}
        self._armed: str | None = None
        #: Every firing, in order, as `(name, mode)` -- the scenario's crash log.
        self.fired: list[tuple[str, str]] = []

    def arm(self, name: str) -> None:
        """Arm one failpoint. The next matching call kills the scenario."""
        if name not in self._failpoints:
            raise KeyError(f"unknown failpoint {name!r}")
        self._armed = name

    def disarm(self) -> None:
        self._armed = None

    @property
    def armed(self) -> str | None:
        return self._armed

    def __getattr__(self, name: str) -> Any:
        operation = getattr(self._inner, name)
        armed = self._armed
        if armed is None or name != self._failpoints[armed].method:
            return operation

        spec = self._failpoints[armed]

        async def call(*args: Any, **kwargs: Any) -> Any:
            if not spec.when(*args, **kwargs):
                return await operation(*args, **kwargs)
            self._armed = None  # a crash ends the process; nothing fires twice
            self.fired.append((spec.name, "before" if spec.before else "after"))
            if spec.before:
                raise CrashSimulated(spec.name, "before")
            await operation(*args, **kwargs)
            raise CrashSimulated(spec.name, "after")

        return call


class StatusJournal:
    """Ordered status observations, and the terminal-regression oracle.

    Wrap a store and every `transition_run` / `transition_node_run` /
    `transition_attempt` / invocation `save` records `(entity, status)` in
    call order. `regressions()` then answers one question over the whole
    timeline: was any entity ever observed non-terminal after it had already
    been observed terminal?
    """

    TERMINAL_RUN = frozenset({"completed", "failed", "cancelled", "timed_out"})
    TERMINAL_ATTEMPT = frozenset({"completed", "failed", "cancelled", "timed_out", "yielded"})
    TERMINAL_INVOCATION = frozenset({"completed", "failed", "unknown"})

    def __init__(self) -> None:
        self.observations: list[tuple[str, str, str]] = []  # (kind, entity, status)

    def record(self, kind: str, entity: str, status: str) -> None:
        self.observations.append((kind, entity, status))

    def regressions(self) -> list[tuple[str, str, str, str]]:
        """Every `(kind, entity, terminal, later_non_terminal)` violation."""
        terminal_seen: dict[tuple[str, str], str] = {}
        violations: list[tuple[str, str, str, str]] = []
        for kind, entity, status in self.observations:
            terminal = {
                "run": self.TERMINAL_RUN,
                "node_run": self.TERMINAL_RUN,
                "attempt": self.TERMINAL_ATTEMPT,
                "invocation": self.TERMINAL_INVOCATION,
            }[kind]
            key = (kind, entity)
            if status in terminal:
                terminal_seen.setdefault(key, status)
            elif key in terminal_seen:
                violations.append((kind, entity, terminal_seen[key], status))
        return violations

    def statuses(self, kind: str, entity: str) -> list[str]:
        return [status for k, e, status in self.observations if k == kind and e == entity]


class JournalingStore:
    """StatusJournal's write-side wrapper; transparent like CrashPoint."""

    def __init__(self, inner: Any, journal: StatusJournal) -> None:
        self._inner = inner
        self._journal = journal

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def transition_run(self, run_id: str, status: Any, **kwargs: Any) -> Any:
        landed = await self._inner.transition_run(run_id, status, **kwargs)
        self._journal.record("run", run_id, str(getattr(status, "value", status)))
        return landed

    async def transition_node_run(self, node_run_id: str, status: Any, **kwargs: Any) -> Any:
        landed = await self._inner.transition_node_run(node_run_id, status, **kwargs)
        self._journal.record("node_run", node_run_id, str(getattr(status, "value", status)))
        return landed

    async def transition_attempt(self, attempt_id: str, status: Any, **kwargs: Any) -> Any:
        landed = await self._inner.transition_attempt(attempt_id, status, **kwargs)
        self._journal.record("attempt", attempt_id, str(getattr(status, "value", status)))
        return landed

    async def save(self, invocation: Any) -> Any:
        landed = await self._inner.save(invocation)
        self._journal.record(
            "invocation",
            invocation.invocation_id,
            str(getattr(landed.status, "value", landed.status)),
        )
        return landed


class EffectLedger:
    """The remote system's ground truth for one external effect.

    The modeled provider applies here *before* returning, so a crash after the
    provider call leaves the ledger holding an effect the engine's ledger may
    not know about -- the ambiguous ordering the properties are about.
    """

    def __init__(self) -> None:
        self.applied: list[str] = []

    def apply(self, effect_key: str) -> None:
        self.applied.append(effect_key)

    def count(self, effect_key: str) -> int:
        return self.applied.count(effect_key)


@dataclass
class ScenarioRecord:
    """One matrix cell's evidence, for the research report's yield numbers."""

    operation: str
    failpoint: str
    mode: str
    recovery: str
    crash_fired: bool = False
    #: Free-form expected-disposition tag asserted by the scenario.
    disposition: str = ""
    notes: list[str] = field(default_factory=list)

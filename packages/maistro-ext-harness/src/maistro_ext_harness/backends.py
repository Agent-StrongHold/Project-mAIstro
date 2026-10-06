"""Real-backend requirements: fail closed, never silently skip (#974).

Some properties cannot be mocked honestly: a connector's real egress
behavior, a provider's real streaming semantics, a sandbox's real
filesystem enforcement. A case that needs a real service *declares* it via
`requires_backend`; the runner then behaves the way the issue pins:

- the backend is probed before the case runs;
- an unavailable backend **fails** the case (exit-red), naming the missing
  service — it does not silently skip, which would dress an unverified
  property up as a result;
- skipping is possible only through an explicit, recorded waiver
  (`--allow-missing-backend NAME`), and the report lists every waiver so a
  reader can see exactly which properties did not execute. A typo'd waiver
  is loud on its own: the case it was meant for still finds its backend
  unavailable and fails.

The harness ships no backend probes itself: which real service proves a
family's honesty is the family plug-in's decision (the provider/connector
suites land with their SDK slices). The registry is the seam they register
into, and the fail-closed semantics here are what they inherit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["Backend", "BackendRegistry"]


@dataclass(frozen=True)
class Backend:
    """One real service a case may require, plus the way to probe it.

    `probe` returns True when the service is reachable and usable. It is
    called at most once per run and must not raise (a probe that raises is
    an unavailable backend, not a harness crash).
    """

    name: str
    probe: Callable[[], bool]


@dataclass
class BackendRegistry:
    """The run's registered backends and the explicit missing-backend waivers."""

    backends: dict[str, Backend] = field(default_factory=dict)
    waivers: frozenset[str] = frozenset()

    def register(self, backend: Backend) -> None:
        self.backends[backend.name] = backend

    def probe(self, name: str) -> bool:
        """Whether backend `name` is usable. Unregistered means unavailable."""
        backend = self.backends.get(name)
        if backend is None:
            return False
        try:
            return bool(backend.probe())
        except Exception:
            return False

    def waived(self, name: str) -> bool:
        """Whether `name` carries an explicit recorded waiver."""
        return name in self.waivers

"""Renderer capability substrate — SPEC-070426-a22b / ADR-070426-f2a0.

External renderers are *optional* capability providers behind ``maistro-design``. The
design boundary is unchanged (ADR-061): ``DesignEngine`` builds a prompt stack; a
``RenderProvider`` consumes it and returns an :class:`ArtifactNode` tree.

Two states, kept strictly separate:

* **Absence** — a provider that is not installed / not discovered fills no slots, so the
  skills that need those slots are silently filtered out of the offered set. There is no
  call site, nothing to fail, and no error is raised.
* **Failure** — a provider that *was* discovered but errors at render time is a real
  fault: it is circuit-broken (its slots are emptied until the next successful discovery)
  and the error is surfaced to the caller who invoked that render.

``RenderSlot.FIXED_PAGE`` is the canvas-native floor: always filled, never supplied by an
external plugin, so a zero-plugin install is still a complete fixed-layout designer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro_design.types import DesignError, RenderSlot

if TYPE_CHECKING:
    from maistro_design.types import ArtifactNode, DesignSkill

logger = logging.getLogger("maistro.design.renderers")

# The plugin-free floor: filled unconditionally by the built-in canvas exporters
# (SPEC-070426-457b) — fixed pages and multi-page decks — so a zero-plugin install is a
# complete fixed-layout designer. Only reflowable-web and video are truly external.
NATIVE_SLOTS: frozenset[RenderSlot] = frozenset({RenderSlot.FIXED_PAGE, RenderSlot.DECK})


class RenderProviderError(DesignError):
    """A discovered provider failed at render time (circuit-broken)."""

    code = "RENDER_PROVIDER_ERROR"


class RenderSlotUnavailableError(DesignError):
    """Render was requested for a slot no live provider fills."""

    code = "RENDER_SLOT_UNAVAILABLE"


@dataclass(frozen=True)
class RendererDiscovery:
    """Outcome of probing a :class:`RenderProvider`. Constructed via :meth:`up`/:meth:`down`."""

    available: bool
    slots: frozenset[RenderSlot] = frozenset()

    @classmethod
    def up(cls, slots: Iterable[RenderSlot]) -> RendererDiscovery:
        return cls(available=True, slots=frozenset(slots))

    @classmethod
    def down(cls) -> RendererDiscovery:
        return cls(available=False, slots=frozenset())


@runtime_checkable
class RenderProvider(Protocol):
    """An optional renderer. ``discover()`` must never raise; ``render()`` may."""

    slots: tuple[RenderSlot, ...]

    async def discover(self) -> RendererDiscovery: ...

    async def render(self, prompt_stack: str, skill: DesignSkill) -> ArtifactNode: ...


def available_skills(
    skills: Iterable[DesignSkill], filled_slots: frozenset[RenderSlot]
) -> list[DesignSkill]:
    """Skills whose required capability slot is filled. A skill with ``render_slot=None``
    needs no external renderer (canvas-native) and is therefore always available.

    This filters on the capability-slot axis only. The orthogonal legacy
    ``DesignSkill.required_renderer`` (html/svg/typography rasterizers) remains guarded at
    generation time by ``DesignEngine._check_renderer_available``; no shipped built-in sets
    it. A future skill that needs a rasterizer should also carry the matching ``render_slot``
    so it is filtered here rather than advertised and then failing in ``generate``.
    """
    return [s for s in skills if s.render_slot is None or s.render_slot in filled_slots]


@dataclass
class _ProviderState:
    provider: RenderProvider
    slots: frozenset[RenderSlot] = frozenset()  # slots filled as of the last discovery
    tripped: bool = False  # circuit breaker open after a render failure


class RendererRegistry:
    """Holds renderer providers, tracks which slots are filled, and enforces the
    absence-vs-failure split. Thread-safe."""

    def __init__(self, *, native_slots: frozenset[RenderSlot] = NATIVE_SLOTS) -> None:
        self._native = frozenset(native_slots)
        self._providers: list[_ProviderState] = []
        self._lock = threading.RLock()

    def register(self, provider: RenderProvider) -> None:
        with self._lock:
            self._providers.append(_ProviderState(provider))

    async def discover_all(self) -> frozenset[RenderSlot]:
        """Probe every provider. Absence (or a misbehaving ``discover``) => no slots. A
        successful discovery also clears any tripped circuit breaker."""
        for state in list(self._providers):
            try:
                result = await state.provider.discover()
            except Exception:
                logger.warning("discover() raised for %r; treating as down", state.provider)
                result = RendererDiscovery.down()
            with self._lock:
                state.slots = result.slots if result.available else frozenset()
                state.tripped = False
        return self.filled_slots()

    def filled_slots(self) -> frozenset[RenderSlot]:
        """Native floor plus the slots of every discovered, non-tripped provider."""
        with self._lock:
            slots = set(self._native)
            for state in self._providers:
                if not state.tripped:
                    slots |= state.slots
            return frozenset(slots)

    def available_skills(self, skills: Iterable[DesignSkill]) -> list[DesignSkill]:
        return available_skills(skills, self.filled_slots())

    async def render(self, slot: RenderSlot, prompt_stack: str, skill: DesignSkill) -> ArtifactNode:
        """Render via the live provider for ``slot``. Raises
        :class:`RenderSlotUnavailableError` if none is live, or
        :class:`RenderProviderError` (and trips the breaker) if the provider fails."""
        with self._lock:
            state = self._live_state_for(slot)
        if state is None:
            msg = f"no live provider fills slot {slot!r}"
            raise RenderSlotUnavailableError(msg)
        try:
            return await state.provider.render(prompt_stack, skill)
        except Exception as exc:
            with self._lock:
                state.tripped = True  # failure => circuit-break until next discovery
            logger.warning("render() failed for slot %s; tripping breaker", slot)
            msg = f"render provider for slot {slot!r} failed"
            raise RenderProviderError(msg) from exc

    def _live_state_for(self, slot: RenderSlot) -> _ProviderState | None:
        if slot in self._native:
            return None  # native slots are rendered by the canvas floor, not a provider
        for state in self._providers:
            if not state.tripped and slot in state.slots:
                return state
        return None

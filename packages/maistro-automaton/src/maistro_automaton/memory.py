"""EpisodeSink: the persistence port that makes an automaton persistent.

The machinery never stores. It emits Episodes — every fired action, every
refusal, every observed outcome — and the HOST decides what durability means.
This is the seam that lets the same actor machinery drive an in-memory test,
a SQLite-backed train tender, or (someday, behind its own activation gate) a
cognitive runtime, without the machinery knowing or caring which.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maistro_automaton.types import Episode


@runtime_checkable
class EpisodeSink(Protocol):
    """Accepts Episodes; returns a host-assigned reference or empty string.

    Sinks must not raise on episode write — an actor that dies because its
    diary is full stops being an actor. Hosts that can fail (full disk,
    locked DB) buffer, degrade, or drop with a local warning; the next tick
    is always coming.
    """

    def store_episode(self, episode: Episode) -> str: ...

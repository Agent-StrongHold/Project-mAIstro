"""Drive computation: stable traits crossed with fast mood, into pressure.

The insight borrowed intact from the Turing sketches: an automaton should not
act because it was prompted, and not because a cron fired — it should act
because *internal state crossed a threshold*. Drives are that internal state:
deterministic weighted sums over slow personality facets and fast mood
attributes, clamped to a ceiling. Same ticks in, same drives out.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from maistro_automaton.types import DriveSpec

DEFAULT_FACET_SCALE = 5.0


class MoodContractError(AttributeError):
    """Raised when a mood object lacks an attribute a DriveSpec names.

    Subclasses AttributeError so generic callers keep compatibility, but the
    message names the missing attribute and the drive that needed it — a mood
    contract that silently loses fields is a mood contract that lies.
    """

    def __init__(self, drive: str, source: str) -> None:
        self.drive = drive
        self.source = source
        super().__init__(
            f"drive {drive!r} reads mood attribute {source!r}; the mood object does not provide it"
        )


@runtime_checkable
class MoodLike(Protocol):
    """Anything with named float attributes can be a mood.

    Hosts define their own affective state (Turing's Mood has valence,
    arousal, focus; a merge train's has pressure, drought, churn); the
    machinery only reads the attributes its DriveSpecs name.
    """

    def __getattr__(self, name: str) -> float: ...


def compute_drive(
    spec: DriveSpec,
    facets: Mapping[str, float],
    mood: Any,
    *,
    facet_scale: float = DEFAULT_FACET_SCALE,
) -> float:
    """Sum one DriveSpec's terms against live state, clamped to the ceiling.

    Facet terms read ``facets[source]`` and normalize by ``facet_scale``
    (missing facets contribute 0 — absence of a trait is not an error, it is
    a low score). Mood terms read the attribute ``mood.<source>`` and raise
    :class:`MoodContractError` when absent — a mood contract that silently
    loses fields is a mood contract that lies.
    """
    total = 0.0
    for term in spec.terms:
        if term.kind.value == "facet":
            value = facets.get(term.source, 0.0) / facet_scale
        else:
            try:
                value = float(getattr(mood, term.source))
            except (AttributeError, TypeError) as exc:
                raise MoodContractError(spec.name, term.source) from exc
        total += term.weight * value
    return min(spec.ceiling, total)


def compute_drives(
    specs: tuple[DriveSpec, ...] | list[DriveSpec],
    facets: Mapping[str, float],
    mood: Any,
    *,
    facet_scale: float = DEFAULT_FACET_SCALE,
) -> dict[str, float]:
    """Compute every drive level for this tick. Pure; safe to memoize."""
    return {spec.name: compute_drive(spec, facets, mood, facet_scale=facet_scale) for spec in specs}

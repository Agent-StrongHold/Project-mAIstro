"""Entry-point discovery for capability providers (group: maistro.capabilities).

A provider package declares:
    [project.entry-points."maistro.capabilities"]
    my_provider = "my_pkg:make_provider"   # a zero-arg factory returning a CapabilityProvider
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.capabilities.registry import CapabilityRegistry

logger = logging.getLogger("maistro.capabilities.discovery")

GROUP = "maistro.capabilities"


def discover_into(
    registry: CapabilityRegistry,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
) -> int:
    """Load + register providers as installed-inactive. Returns count registered.

    Never raises on a single bad entry point — logs and continues. Pass
    `entry_points` to inject (tests); otherwise reads the live metadata group.
    """
    eps = entry_points if entry_points is not None else _live_entry_points()
    count = 0
    for ep in eps:
        try:
            factory = ep.load()
            provider = factory()
            registry.register(provider)
            count += 1
        except Exception as exc:  # discovery must be resilient — never raise on one bad EP
            logger.warning("Skipping capability entry point %r: %s", ep.name, exc)
    return count


def _live_entry_points() -> Iterable[EntryPoint]:
    try:
        return entry_points(group=GROUP)
    except Exception:
        return ()

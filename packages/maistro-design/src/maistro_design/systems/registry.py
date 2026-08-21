"""In-memory design system registry."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro_design.types import DesignSystem

logger = logging.getLogger("maistro.design.systems.registry")


class InMemoryDesignSystemRegistry:
    """Thread-safe in-memory registry for design systems."""

    def __init__(self) -> None:
        self._systems: dict[str, DesignSystem] = {}
        self._lock = threading.RLock()

    def register(self, system: DesignSystem) -> None:
        with self._lock:
            self._systems[system.slug] = system
        logger.debug("Registered design system: %s", system.slug)

    def get(self, slug: str) -> DesignSystem | None:
        return self._systems.get(slug)

    def list_all(self) -> list[DesignSystem]:
        return list(self._systems.values())

    def delete(self, slug: str) -> bool:
        with self._lock:
            if slug not in self._systems:
                return False
            del self._systems[slug]
        logger.debug("Deleted design system: %s", slug)
        return True

    def __len__(self) -> int:
        return len(self._systems)

    def __contains__(self, slug: str) -> bool:
        return slug in self._systems

"""A concrete Store implementation; other modules should depend on the Protocol, not this."""

from __future__ import annotations


class Store:
    def get(self, key: str) -> str:
        return key

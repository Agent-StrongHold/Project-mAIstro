"""The Store protocol — the abstraction other modules should depend on."""

from __future__ import annotations

from typing import Protocol


class Store(Protocol):
    def get(self, key: str) -> str: ...

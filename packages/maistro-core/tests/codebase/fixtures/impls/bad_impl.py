"""Violates Protocol-driven DI: imports a concrete sibling class directly."""

from __future__ import annotations

from impls.concrete_store import Store


def use_store(store: Store) -> str:
    return store.get("k")

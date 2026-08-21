"""Depends on the Store protocol abstraction — never imports a concrete sibling."""

from __future__ import annotations

from protocols.storage import Store


class GoodStore:
    def get(self, key: str) -> str:
        return key


def use_store(store: Store) -> str:
    return store.get("k")

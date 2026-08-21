"""ModelStore — dict-like store with optional SQLite persistence.

Wraps an in-memory dict that can be backed by PersistedStore. Routes
access stores exactly as before (``stores.missions[mid] = m``) but data
is persisted to SQLite when a PersistedStore is configured.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, ValuesView
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Domain services can register lifecycle invariants without making this generic
# storage module import those domains (which would create circular imports).
# Hooks run before the parent record is removed so a failing cascade leaves the
# parent addressable/retryable rather than creating half-deleted state.
_POP_HOOKS: dict[str, list[Callable[[str], None]]] = {}


def register_pop_hook(store_name: str, hook: Callable[[str], None]) -> None:
    """Register an idempotent callback that runs before a store item is removed."""
    hooks = _POP_HOOKS.setdefault(store_name, [])
    if hook not in hooks:
        hooks.append(hook)


class ModelStore:
    def __init__(
        self,
        store_name: str,
        model_class: type[BaseModel],
        persisted: Any | None = None,
    ) -> None:
        self._store_name = store_name
        self._model_class = model_class
        self._data: dict[str, T] = {}
        self._persisted = persisted

    def initialize(self) -> None:
        if self._persisted is None:
            return
        self._data = {
            m.id: m for m in self._persisted.list_all(self._store_name, self._model_class)
        }
        logger.info(
            "ModelStore(%s) loaded %d items from SQLite",
            self._store_name,
            len(self._data),
        )

    def values(self) -> ValuesView[T]:
        return self._data.values()

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str) -> T:
        return self._data[key]

    def __setitem__(self, key: str, value: T) -> None:
        self._data[key] = value
        if self._persisted is not None:
            self._persisted.put(self._store_name, key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def get(self, key: str, default: Any = None) -> T | Any:
        return self._data.get(key, default)

    def pop(self, key: str, *default: Any) -> T | Any:
        if key in self._data:
            for hook in _POP_HOOKS.get(self._store_name, ()):
                hook(key)
            if self._persisted is not None:
                self._persisted.delete(self._store_name, key)
            return self._data.pop(key)
        if default:
            return default[0]
        raise KeyError(key)

    def persist(self, key: str) -> None:
        if self._persisted is not None and key in self._data:
            self._persisted.put(self._store_name, key, self._data[key])


class JsonStore:
    def __init__(self, store_name: str, persisted: Any | None = None) -> None:
        self._store_name = store_name
        self._data: dict[str, Any] = {}
        self._persisted = persisted

    def initialize(self) -> None:
        if self._persisted is None:
            return
        for key, raw in self._persisted.list_all_raw(self._store_name):
            self._data[key] = json.loads(raw)
        logger.info(
            "JsonStore(%s) loaded %d items from SQLite",
            self._store_name,
            len(self._data),
        )

    def values(self) -> ValuesView:
        return self._data.values()

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        if self._persisted is not None:
            self._persisted.put_raw(self._store_name, key, json.dumps(value, default=str))

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def pop(self, key: str, *default: Any) -> Any:
        if key in self._data:
            if self._persisted is not None:
                self._persisted.delete(self._store_name, key)
            return self._data.pop(key)
        if default:
            return default[0]
        raise KeyError(key)

    def clear(self) -> int:
        """Remove every entry and return how many were removed.

        Routes each removal through ``pop`` so the backing PersistedStore sees
        the same per-key delete it sees for any other eviction — no second
        persistence path, and no bulk SQL that PgPersistedStore would not
        implement.
        """
        removed = 0
        for key in list(self._data.keys()):
            self.pop(key, None)
            removed += 1
        return removed

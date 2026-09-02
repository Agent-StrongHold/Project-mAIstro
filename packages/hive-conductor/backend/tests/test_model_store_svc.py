"""Boy Scout coverage: services/model_store.py (was 67%).

Covers ModelStore + JsonStore: dict-like CRUD, optional persistence
forwarding, KeyError defaults, initialize loading, persist flag for
ModelStore, JSON round-trip for JsonStore.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest
from pydantic import BaseModel

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


class _Model(BaseModel):
    id: str
    value: int


class _FakePersisted:
    def __init__(
        self, models: list[_Model] | None = None, raw: list[tuple[str, str]] | None = None
    ) -> None:
        self._models = models or []
        self._raw = raw or []
        self.put_calls: list[tuple[str, str, Any]] = []
        self.put_raw_calls: list[tuple[str, str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []

    def list_all(self, store_name: str, model_class: Any) -> list[Any]:
        return self._models

    def list_all_raw(self, store_name: str) -> list[tuple[str, str]]:
        return self._raw

    def put(self, store_name: str, key: str, value: Any) -> None:
        self.put_calls.append((store_name, key, value))

    def put_raw(self, store_name: str, key: str, raw: str) -> None:
        self.put_raw_calls.append((store_name, key, raw))

    def delete(self, store_name: str, key: str) -> None:
        self.delete_calls.append((store_name, key))


# --- ModelStore --------------------------------------------------------


def test_model_store_set_and_get_no_persist() -> None:
    from services.model_store import ModelStore

    s = ModelStore("ms", _Model)
    s["k"] = _Model(id="k", value=42)
    assert s["k"].value == 42
    assert "k" in s
    assert len(s) == 1
    assert list(iter(s)) == ["k"]
    assert s.get("missing", "default") == "default"
    assert list(s.keys()) == ["k"]
    assert any(v.id == "k" for v in s.values())
    assert any(k == "k" for k, _ in s.items())


def test_model_store_set_forwards_to_persisted() -> None:
    from services.model_store import ModelStore

    p = _FakePersisted()
    s = ModelStore("ms", _Model, persisted=p)
    s["k"] = _Model(id="k", value=1)
    assert p.put_calls and p.put_calls[0][0] == "ms"
    assert p.put_calls[0][1] == "k"


def test_model_store_pop_removes_and_forwards_delete() -> None:
    from services.model_store import ModelStore

    p = _FakePersisted()
    s = ModelStore("ms", _Model, persisted=p)
    s["k"] = _Model(id="k", value=1)
    out = s.pop("k")
    assert out.value == 1
    assert "k" not in s
    assert ("ms", "k") in p.delete_calls


def test_model_store_pop_returns_default_when_missing() -> None:
    from services.model_store import ModelStore

    s = ModelStore("ms", _Model)
    assert s.pop("nope", "default-value") == "default-value"


def test_model_store_pop_missing_no_default_raises_key_error() -> None:
    from services.model_store import ModelStore

    s = ModelStore("ms", _Model)
    with pytest.raises(KeyError):
        s.pop("nope")


def test_model_store_initialize_loads_from_persisted() -> None:
    from services.model_store import ModelStore

    p = _FakePersisted(models=[_Model(id="a", value=1), _Model(id="b", value=2)])
    s = ModelStore("ms", _Model, persisted=p)
    s.initialize()
    assert len(s) == 2
    assert s["a"].value == 1
    assert s["b"].value == 2


def test_model_store_initialize_noop_without_persisted() -> None:
    """Initialize with no persisted store should be a no-op."""
    from services.model_store import ModelStore

    s = ModelStore("ms", _Model)
    s["pre"] = _Model(id="pre", value=99)
    s.initialize()
    assert "pre" in s


def test_model_store_persist_method() -> None:
    from services.model_store import ModelStore

    p = _FakePersisted()
    s = ModelStore("ms", _Model, persisted=p)
    s._data["k"] = _Model(id="k", value=5)
    s.persist("k")
    assert p.put_calls and p.put_calls[0][1] == "k"


def test_model_store_persist_noop_when_key_missing() -> None:
    from services.model_store import ModelStore

    p = _FakePersisted()
    s = ModelStore("ms", _Model, persisted=p)
    s.persist("nope")
    assert p.put_calls == []


def test_model_store_get_with_implicit_none_default() -> None:
    from services.model_store import ModelStore

    s = ModelStore("ms", _Model)
    assert s.get("missing") is None


# --- JsonStore --------------------------------------------------------


def test_json_store_round_trip_in_memory() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    s["k"] = {"v": 1}
    assert s["k"] == {"v": 1}
    assert "k" in s
    assert len(s) == 1


def test_json_store_set_serializes_to_persisted() -> None:
    from services.model_store import JsonStore

    p = _FakePersisted()
    s = JsonStore("js", persisted=p)
    s["k"] = {"v": 7}
    # The persisted layer gets a JSON-encoded string
    assert p.put_raw_calls
    assert p.put_raw_calls[0][2] == '{"v": 7}'


def test_json_store_pop_removes_and_forwards_delete() -> None:
    from services.model_store import JsonStore

    p = _FakePersisted()
    s = JsonStore("js", persisted=p)
    s["k"] = {"x": 1}
    out = s.pop("k")
    assert out == {"x": 1}
    assert ("js", "k") in p.delete_calls


def test_json_store_pop_returns_default() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    assert s.pop("nope", {"default": True}) == {"default": True}


def test_json_store_pop_raises_key_error_without_default() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    with pytest.raises(KeyError):
        s.pop("nope")


def test_json_store_initialize_loads_and_parses_json() -> None:
    from services.model_store import JsonStore

    p = _FakePersisted(raw=[("a", '{"a": 1}'), ("b", '{"b": 2}')])
    s = JsonStore("js", persisted=p)
    s.initialize()
    assert s["a"] == {"a": 1}
    assert s["b"] == {"b": 2}


def test_json_store_initialize_noop_without_persisted() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    s["pre"] = {"keep": True}
    s.initialize()
    assert s["pre"] == {"keep": True}


def test_json_store_get_with_default() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    assert s.get("missing", "fallback") == "fallback"
    assert s.get("missing") is None


class _ConflictPersisted(_FakePersisted):
    def __init__(self) -> None:
        super().__init__()
        self.put_once_calls: list[tuple[str, str, str]] = []

    def put_raw_if_absent(self, store_name: str, key: str, raw: str) -> bool:
        self.put_once_calls.append((store_name, key, raw))
        return False

    def get_raw(self, store_name: str, key: str) -> str | None:
        return None


def test_json_store_put_if_absent_returns_false_when_key_present() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js")
    s["k"] = {"owner": "first"}
    assert s.put_if_absent("k", {"owner": "second"}) is False
    assert s["k"] == {"owner": "first"}


def test_json_store_put_if_absent_requires_conflict_safe_backend() -> None:
    from services.model_store import JsonStore

    s = JsonStore("js", persisted=_FakePersisted())
    with pytest.raises(RuntimeError, match="conflict-safe inserts"):
        s.put_if_absent("k", {"v": 1})


def test_json_store_put_if_absent_loads_durable_winner_on_conflict() -> None:
    from services.model_store import JsonStore

    p = _ConflictPersisted()
    s = JsonStore("js", persisted=p)
    with pytest.raises(RuntimeError, match="conflicting durable record"):
        s.put_if_absent("k", {"owner": "first"})

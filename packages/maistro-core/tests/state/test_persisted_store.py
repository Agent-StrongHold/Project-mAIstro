"""PersistedStore — dict-like persistence over SQLite via State.

These tests define the contract for a key-value store that serializes
Pydantic models to JSON and persists them through the State module's
singleton writer.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field


class SampleModel(BaseModel):
    id: str
    name: str
    value: int = 0
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class NestedModel(BaseModel):
    id: str
    title: str
    items: list[SampleModel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@pytest.fixture()
def state_with_store(tmp_path: Path):
    from maistro.state import PersistedStore, State

    db_path = tmp_path / "state.db"
    state = State(db_path=str(db_path))
    store = PersistedStore(state)
    store.initialize()
    yield state, store
    state.close()


class TestPutAndGet:
    def test_put_then_get_returns_model(self, state_with_store) -> None:
        state, store = state_with_store
        model = SampleModel(id="k1", name="test", value=42)
        store.put("items", "k1", model)
        state.flush()

        result = store.get("items", "k1", SampleModel)
        assert result is not None
        assert result.id == "k1"
        assert result.name == "test"
        assert result.value == 42

    def test_get_missing_key_returns_none(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.get("items", "nonexistent", SampleModel) is None

    def test_get_from_empty_store_returns_none(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.get("anything", "anykey", SampleModel) is None


class TestListAll:
    def test_list_all_returns_all_items(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "a", SampleModel(id="a", name="alpha"))
        store.put("items", "b", SampleModel(id="b", name="beta"))
        store.put("items", "c", SampleModel(id="c", name="gamma"))
        state.flush()

        results = store.list_all("items", SampleModel)
        assert len(results) == 3
        by_id = {r.id: r for r in results}
        assert by_id["a"].name == "alpha"
        assert by_id["b"].name == "beta"
        assert by_id["c"].name == "gamma"

    def test_list_all_empty_store(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.list_all("items", SampleModel) == []

    def test_list_all_respects_store_name(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("store_a", "k1", SampleModel(id="k1", name="a"))
        store.put("store_b", "k1", SampleModel(id="k1", name="b"))
        state.flush()

        a_items = store.list_all("store_a", SampleModel)
        b_items = store.list_all("store_b", SampleModel)
        assert len(a_items) == 1
        assert len(b_items) == 1
        assert a_items[0].name == "a"
        assert b_items[0].name == "b"


class TestDelete:
    def test_delete_removes_item(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="test"))
        state.flush()

        store.delete("items", "k1")
        state.flush()

        assert store.get("items", "k1", SampleModel) is None

    def test_delete_missing_key_is_noop(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "present", SampleModel(id="present", name="kept"))
        state.flush()
        store.delete("items", "nonexistent")
        state.flush()

        assert store.get("items", "present", SampleModel) == SampleModel(id="present", name="kept")


class TestContains:
    def test_contains_returns_true_for_existing(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="test"))
        state.flush()

        assert store.contains("items", "k1") is True

    def test_contains_returns_false_for_missing(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.contains("items", "missing") is False


class TestOverwrite:
    def test_put_same_key_overwrites(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="first", value=1))
        state.flush()

        store.put("items", "k1", SampleModel(id="k1", name="second", value=2))
        state.flush()

        result = store.get("items", "k1", SampleModel)
        assert result is not None
        assert result.name == "second"
        assert result.value == 2

    def test_list_all_count_after_overwrite(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="first"))
        store.put("items", "k1", SampleModel(id="k1", name="second"))
        state.flush()

        assert len(store.list_all("items", SampleModel)) == 1


class TestComplexModel:
    def test_nested_model_roundtrip(self, state_with_store) -> None:
        state, store = state_with_store
        now = datetime.now(UTC)
        model = NestedModel(
            id="n1",
            title="complex",
            items=[
                SampleModel(id="s1", name="sub1", tags=["a", "b"]),
                SampleModel(id="s2", name="sub2", meta={"x": 1}),
            ],
            created_at=now,
        )
        store.put("nested", "n1", model)
        state.flush()

        result = store.get("nested", "n1", NestedModel)
        assert result is not None
        assert result.title == "complex"
        assert len(result.items) == 2
        assert result.items[0].tags == ["a", "b"]
        assert result.items[1].meta == {"x": 1}


class TestPersistenceAcrossRestart:
    def test_data_survives_close_and_reopen(self, tmp_path: Path) -> None:
        from maistro.state import PersistedStore, State

        db_path = tmp_path / "state.db"

        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()
        store.put("items", "k1", SampleModel(id="k1", name="persisted", value=99))
        state.flush()
        state.close()

        state2 = State(db_path=str(db_path))
        store2 = PersistedStore(state2)
        store2.initialize()
        result = store2.get("items", "k1", SampleModel)
        state2.close()

        assert result is not None
        assert result.name == "persisted"
        assert result.value == 99


class TestConcurrentWrites:
    def test_many_threads_writing_same_store(self, state_with_store) -> None:
        state, store = state_with_store
        errors: list[Exception] = []

        def write_item(idx: int) -> None:
            try:
                store.put("items", f"k{idx}", SampleModel(id=f"k{idx}", name=f"item-{idx}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_item, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        state.flush()
        assert len(errors) == 0

        results = store.list_all("items", SampleModel)
        assert len(results) == 100


class TestMultipleStores:
    def test_different_stores_isolated(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("missions", "m1", SampleModel(id="m1", name="mission"))
        store.put("agents", "a1", SampleModel(id="a1", name="agent"))
        state.flush()

        missions = store.list_all("missions", SampleModel)
        agents = store.list_all("agents", SampleModel)
        assert len(missions) == 1
        assert len(agents) == 1
        assert missions[0].name == "mission"
        assert agents[0].name == "agent"

    def test_delete_from_one_store_doesnt_affect_other(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("missions", "k1", SampleModel(id="k1", name="mission"))
        store.put("agents", "k1", SampleModel(id="k1", name="agent"))
        state.flush()

        store.delete("missions", "k1")
        state.flush()

        assert store.get("missions", "k1", SampleModel) is None
        assert store.get("agents", "k1", SampleModel) is not None

"""Workspace Home layout service (#1048) — durability, revisions, authority split.

The contract under test is the one the issue makes non-negotiable:

- the layout is keyed by the canonical Workspace, is durable, and a write
  that did not land is not a success (same bar as the dashboard's #340);
- saves are revision-checked, so two editors cannot silently overwrite;
- the Agent's compose path can write only unpinned space — a user who pins
  any region, up to 100% of Home, has removed it from the Agent's reach;
- a region is a presentation instance holding a *reference*; saving never
  mints, copies or forks the referenced resource identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import stores
from services import home_layouts
from services.home_layouts import (
    HomeLayout,
    HomeRegion,
    LayoutConflictError,
    PinnedRegionWriteError,
)


@pytest.fixture(autouse=True)
def _clean_store():
    store = home_layouts._store()
    for key in list(store.keys()):
        store.pop(key, None)
    yield
    for key in list(store.keys()):
        store.pop(key, None)


def _region(id: str, kind: str = "goals", **kw: Any) -> HomeRegion:
    return HomeRegion(id=id, kind=kind, **kw)  # type: ignore[arg-type]


def _pinned_record(workspace: str = "ws-a") -> HomeLayout:
    """Two pinned regions plus the one unpinned region the user left the
    Agent — i.e. pin 'some', not 100%."""
    return HomeLayout(
        regions=[
            _region("r-goals", "goals", pinned=True, position=0),
            _region("r-backlog", "backlog", pinned=True, position=1),
            _region("r-runs", "runs", pinned=False, position=2),
        ]
    )


# --- Workspace scoping -------------------------------------------------------


def test_layouts_are_keyed_per_workspace_not_per_principal() -> None:
    """Two Workspaces never share a Home layout: the key is the Workspace id."""
    home_layouts.save_layout("ws-a", HomeLayout(regions=[_region("only-a")]))
    home_layouts.save_layout("ws-b", HomeLayout(regions=[_region("only-b")]))

    assert [r.id for r in home_layouts.load("ws-a").layout.regions] == ["only-a"]
    assert [r.id for r in home_layouts.load("ws-b").layout.regions] == ["only-b"]


def test_effective_defaults_to_unpinned_and_is_not_persisted_by_a_read() -> None:
    """A Workspace that never saved is offered the default (nothing pinned) —
    offered, not written: a GET must not fabricate durable state."""
    record = home_layouts.effective("ws-default")
    assert record.revision == 0
    assert record.layout.regions
    assert all(r.pinned is False for r in record.layout.regions)
    assert home_layouts.load("ws-default").revision == 0


def test_the_default_layout_references_kinds_not_resources() -> None:
    """The default composes section kinds; it does not invent resource ids."""
    for region in home_layouts.default_layout().regions:
        assert region.resource_type == "none"
        assert region.resource_id is None


# --- Durability --------------------------------------------------------------


# No `ac` marker: this is issue-level acceptance (#1048), not a SPEC-NNN
# criterion; the durability claim is the test itself.
def test_a_saved_layout_survives_the_store_being_closed_and_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The definition of done, run rather than asserted: a real `State` on a
    real SQLite file, closed and reopened. Against a fake, a restart proves
    nothing."""
    from services.model_store import JsonStore

    from maistro.state import PersistedStore, State

    db = tmp_path / "home-state.db"

    first = State(db_path=str(db))
    persisted = PersistedStore(first)
    persisted.initialize()
    before = JsonStore("home_layouts", persisted)
    before.initialize()
    monkeypatch.setattr(home_layouts, "_store", lambda: before)

    saved = home_layouts.save_layout(
        "ws-durable", HomeLayout(regions=[_region("keep-me", "backlog", pinned=True)])
    )
    assert saved.revision == 1
    first.flush()
    first.close()

    second = State(db_path=str(db))
    reopened = PersistedStore(second)
    reopened.initialize()
    after = JsonStore("home_layouts", reopened)
    after.initialize()
    monkeypatch.setattr(home_layouts, "_store", lambda: after)
    try:
        record = home_layouts.load("ws-durable")
    finally:
        second.close()

    assert record.revision == 1
    regions = {r.id: r for r in record.layout.regions}
    assert regions["keep-me"].pinned is True
    assert regions["keep-me"].kind == "backlog"


def test_the_home_stores_are_service_owned_but_registered_for_persistence() -> None:
    """Durable Home state lives beside the only code that writes it, but it
    must still be reachable by the central persistence wiring: a `JsonStore`
    that `configure_persistence` never reaches is a dict, and a store the
    retirement ledger cannot see being written is exactly the leak #1046
    freezes out (#1048, #334 precedent).
    """
    from services import home_layouts, home_projections

    assert home_layouts.layout_store in stores._all_json_stores
    assert home_projections.dismissal_store in stores._all_json_stores
    # And the names are gone from `stores` itself, so the ledger's
    # every-store scan has nothing unledgered to demand a row for.
    assert not hasattr(stores, "home_layouts")
    assert not hasattr(stores, "home_adaptive_dismissals")


def test_a_second_registration_is_a_no_op_and_late_registration_wires_persistence() -> None:
    """`register_json_store` is the one seam: idempotent, and after
    `configure_persistence` it wires and initializes immediately — a store
    registered late must not silently miss the configured backend."""
    from services.model_store import JsonStore

    late = stores.register_json_store(JsonStore("home_layouts_test_late"))
    try:
        assert late in stores._all_json_stores
        assert stores.register_json_store(late) is late
        assert stores._all_json_stores.count(late) == 1

        backend = _RefusingStore()
        stores.configure_persistence(backend)
        assert late._persisted is backend
    finally:
        stores._all_json_stores.remove(late)
        stores.configure_persistence(None)


class _RefusingStore:
    """Every write raises. A read-only filesystem, a full disk, a lost pool."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __setitem__(self, key: str, value: Any) -> None:
        raise OSError("no writable backing store")


def test_a_write_that_did_not_land_raises_not_answers_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(home_layouts, "_store", lambda: _RefusingStore())
    from services.home_layouts import LayoutPersistenceError

    with pytest.raises(LayoutPersistenceError):
        home_layouts.save_layout("ws-full", HomeLayout(regions=[_region("r1")]))


# --- Revisions ---------------------------------------------------------------


def test_a_stale_revision_is_refused_and_names_the_stored_one() -> None:
    home_layouts.save_layout("ws-rev", HomeLayout(regions=[_region("r1")]))
    home_layouts.save_layout("ws-rev", HomeLayout(regions=[_region("r1"), _region("r2")]))

    with pytest.raises(LayoutConflictError) as excinfo:
        home_layouts.save_layout(
            "ws-rev",
            HomeLayout(regions=[_region("r3")]),
            expected_revision=1,
        )
    assert excinfo.value.stored.revision == 2


def test_absent_revision_is_last_write_wins_like_the_dashboard() -> None:
    home_layouts.save_layout("ws-lww", HomeLayout(regions=[_region("r1")]))
    record = home_layouts.save_layout("ws-lww", HomeLayout(regions=[_region("r2")]))
    assert record.revision == 2
    assert [r.id for r in record.layout.regions] == ["r2"]


# --- Region shape ------------------------------------------------------------


def test_duplicate_region_ids_are_refused() -> None:
    with pytest.raises(Exception, match="duplicate region id"):
        HomeLayout(regions=[_region("dup"), _region("dup")])


def test_two_regions_may_reference_the_same_resource() -> None:
    """Two presentation instances over one canonical item: a projection, not
    a fork. Saving it must not mint a second resource identity."""
    layout = HomeLayout(
        regions=[
            _region("spotlight", "backlog", resource_type="backlog_item", resource_id="item-9"),
            _region("queue", "backlog", resource_type="backlog_item", resource_id="item-9"),
        ]
    )
    record = home_layouts.save_layout("ws-shared", layout)
    refs = {(r.resource_type, r.resource_id) for r in record.layout.regions}
    assert refs == {("backlog_item", "item-9")}


def test_an_unknown_resource_type_is_refused() -> None:
    with pytest.raises(Exception, match="canonical reference type"):
        HomeLayout(regions=[_region("bad", resource_type="bookmark", resource_id="b1")])


# --- The authority split ------------------------------------------------------


def test_the_agent_may_fill_unpinned_space_and_pinned_space_survives() -> None:
    home_layouts.save_layout("ws-compose", _pinned_record())

    record = home_layouts.compose_adaptive(
        "ws-compose",
        [
            _region(
                "agent-lens",
                "backlog",
                position=9,
                reason="blocked item in this Workspace's backlog",
            )
        ],
    )

    regions = {r.id: r for r in record.layout.regions}
    # Pinned regions survived byte-for-byte.
    assert regions["r-goals"].pinned is True
    assert regions["r-goals"].position == 0
    assert regions["r-backlog"].pinned is True
    # The Agent's region is unpinned, present, and carries its reason.
    assert regions["agent-lens"].pinned is False
    assert regions["agent-lens"].reason == "blocked item in this Workspace's backlog"
    # The unpinned r-runs was the Agent's to drop: composition includes removal.


@pytest.mark.parametrize(
    "payload",
    [
        # Pinning a new region.
        [_region("sneaky", "goals", pinned=True)],
        # Re-using a pinned region's id to rewrite it (flip, move, re-reason).
        [_region("r-goals", "goals", pinned=False, position=5)],
    ],
)
def test_a_compose_payload_touching_pinned_space_is_refused(payload: list[HomeRegion]) -> None:
    home_layouts.save_layout("ws-guard", _pinned_record())
    before = home_layouts.load("ws-guard")

    with pytest.raises(PinnedRegionWriteError):
        home_layouts.compose_adaptive("ws-guard", payload)

    after = home_layouts.load("ws-guard")
    assert after.revision == before.revision
    assert after.layout == before.layout


def test_pinning_100_percent_leaves_the_agent_nothing_to_compose() -> None:
    home_layouts.save_layout(
        "ws-full-pin",
        HomeLayout(regions=[_region("r-goals", "goals", pinned=True, position=0)]),
    )

    with pytest.raises(PinnedRegionWriteError):
        home_layouts.compose_adaptive(
            "ws-full-pin", [_region("agent-anything", "runs", position=9)]
        )
    # The refuse-anything is per-region: an empty compose is a legal no-op
    # over pinned space, and changes nothing.
    record = home_layouts.compose_adaptive("ws-full-pin", [])
    assert [r.id for r in record.layout.regions] == ["r-goals"]
    assert record.layout.regions[0].pinned is True


def test_pinning_zero_percent_gives_the_agent_the_whole_surface() -> None:
    home_layouts.save_layout(
        "ws-no-pin",
        HomeLayout(regions=[_region("r-goals", "goals", pinned=False, position=0)]),
    )
    record = home_layouts.compose_adaptive(
        "ws-no-pin", [_region("agent-takeover", "runs", position=9)]
    )
    ids = {r.id for r in record.layout.regions}
    # The unpinned region was the Agent's to drop: composition includes removal.
    assert ids == {"agent-takeover"}


def test_set_region_pinned_is_presentation_only_and_reaches_an_unsaved_default() -> None:
    """Pinning into a Workspace that never saved persists the default with the
    one pin applied — not an empty layout that would silently drop the rest."""
    record = home_layouts.set_region_pinned("ws-first-pin", "default-goals", pinned=True)
    assert record.revision == 1
    regions = {r.id: r for r in record.layout.regions}
    assert regions["default-goals"].pinned is True
    assert len(record.layout.regions) == len(home_layouts.default_layout().regions)

    stored = home_layouts.load("ws-first-pin")
    assert stored.revision == 1


def test_unpinning_hands_the_region_back_to_the_agent() -> None:
    home_layouts.save_layout("ws-unpin", _pinned_record())
    record = home_layouts.set_region_pinned("ws-unpin", "r-goals", pinned=False)
    regions = {r.id: r for r in record.layout.regions}
    assert regions["r-goals"].pinned is False
    # With r-goals unpinned there is unpinned space again, so the Agent may
    # now rewrite it (and own the composition of the rest).
    home_layouts.compose_adaptive("ws-unpin", [_region("r-goals", "goals", position=4)])


def test_an_explicitly_emptied_home_leaves_the_agent_nothing_too() -> None:
    """A user who saved an empty layout said 'Home shows nothing': a non-empty
    compose would grow their fixed composition, so it is refused."""
    home_layouts.save_layout("ws-emptied", HomeLayout(regions=[]))
    with pytest.raises(PinnedRegionWriteError, match="no unpinned space"):
        home_layouts.compose_adaptive("ws-emptied", [_region("agent-lens", "runs")])


def test_unknown_region_ids_cannot_be_pinned() -> None:
    home_layouts.save_layout("ws-missing", HomeLayout(regions=[_region("r1")]))
    from services.home_layouts import LayoutError

    with pytest.raises(LayoutError, match="no region"):
        home_layouts.set_region_pinned("ws-missing", "ghost", pinned=True)


# --- Dismissals are a preference, scoped per Workspace -----------------------


def test_dismissals_count_and_are_workspace_scoped() -> None:
    from services import home_projections

    first = home_projections.record_dismissal("ws-d1", "goal", "g1", actor="user")
    assert first["count"] == 1
    second = home_projections.record_dismissal("ws-d1", "goal", "g1", actor="user")
    assert second["count"] == 2

    # Another Workspace's Home is untouched by this dismissal.
    assert home_projections.dismissal_counts("ws-d2") == {}
    assert home_projections.dismissal_counts("ws-d1") == {"goal:g1": 2}


def test_dismissal_refuses_an_empty_identity() -> None:
    from services import home_projections

    with pytest.raises(ValueError):
        home_projections.record_dismissal("ws-x", "goal", "", actor="user")

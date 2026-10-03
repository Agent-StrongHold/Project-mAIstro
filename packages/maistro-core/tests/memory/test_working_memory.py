"""Behavior of the working-memory projection, recall, rendering, simplification
and measurement (#301, M4-H).

The invariants under test are the ones the epic sells:

* **losslessness** — simplification folds and hard resets append markers;
  every entry stays reachable through the store after any number of resets;
* **reference-addressability** — an identical payload is stored once and
  pointed at twice; prompt text carries the pointer, not the payload;
* **derivation** — the working set is recomputable from the log alone, so a
  rebuild after a hard reset reproduces it exactly (tested over *both* store
  legs, the regression seam where the SQLite twin silently diverged);
* **measured, not vibes** — redundant-hypothesis collapse and fresh-vs-lineage
  are deterministic functions of the graph, and an unmeasured ratio is
  ``None``, never a polite zero (ADR-083026-a91e).
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.working import (
    InMemoryWorkspaceLogStore,
    ObservationKind,
    WorkingMemoryManager,
    WorkingMemoryRecall,
    WorkingResult,
    WorkspaceLogStore,
    WorkspaceObservation,
    make_result_id,
    observation,
    render_working_context,
)
from maistro.memory.working.measurement import (
    measure_fresh_vs_lineage,
    measure_redundant_hypotheses,
)
from maistro.memory.working.projection import WorkspaceWorkingMemory
from maistro.memory.working.render import render_guide, render_working
from maistro.memory.working.simplify import (
    append_cycle_summary,
    hard_reset,
    simplify,
)
from maistro.memory.working.wiring import (
    wire_in_memory_working_memory,
    wire_working_memory,
)

WS = "ws-behavior"


# --------------------------------------------------------------------------
# fixtures


@pytest.fixture(params=["memory", "sqlite"])
async def env(request: pytest.FixtureRequest, tmp_path: Any) -> Any:
    """A manager over each store leg, plus the store for direct assertions."""
    if request.param == "memory":
        store: WorkspaceLogStore = InMemoryWorkspaceLogStore()
    else:
        import aiosqlite

        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        conn = await aiosqlite.connect(tmp_path / "wm.db")
        store = SqliteWorkspaceLogStore(conn)
        await store.ensure_schema()
    manager = WorkingMemoryManager(store)
    yield store, manager
    if request.param == "sqlite":
        await conn.close()


async def _seed_log(store: WorkspaceLogStore, ws: str = WS) -> dict[str, Any]:
    """A small log with every entry kind: observation, tool result, hypotheses."""
    payload = "full deployment log output\n" * 20
    result = WorkingResult(
        workspace_id=ws,
        result_id=make_result_id(ws, "deploy-tool", payload),
        source="deploy-tool",
        content=payload,
    )
    await store.put_result(result)
    seeded: dict[str, Any] = {}
    seeded["result"] = result
    seeded["deploy"] = await store.append(
        observation(
            workspace_id=ws,
            cycle=1,
            text="read the deploy pipeline output",
            kind=ObservationKind.TOOL_RESULT,
            result_ref=result.result_id,
            digest=result.digest,
        )
    )
    # Two identical hypotheses: one fact observed twice.
    for _ in range(2):
        await store.append(
            observation(
                workspace_id=ws,
                cycle=2,
                text="hypothesis: the healthcheck is flaky",
                kind=ObservationKind.HYPOTHESIS,
            )
        )
    seeded["current"] = await store.append(
        observation(workspace_id=ws, cycle=3, text="writing the rollout tests now")
    )
    return seeded


# --------------------------------------------------------------------------
# working-set derivation


class TestWorkingSetDerivation:
    async def test_fresh_log_working_set_is_everything(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        projection = await manager.projection(WS)
        assert [e.seq for e in projection.active_entries()] == [1, 2, 3, 4]
        stats = projection.stats()
        assert (stats.entries, stats.active, stats.folded) == (4, 4, 0)

    async def test_summary_marker_folds_named_entries(self, env: Any) -> None:
        store, manager = env
        seeded = await _seed_log(store)
        summary = await append_cycle_summary(
            store,
            await manager.projection(WS),
            cycle=2,
        )
        assert summary is not None
        active = manager.hot(WS).active_entries()  # type: ignore[union-attr]
        active_ids = [e.entry_id for e in active]
        # The cycle-2 hypotheses folded; cycle 1 and cycle 3 entries stay,
        # and the summary line itself is active — it replaced what it folded.
        assert seeded["deploy"].entry_id in active_ids
        assert seeded["current"].entry_id in active_ids
        folded_kinds = [
            e.kind
            for e in active
            if e.entry_id not in (seeded["deploy"].entry_id, seeded["current"].entry_id)
        ]
        assert folded_kinds == [ObservationKind.SUMMARY]
        # The folded entries are still in the log: lossless.
        assert len(await store.list_entries(WS)) == 5
        assert await store.get_entry(WS, seeded["deploy"].entry_id) is not None

    async def test_hard_reset_keeps_only_the_survival_set(self, env: Any) -> None:
        store, manager = env
        seeded = await _seed_log(store)
        projection = await manager.projection(WS)
        marker = await hard_reset(store, projection, survival_ids=[seeded["deploy"].entry_id])
        assert marker.kind is ObservationKind.RESET
        active = projection.active_entries()
        assert [e.entry_id for e in active] == [seeded["deploy"].entry_id]
        # The log holds everything: the reset appended, it did not delete.
        assert len(await store.list_entries(WS)) == 5

    async def test_survive_reset_flag_survives_from_any_position(self, env: Any) -> None:
        store, manager = env
        seeded = await _seed_log(store)
        projection = await manager.projection(WS)
        await manager.observe(WS, cycle=3, text="pinned: production is us-east", survive_reset=True)
        await hard_reset(store, projection)  # names nothing: only the flag survives
        active_texts = [e.text for e in projection.active_entries()]
        assert active_texts == ["pinned: production is us-east"]
        assert seeded["current"].entry_id not in [e.entry_id for e in projection.active_entries()]

    async def test_hard_reset_rejects_unknown_survival_ids(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        projection = await manager.projection(WS)
        with pytest.raises(KeyError, match="survival id"):
            await hard_reset(store, projection, survival_ids=["obs-not-in-the-log"])

    async def test_simplify_folds_stale_cycles_but_never_pinned(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        projection = await manager.projection(WS)
        await manager.observe(WS, cycle=4, text="newest cycle work")
        await manager.observe(WS, cycle=4, text="pinned: rollout window", survive_reset=True)
        summary = await simplify(store, projection, keep_cycles=1)
        assert summary is not None
        texts = [e.text for e in projection.active_entries()]
        # Newest cycle verbatim, stale cycles folded, the pinned entry kept.
        assert "newest cycle work" in texts
        assert "pinned: rollout window" in texts
        assert "writing the rollout tests now" not in texts
        assert "read the deploy pipeline output" not in texts
        assert "hypothesis: the healthcheck is flaky" not in texts
        # Lossless: 4 seed entries + 2 cycle-4 entries + 1 summary marker.
        assert len(await store.list_entries(WS)) == 7

    async def test_append_cycle_summary_skips_empty_cycles(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        projection = await manager.projection(WS)
        assert await append_cycle_summary(store, projection, cycle=99) is None


class TestRebuildEquivalence:
    async def test_rebuild_reproduces_the_working_set_after_reset(self, env: Any) -> None:
        """The projection is disposable: hydrate(log) == in-memory state."""
        store, manager = env
        seeded = await _seed_log(store)
        projection = await manager.projection(WS)
        pinned = await manager.observe(WS, cycle=3, text="pinned: prod region", survive_reset=True)
        # A pre-reset survivor (before the marker's pagination point) and a
        # named survivor; the pinned entry is flagged, not named.
        await hard_reset(
            store,
            projection,
            survival_ids=[seeded["deploy"].entry_id, seeded["current"].entry_id],
        )
        before = [(e.seq, e.entry_id) for e in projection.active_entries()]
        # A rebuild is dispose + hydrate: the projection is disposable exactly
        # because the log is authoritative.
        await manager.dispose(WS)
        rebuilt = await manager.projection(WS)
        after = [(e.seq, e.entry_id) for e in rebuilt.active_entries()]
        assert after == before
        # Full results referenced by surviving entries hydrate too.
        deploy_hit = rebuilt.entry(seeded["deploy"].entry_id)
        assert deploy_hit is not None and deploy_hit.result_ref is not None
        assert rebuilt.result(deploy_hit.result_ref) is not None
        assert rebuilt.entry(pinned.entry_id) is not None

    async def test_second_reset_uses_its_own_survival_set(self, env: Any) -> None:
        store, manager = env
        seeded = await _seed_log(store)
        projection = await manager.projection(WS)
        await hard_reset(store, projection, survival_ids=[seeded["deploy"].entry_id])
        fresh = await manager.observe(WS, cycle=4, text="post-reset work")
        await hard_reset(store, projection, survival_ids=[fresh.entry_id])
        assert [e.entry_id for e in projection.active_entries()] == [fresh.entry_id]
        # And a rebuild agrees: the newest marker wins.
        await manager.dispose(WS)
        rebuilt = await manager.projection(WS)
        assert [e.entry_id for e in rebuilt.active_entries()] == [fresh.entry_id]


class TestManagerLifecycle:
    async def test_observe_records_tool_results_and_keeps_hot_projection_coherent(
        self, env: Any
    ) -> None:
        store, manager = env
        projection = await manager.projection(WS)
        observed = await manager.observe(WS, cycle=1, text="hot observation")
        assert projection.entry(observed.entry_id) is not None
        entry = await manager.observe(
            WS,
            cycle=1,
            text="ran the tool",
            source="tool",
            content="payload",
        )
        assert entry.kind is ObservationKind.TOOL_RESULT
        assert entry.result_ref is not None
        assert projection.result(entry.result_ref) is not None
        stored = await store.get_result(WS, entry.result_ref)
        assert stored is not None and stored.content == "payload"

    async def test_identical_payloads_collapse_to_one_stored_result(self, env: Any) -> None:
        store, manager = env
        await manager.projection(WS)
        entry1 = await manager.observe(
            WS, cycle=1, text="first call", source="tool", content="same bytes"
        )
        entry2 = await manager.observe(
            WS, cycle=2, text="second call", source="tool", content="same bytes"
        )
        assert entry1.result_ref is not None
        # Same payload, same Workspace: one content address, one stored row.
        assert entry2.result_ref == entry1.result_ref
        stored = await store.get_result(WS, entry1.result_ref)
        assert stored is not None and stored.content == "same bytes"
        # And the stored-once record survives rehydration.
        projection = await manager.projection(WS)
        assert projection.result(entry1.result_ref) is not None

    async def test_eviction_by_capacity_and_ttl(self, env: Any) -> None:
        _, manager = env
        manager.max_projections = 2
        await manager.projection("ws-a")
        await manager.projection("ws-b")
        await manager.projection("ws-c")
        # Capacity: three live graphs with a bound of two evicts the oldest.
        assert manager.hot("ws-a") is None
        assert manager.hot("ws-b") is not None
        assert manager.hot("ws-c") is not None
        # TTL: a zero TTL makes every live graph stale on the next pass.
        manager.ttl_seconds = 0.0
        evicted = manager.evict()
        assert evicted == 2
        assert manager.hot("ws-b") is None
        assert manager.hot("ws-c") is None

    async def test_dispose_keeps_the_log(self, env: Any) -> None:
        store, manager = env
        await manager.projection(WS)
        await manager.observe(WS, cycle=1, text="durable")
        await manager.dispose(WS)
        assert manager.hot(WS) is None
        assert len(await store.list_entries(WS)) == 1


# --------------------------------------------------------------------------
# recall


class TestRecall:
    async def test_empty_query_returns_working_set_newest_first(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        recall = WorkingMemoryRecall(manager)
        hits = await recall.recall(WS)
        # Newest first; the two digest-equal hypotheses collapse to their
        # newest observation (seq 3), so seq 2 is not a separate hit.
        assert [h.entry.seq for h in hits] == [4, 3, 1]

    async def test_query_matches_terms_and_tags(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        await manager.observe(
            WS,
            cycle=4,
            text="untagged note",
            meta={"tags": ["deploy", "pipeline"]},
        )
        recall = WorkingMemoryRecall(manager)
        hits = await recall.recall(WS, "deploy pipeline", kinds=(ObservationKind.OBSERVATION,))
        assert hits
        assert hits[0].entry.text == "untagged note"
        assert "deploy" in hits[0].matched

    async def test_redundant_hypotheses_collapse_to_one_hit(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        recall = WorkingMemoryRecall(manager)
        hits = await recall.recall(WS, "hypothesis healthcheck flaky")
        hypothesis_hits = [h for h in hits if h.entry.kind is ObservationKind.HYPOTHESIS]
        assert len(hypothesis_hits) == 1
        # ...unless the caller asks for the redundancy explicitly.
        keep = await recall.recall(WS, "hypothesis healthcheck flaky", keep_duplicates=True)
        assert len([h for h in keep if h.entry.kind is ObservationKind.HYPOTHESIS]) == 2

    async def test_lineage_expansion_returns_the_result_behind_a_hit(self, env: Any) -> None:
        _, manager = env
        await manager.projection(WS)
        # Two entries address the SAME result but share no vocabulary, so
        # only one is reachable fresh; the other must arrive by traversal.
        first = await manager.observe(
            WS, cycle=1, text="alpha analysis unique", source="tool", content="PAYLOAD"
        )
        second = await manager.observe(
            WS, cycle=2, text="totally other words", source="tool", content="PAYLOAD"
        )
        recall = WorkingMemoryRecall(manager)
        # Default: digest-equal entries collapse (same payload re-observed),
        # so the second observation does not get its own slot.
        default_hits = await recall.recall(WS, "alpha analysis")
        assert second.entry_id not in {h.entry.entry_id for h in default_hits}
        # With duplicates kept, the second observation arrives by traversal:
        # it shares first's result_ref and digest, so the graph edge finds it.
        hits = await recall.recall(WS, "alpha analysis", keep_duplicates=True)
        fresh_ids = {h.entry.entry_id for h in hits if h.matched != ("lineage",)}
        lineage_ids = {h.entry.entry_id for h in hits if h.matched == ("lineage",)}
        assert first.entry_id in fresh_ids
        assert second.entry_id in lineage_ids

    async def test_with_results_resolves_the_full_payload(self, env: Any) -> None:
        store, manager = env
        seeded = await _seed_log(store)
        recall = WorkingMemoryRecall(manager)
        hits = await recall.recall(WS, "", limit=10, with_results=True)
        resolved = {h.entry.entry_id: h.result for h in hits}
        assert resolved[seeded["deploy"].entry_id] is not None
        assert seeded["result"].content.startswith("full deployment log output")
        # The payload never entered the prompt text: the entry line is compact.
        assert len(seeded["deploy"].text) < len(seeded["result"].content)

    async def test_recall_is_workspace_scoped(self, env: Any) -> None:
        _, manager = env
        await manager.projection("ws-one")
        await manager.observe("ws-one", cycle=1, text="only in workspace one")
        await manager.projection("ws-two")
        await manager.observe("ws-two", cycle=1, text="only in workspace two")
        recall = WorkingMemoryRecall(manager)
        hits_one = await recall.recall("ws-one", "workspace one")
        hits_two = await recall.recall("ws-two", "workspace two")
        assert [h.entry.text for h in hits_one] == ["only in workspace one"]
        assert [h.entry.text for h in hits_two] == ["only in workspace two"]


# --------------------------------------------------------------------------
# GUIDE + WORKING rendering


class TestRender:
    def _projection(self) -> WorkspaceWorkingMemory:
        def entry(seq: int, cycle: int, text: str, **kw: Any) -> WorkspaceObservation:
            return WorkspaceObservation(
                workspace_id=WS,
                entry_id=f"obs-render-{seq}",
                kind=kw.pop("kind", ObservationKind.OBSERVATION),
                cycle=cycle,
                text=text,
                seq=seq,
                **kw,
            )

        projection = WorkspaceWorkingMemory(WS)
        projection.hydrate(
            [
                entry(1, 1, "old folded work"),
                entry(2, 2, "pinned fact", survive_reset=True),
                entry(
                    3,
                    3,
                    "referenced result line",
                    result_ref="res-abc",
                    digest="d" * 64,
                ),
                entry(4, 4, "newest observation"),
            ],
            results=[
                WorkingResult(
                    workspace_id=WS,
                    result_id="res-abc",
                    source="tool",
                    content="x" * 400,
                )
            ],
        )
        return projection

    async def test_both_blocks_are_deterministic(self, env: Any) -> None:
        projection = self._projection()
        first = render_working_context(projection)
        second = render_working_context(projection)
        assert first.working == second.working
        assert first.guide == second.guide
        assert first.working and first.guide

    async def test_working_is_pinned_first_and_newest_first_after(self, env: Any) -> None:
        rendered = render_working(self._projection().active_entries())
        lines = rendered.splitlines()
        assert lines[0].startswith("# WORKING MEMORY")
        pinned_index = next(i for i, line in enumerate(lines) if "pinned fact" in line)
        newest_index = next(i for i, line in enumerate(lines) if "newest observation" in line)
        old_index = next(i for i, line in enumerate(lines) if "old folded work" in line)
        assert pinned_index < newest_index < old_index
        assert "*pinned*" in lines[pinned_index]

    async def test_budget_drops_whole_entries_but_never_the_pinned(self, env: Any) -> None:
        entries = self._projection().active_entries()
        # A budget that cannot even hold the unpinned lines still holds pins.
        rendered = render_working(entries, budget_tokens=24)
        assert "pinned fact" in rendered
        assert "newest observation" not in rendered
        # No truncation: every rendered line is a whole entry.
        for line in rendered.splitlines():
            if line.startswith("- "):
                assert any(line.endswith(e.text) or f"] {e.text}" in line for e in entries)

    async def test_guide_lists_addressable_results_with_the_recall_hint(self, env: Any) -> None:
        projection = self._projection()
        guide = render_guide(projection.all_entries(), {"res-abc": 400})
        assert "res-abc" in guide
        assert "recall" in guide
        assert "400B" in guide

    async def test_render_working_context_counts(self, env: Any) -> None:
        rendered = render_working_context(self._projection())
        assert rendered.pinned_rendered == 1
        assert rendered.entries_rendered == 4
        assert rendered.results_listed >= 1
        assert rendered.tokens_spent > 0


# --------------------------------------------------------------------------
# measurement


class TestMeasurement:
    async def test_redundant_hypothesis_collapse(self, env: Any) -> None:
        store, manager = env
        await _seed_log(store)
        projection = await manager.projection(WS)
        measurement = measure_redundant_hypotheses(projection)
        assert measurement.hypotheses_total == 2
        assert measurement.unique == 1
        assert measurement.redundant == 1
        assert measurement.collapse_ratio == 0.5

    async def test_no_hypotheses_measures_absent_not_zero(self, env: Any) -> None:
        _, manager = env
        projection = await manager.projection(WS)
        measurement = measure_redundant_hypotheses(projection)
        assert measurement.hypotheses_total == 0
        assert measurement.collapse_ratio is None

    async def test_fresh_vs_lineage_over_probe_queries(self, env: Any) -> None:
        _, manager = env
        await manager.projection(WS)
        # Two entries address one result; only one's text matches the probe.
        await manager.observe(
            WS, cycle=1, text="quarterly report analysis", source="tool", content="P"
        )
        await manager.observe(
            WS, cycle=2, text="distinct wording entirely", source="tool", content="P"
        )
        projection = await manager.projection(WS)
        measurement = measure_fresh_vs_lineage(projection, ["quarterly report"])
        assert measurement.queries == 1
        assert measurement.fresh_hits == 1
        # Reach with traversal on: the fresh hit plus its sibling via the
        # shared result_ref.
        assert measurement.lineage_hits == 2
        assert measurement.overlap_ratio == 1.0
        assert measurement.lineage_gain == 1.0

    async def test_fresh_only_graph_has_no_lineage_gain(self, env: Any) -> None:
        _, manager = env
        await manager.projection(WS)
        await manager.observe(WS, cycle=1, text="isolated observation about kumquats")
        projection = await manager.projection(WS)
        measurement = measure_fresh_vs_lineage(projection, ["kumquats"])
        assert measurement.fresh_hits == 1
        assert measurement.lineage_hits == 1
        assert measurement.overlap_ratio == 0.0
        assert measurement.lineage_gain == 0.0

    async def test_empty_graph_zero_hits_but_absent_ratios(self, env: Any) -> None:
        _, manager = env
        projection = await manager.projection(WS)
        measurement = measure_fresh_vs_lineage(projection, ["anything"])
        assert (measurement.fresh_hits, measurement.lineage_hits) == (0, 0)
        assert measurement.overlap_ratio is None
        assert measurement.lineage_gain is None


# --------------------------------------------------------------------------
# wiring


class TestWiring:
    async def test_sqlite_pool_wires_the_durable_twin(self, tmp_path: Any) -> None:
        import aiosqlite

        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        conn = await aiosqlite.connect(tmp_path / "wm.db")
        try:
            manager = await wire_working_memory(conn)
            assert isinstance(manager.store, SqliteWorkspaceLogStore)
            await manager.observe("ws-wired", cycle=1, text="durable via wiring")
            assert len(await manager.store.list_entries("ws-wired")) == 1
        finally:
            await conn.close()

    async def test_no_pool_falls_back_loudly(self, caplog: Any) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            manager = wire_in_memory_working_memory()
        assert isinstance(manager.store, InMemoryWorkspaceLogStore)
        assert any("#301" in record.message for record in caplog.records)

    async def test_container_wires_working_memory(self, tmp_path: Any) -> None:
        """The Container seam: SQLite pool in, durable manager out; no pool,
        the loud in-memory fallback — same rule as campaigns."""
        import aiosqlite

        from maistro.container import Container, _wire_working_memory_backend
        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        conn = await aiosqlite.connect(tmp_path / "wm.db")
        try:
            wired = await _wire_working_memory_backend(conn)
            assert isinstance(wired.store, SqliteWorkspaceLogStore)
        finally:
            await conn.close()
        fallback = await _wire_working_memory_backend(None)
        assert isinstance(fallback.store, InMemoryWorkspaceLogStore)
        # The field exists on Container and defaults to None (direct-built).
        assert Container.__dataclass_fields__["working_memory"].default is None

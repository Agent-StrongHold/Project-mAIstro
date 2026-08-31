"""The canonical spine exposes the atomic consumer-claim seam (#544)."""

from maistro.runs.wiring import wire_execution_spine


async def test_wired_in_memory_spine_exposes_atomic_consumer_claim() -> None:
    (
        _scope,
        run_store,
        _admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="w1")

    assert callable(getattr(run_store, "claim_consumer_run", None))

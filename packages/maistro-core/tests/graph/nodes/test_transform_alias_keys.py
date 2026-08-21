"""Tests for transform.alias_keys (bridge node for schema-incompatible neighbors)."""

from __future__ import annotations

from maistro.graph.nodes import NodeContext, get_node


def _ctx() -> NodeContext:
    return NodeContext(run_id="r", dag_id="d", node_id="n")


async def test_alias_keys_renames_via_mapping() -> None:
    node = get_node("transform.alias_keys")()
    out = await node.run(
        {
            "mapping": {"items": "issues"},
            "issues": [{"key": "P-1"}, {"key": "P-2"}],
        },
        _ctx(),
    )
    assert out.success
    dumped = out.output.model_dump()
    assert dumped["items"] == [{"key": "P-1"}, {"key": "P-2"}]


async def test_alias_keys_passes_unmapped_keys_through_by_default() -> None:
    node = get_node("transform.alias_keys")()
    out = await node.run(
        {
            "mapping": {"items": "issues"},
            "issues": [{"k": 1}],
            "count": 1,
            "base_url": "https://x",
        },
        _ctx(),
    )
    assert out.success
    dumped = out.output.model_dump()
    assert dumped["items"] == [{"k": 1}]
    assert dumped["count"] == 1
    assert dumped["base_url"] == "https://x"
    # `issues` should NOT appear under its original name — it's been consumed
    # as the source of `items`.
    assert "issues" not in dumped


async def test_alias_keys_drop_unmapped_removes_passthrough() -> None:
    node = get_node("transform.alias_keys")()
    out = await node.run(
        {
            "mapping": {"items": "issues"},
            "drop_unmapped": True,
            "issues": [{"k": 1}],
            "count": 99,
            "extra": "should-be-dropped",
        },
        _ctx(),
    )
    assert out.success
    dumped = out.output.model_dump()
    assert dumped == {"items": [{"k": 1}]}


async def test_alias_keys_missing_source_key_skips_target() -> None:
    """When the upstream doesn't have the `old_key`, the new key is simply
    not set in the output (no KeyError)."""
    node = get_node("transform.alias_keys")()
    out = await node.run(
        {
            "mapping": {"items": "issues"},
            # no `issues` here — missing source
            "count": 0,
        },
        _ctx(),
    )
    assert out.success
    dumped = out.output.model_dump()
    assert "items" not in dumped
    assert dumped["count"] == 0


async def test_alias_keys_empty_mapping_is_identity() -> None:
    node = get_node("transform.alias_keys")()
    out = await node.run({"mapping": {}, "a": 1, "b": 2}, _ctx())
    assert out.success
    dumped = out.output.model_dump()
    assert dumped == {"a": 1, "b": 2}

"""ADR-043 tests — executor + tool agent integration.

Image generation is mocked via ``FakeImageGenClient``; no PIL or
network involved.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_canvas.canvas.asset_executor import AssetExecutor
from maistro_canvas.canvas.asset_store import InMemoryAssetStore
from maistro_canvas.canvas.asset_tool import AssetTool
from maistro_canvas.layers import (
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    LayerKind,
    RenderStyle,
    Socket,
    WorldStyle,
)
from maistro_canvas.protocols import ImageData

# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────


class FakeImageGenClient:
    """Captures calls and returns synthetic images. Sequential URL
    counter so consecutive calls are distinguishable."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._counter = 0

    async def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        width: int,
        height: int,
        count: int = 1,
        seed: int | None = None,
        negative_prompt: str = "",
        world_style: WorldStyle | None = None,
        render_style: RenderStyle | None = None,
        asset_sheet: AssetSheet | None = None,
    ) -> list[ImageData]:
        self._counter += 1
        self.calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "width": width,
                "height": height,
                "count": count,
                "world_style": world_style,
                "render_style": render_style,
                "asset_sheet_ref": asset_sheet.sheet_image if asset_sheet is not None else None,
            }
        )
        return [
            ImageData(
                width=width,
                height=height,
                url=f"/fake-image-{self._counter}.png",
            )
            for _ in range(count)
        ]


def _world_style() -> WorldStyle:
    return WorldStyle(
        era="modern",
        realism="watercolor",
        architectural_register="cottage",
        vehicle_register="1970s-pickup",
        palette_anchors=("sage", "cream"),
        fauna_realism="cute",
    )


@pytest.fixture
def store() -> InMemoryAssetStore:
    return InMemoryAssetStore()


@pytest.fixture
def gen() -> FakeImageGenClient:
    return FakeImageGenClient()


@pytest.fixture
def executor(store: InMemoryAssetStore, gen: FakeImageGenClient) -> AssetExecutor:
    return AssetExecutor(store, gen)


@pytest.fixture
def tool(executor: AssetExecutor) -> AssetTool:
    return AssetTool(executor)


# ─────────────────────────────────────────────────────────────────────
# Executor
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_and_get_definition(executor: AssetExecutor) -> None:
    defn = AssetDefinition(
        asset_id="farmhouse",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
        sockets=(Socket(name="porch", x=0.5, y=0.6),),
    )
    out = await executor.register_definition(defn)
    assert out is defn
    fetched = await executor.get_definition("farmhouse")
    assert fetched is not None
    assert fetched.asset_id == "farmhouse"


@pytest.mark.asyncio
async def test_generate_sheet_persists_and_calls_backend(
    executor: AssetExecutor, gen: FakeImageGenClient
) -> None:
    await executor.register_definition(
        AssetDefinition(asset_id="char_proto", kind=LayerKind.CHARACTER, base_prompt="x")
    )
    sheet = await executor.generate_sheet(
        asset_id="char_proto",
        refs=("/r1.png", "/r2.png", "/r3.png"),
        prompt="hero portrait",
    )
    assert sheet.asset_id == "char_proto"
    assert sheet.revision == 1
    assert sheet.sheet_image == "/fake-image-1.png"
    assert len(gen.calls) == 1
    assert gen.calls[0]["prompt"] == "hero portrait"


@pytest.mark.asyncio
async def test_regenerate_sheet_bumps_revision(
    executor: AssetExecutor,
) -> None:
    await executor.register_definition(
        AssetDefinition(asset_id="x", kind=LayerKind.CHARACTER, base_prompt="x")
    )
    s1 = await executor.generate_sheet(
        asset_id="x", refs=("/a.png", "/b.png", "/c.png"), prompt="p"
    )
    s2 = await executor.regenerate_sheet(asset_id="x", prompt="p2")
    s3 = await executor.regenerate_sheet(asset_id="x", prompt="p3")
    assert s1.revision == 1
    assert s2.revision == 2
    assert s3.revision == 3


@pytest.mark.asyncio
async def test_plan_returns_ordered_render_plan(
    executor: AssetExecutor,
) -> None:
    await executor.register_definition(
        AssetDefinition(asset_id="bg", kind=LayerKind.BACKGROUND, base_prompt="sky")
    )
    await executor.register_definition(
        AssetDefinition(asset_id="char", kind=LayerKind.CHARACTER, base_prompt="hero")
    )
    await executor.upsert_instance(
        AssetInstance(instance_id="b", canvas_id="c1", definition="bg", z_index=0)
    )
    await executor.upsert_instance(
        AssetInstance(instance_id="h", canvas_id="c1", definition="char", z_index=1)
    )
    plan = await executor.plan(canvas_id="c1", world_style=_world_style())
    assert plan.canvas_id == "c1"
    assert [r.instance_id for r in plan.rendered] == ["b", "h"]
    assert "sky" in plan.rendered[0].prompt
    assert "hero" in plan.rendered[1].prompt


@pytest.mark.asyncio
async def test_render_page_calls_backend_per_layer(
    executor: AssetExecutor, gen: FakeImageGenClient
) -> None:
    await executor.register_definition(
        AssetDefinition(asset_id="bg", kind=LayerKind.BACKGROUND, base_prompt="sky")
    )
    await executor.register_definition(
        AssetDefinition(asset_id="char", kind=LayerKind.CHARACTER, base_prompt="hero")
    )
    await executor.upsert_instance(
        AssetInstance(instance_id="b", canvas_id="c1", definition="bg", z_index=0)
    )
    await executor.upsert_instance(
        AssetInstance(instance_id="h", canvas_id="c1", definition="char", z_index=1)
    )
    plan = await executor.plan(canvas_id="c1", world_style=_world_style())
    rendered = await executor.render_page(canvas_id="c1", plan=plan)
    assert len(rendered) == 2
    # One backend call per layer.
    assert len(gen.calls) == 2
    # Each got a real prompt.
    assert all(c["prompt"] for c in gen.calls)


@pytest.mark.asyncio
async def test_render_page_passes_asset_sheet_when_planned(
    executor: AssetExecutor, gen: FakeImageGenClient
) -> None:
    sheet = AssetSheet(
        asset_id="char",
        refs=("/r1.png", "/r2.png", "/r3.png"),
        sheet_image="/fixed-sheet.png",
    )
    await executor.register_definition(
        AssetDefinition(
            asset_id="char",
            kind=LayerKind.CHARACTER,
            base_prompt="hero",
            asset_sheet=sheet,
        )
    )
    await executor.upsert_instance(
        AssetInstance(instance_id="h", canvas_id="c1", definition="char")
    )
    plan = await executor.plan(canvas_id="c1", world_style=_world_style())
    await executor.render_page(canvas_id="c1", plan=plan)
    # The render call should have received the sheet ref.
    [call] = gen.calls
    assert call["asset_sheet_ref"] == "/fixed-sheet.png"


# ─────────────────────────────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_unknown_action_raises(tool: AssetTool) -> None:
    with pytest.raises(ValueError, match="unknown action"):
        await tool.call("does_not_exist", {})


@pytest.mark.asyncio
async def test_tool_register_definition(tool: AssetTool) -> None:
    out = await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "x",
                "kind": "structure",
                "base_prompt": "a small house",
                "sockets": [],
            }
        },
    )
    assert out["definition"]["asset_id"] == "x"


@pytest.mark.asyncio
async def test_tool_round_trip_get_after_register(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "y",
                "kind": "prop",
                "base_prompt": "a balloon",
                "sockets": [],
            }
        },
    )
    out = await tool.call("get_definition", {"asset_id": "y"})
    assert out["definition"]["asset_id"] == "y"


@pytest.mark.asyncio
async def test_tool_list_definitions_filters_by_kind(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {"definition": {"asset_id": "h1", "kind": "structure", "base_prompt": "x", "sockets": []}},
    )
    await tool.call(
        "register_definition",
        {"definition": {"asset_id": "v1", "kind": "vehicle", "base_prompt": "x", "sockets": []}},
    )
    out = await tool.call("list_definitions", {"kind": "structure"})
    assert {d["asset_id"] for d in out["definitions"]} == {"h1"}


@pytest.mark.asyncio
async def test_tool_upsert_and_list_instances(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {"definition": {"asset_id": "a", "kind": "structure", "base_prompt": "x", "sockets": []}},
    )
    await tool.call(
        "upsert_instance",
        {
            "instance": {
                "instance_id": "i1",
                "canvas_id": "c1",
                "definition": "a",
                "anchor": "ground_contact",
            }
        },
    )
    out = await tool.call("list_instances", {"canvas_id": "c1"})
    assert len(out["instances"]) == 1
    assert out["instances"][0]["instance_id"] == "i1"


@pytest.mark.asyncio
async def test_tool_inline_definition_round_trip(tool: AssetTool) -> None:
    await tool.call(
        "upsert_instance",
        {
            "instance": {
                "instance_id": "cloud",
                "canvas_id": "c1",
                "definition": {
                    "asset_id": "",
                    "kind": "fx",
                    "base_prompt": "a wispy cloud",
                    "sockets": [],
                },
                "anchor": "floating",
            }
        },
    )
    out = await tool.call("list_instances", {"canvas_id": "c1"})
    assert out["instances"][0]["definition"]["kind"] == "fx"


@pytest.mark.asyncio
async def test_tool_remove_instance(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {"definition": {"asset_id": "a", "kind": "prop", "base_prompt": "x", "sockets": []}},
    )
    await tool.call(
        "upsert_instance",
        {"instance": {"instance_id": "i", "canvas_id": "c", "definition": "a"}},
    )
    out = await tool.call("remove_instance", {"instance_id": "i"})
    assert out["ok"] is True
    listing = await tool.call("list_instances", {"canvas_id": "c"})
    assert listing["instances"] == []


@pytest.mark.asyncio
async def test_tool_generate_sheet(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "char",
                "kind": "character",
                "base_prompt": "x",
                "sockets": [],
            }
        },
    )
    out = await tool.call(
        "generate_sheet",
        {
            "asset_id": "char",
            "refs": ["/a.png", "/b.png", "/c.png"],
            "prompt": "hero portrait",
        },
    )
    assert out["sheet"]["revision"] == 1
    assert out["sheet"]["sheet_image"].startswith("/fake-image-")


@pytest.mark.asyncio
async def test_tool_plan_returns_render_plan_dict(tool: AssetTool) -> None:
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "bg",
                "kind": "background",
                "base_prompt": "sky",
                "sockets": [],
            }
        },
    )
    await tool.call(
        "upsert_instance",
        {"instance": {"instance_id": "b", "canvas_id": "c1", "definition": "bg"}},
    )
    out = await tool.call(
        "plan",
        {
            "canvas_id": "c1",
            "world_style": {
                "era": "modern",
                "realism": "watercolor",
                "architectural_register": "cottage",
                "vehicle_register": "1970s-pickup",
                "palette_anchors": ["sage", "cream"],
                "fauna_realism": "cute",
            },
        },
    )
    plan = out["render_plan"]
    assert plan["canvas_id"] == "c1"
    assert len(plan["rendered"]) == 1
    assert plan["rendered"][0]["instance_id"] == "b"


@pytest.mark.asyncio
async def test_tool_render_page_returns_per_layer_images(
    tool: AssetTool, gen: FakeImageGenClient
) -> None:
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "bg",
                "kind": "background",
                "base_prompt": "sky",
                "sockets": [],
            }
        },
    )
    await tool.call(
        "upsert_instance",
        {"instance": {"instance_id": "b", "canvas_id": "c1", "definition": "bg"}},
    )
    out = await tool.call(
        "render_page",
        {
            "canvas_id": "c1",
            "world_style": {
                "era": "modern",
                "realism": "watercolor",
                "architectural_register": "cottage",
                "vehicle_register": "1970s-pickup",
                "palette_anchors": ["sage", "cream"],
                "fauna_realism": "cute",
            },
        },
    )
    assert len(out["results"]) == 1
    assert out["results"][0]["planned"]["instance_id"] == "b"
    assert len(out["results"][0]["images"]) == 1


@pytest.mark.asyncio
async def test_tool_complex_scene_round_trip(tool: AssetTool) -> None:
    """Smoke test: register a small scene, plan, render. Mirrors what
    the agent would actually do on a typical page."""
    # Definitions
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "farmhouse",
                "kind": "structure",
                "base_prompt": "a small red farmhouse",
                "sockets": [{"name": "porch", "x": 0.5, "y": 0.6, "role": None}],
            }
        },
    )
    await tool.call(
        "register_definition",
        {
            "definition": {
                "asset_id": "protag",
                "kind": "character",
                "base_prompt": "a young child",
                "sockets": [],
                "skin_set": {"protagonist": ["sarah"]},
            }
        },
    )
    # Instances on canvas c1
    await tool.call(
        "upsert_instance",
        {"instance": {"instance_id": "FH", "canvas_id": "c1", "definition": "farmhouse"}},
    )
    await tool.call(
        "upsert_instance",
        {
            "instance": {
                "instance_id": "S",
                "canvas_id": "c1",
                "definition": "protag",
                "parent_id": "FH",
                "parent_socket": "porch",
                "z_index": 1,
            }
        },
    )
    # Plan + render
    plan_out = await tool.call(
        "plan",
        {
            "canvas_id": "c1",
            "world_style": {
                "era": "modern",
                "realism": "watercolor",
                "architectural_register": "cottage",
                "vehicle_register": "1970s-pickup",
                "palette_anchors": ["sage", "cream"],
                "fauna_realism": "cute",
            },
        },
    )
    assert {r["instance_id"] for r in plan_out["render_plan"]["rendered"]} == {"FH", "S"}

    render_out = await tool.call(
        "render_page",
        {
            "canvas_id": "c1",
            "plan": plan_out["render_plan"],
        },
    )
    assert len(render_out["results"]) == 2

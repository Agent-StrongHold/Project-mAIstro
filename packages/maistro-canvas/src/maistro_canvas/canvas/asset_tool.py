"""Canvas asset tool — agent-facing surface for the ADR-039 model.
Per ADR-043.

Stateless dispatcher around an ``AssetExecutor``. JSON-serialisable
in/out so the existing agent tool protocol can call it without
shape-aware glue.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from maistro_canvas.canvas.asset_store import (
    _deser_definition,
    _deser_render_style,
    _deser_style_volume,
    _deser_world_style,
    _ser_definition,
)
from maistro_canvas.layers import (
    Anchor,
    AssetDefinition,
    AssetInstance,
    OcclusionHint,
    PersonalizationSlot,
    Slot,
    Transform,
)

if TYPE_CHECKING:
    from maistro_canvas.canvas.asset_executor import AssetExecutor


_VALID_ACTIONS = (
    "register_definition",
    "get_definition",
    "list_definitions",
    "upsert_instance",
    "get_instance",
    "list_instances",
    "remove_instance",
    "generate_sheet",
    "regenerate_sheet",
    "plan",
    "render_page",
)


class AssetTool:
    """In-process canvas asset tool.

    Mirrors the legacy ``canvas/tool.py`` shape (dispatch on
    ``action``, dict args/returns) so davinci's agent runtime can load
    both side by side.
    """

    name: str = "canvas_asset"
    description: str = (
        "ADR-039 canvas asset model — definitions, instances, sheets, "
        "render plans, and page rendering."
    )

    def __init__(self, executor: AssetExecutor) -> None:
        self._exec = executor

    async def call(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action not in _VALID_ACTIONS:
            msg = f"unknown action {action!r}; valid: {_VALID_ACTIONS}"
            raise ValueError(msg)
        handler = getattr(self, f"_action_{action}")
        result: dict[str, Any] = await handler(args)
        return result

    # ── Definitions ─────────────────────────────────────────────────

    async def _action_register_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        defn = _deser_definition(args["definition"])
        out = await self._exec.register_definition(defn)
        return {"definition": _ser_definition(out)}

    async def _action_get_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        out = await self._exec.get_definition(args["asset_id"])
        return {"definition": _ser_definition(out) if out is not None else None}

    async def _action_list_definitions(self, args: dict[str, Any]) -> dict[str, Any]:
        rows = await self._exec.list_definitions_by_kind(args["kind"])
        return {"definitions": [_ser_definition(d) for d in rows]}

    # ── Instances ───────────────────────────────────────────────────

    async def _action_upsert_instance(self, args: dict[str, Any]) -> dict[str, Any]:
        instance = _deser_instance(args["instance"])
        out = await self._exec.upsert_instance(instance)
        return {"instance": _ser_instance(out)}

    async def _action_get_instance(self, args: dict[str, Any]) -> dict[str, Any]:
        # `AssetExecutor` doesn't expose `get_instance` directly; look
        # through the canvas listing. For tool ergonomics we accept
        # a separate `canvas_id` argument.
        canvas_id = args["canvas_id"]
        instance_id = args["instance_id"]
        for i in await self._exec.list_instances(canvas_id):
            if i.instance_id == instance_id:
                return {"instance": _ser_instance(i)}
        return {"instance": None}

    async def _action_list_instances(self, args: dict[str, Any]) -> dict[str, Any]:
        rows = await self._exec.list_instances(args["canvas_id"])
        return {"instances": [_ser_instance(i) for i in rows]}

    async def _action_remove_instance(self, args: dict[str, Any]) -> dict[str, Any]:
        await self._exec.remove_instance(args["instance_id"])
        return {"ok": True}

    # ── Sheets ──────────────────────────────────────────────────────

    async def _action_generate_sheet(self, args: dict[str, Any]) -> dict[str, Any]:
        sheet = await self._exec.generate_sheet(
            asset_id=args["asset_id"],
            refs=tuple(args["refs"]),
            prompt=args["prompt"],
            params=args.get("params"),
        )
        return {"sheet": _ser_sheet(sheet)}

    async def _action_regenerate_sheet(self, args: dict[str, Any]) -> dict[str, Any]:
        refs = args.get("refs")
        sheet = await self._exec.regenerate_sheet(
            asset_id=args["asset_id"],
            prompt=args["prompt"],
            refs=tuple(refs) if refs is not None else None,
            params=args.get("params"),
        )
        return {"sheet": _ser_sheet(sheet)}

    # ── Render plan + page ─────────────────────────────────────────

    async def _action_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        from maistro_canvas.canvas.asset_routes import (  # local import to avoid FastAPI dep at module load
            _plan_to_model,
        )

        world_style = _deser_world_style(args["world_style"])
        volumes_raw = args.get("style_volumes") or []
        volumes = tuple(_deser_style_volume(v) for v in volumes_raw)
        render_style = (
            _deser_render_style(args["render_style"]) if args.get("render_style") else None
        )
        plan = await self._exec.plan(
            canvas_id=args["canvas_id"],
            world_style=world_style,
            style_volumes=volumes,
            page_index=args.get("page_index"),
            render_style=render_style,
            profile_id=args.get("profile_id"),
        )
        return {"render_plan": _plan_to_model(plan).model_dump()}

    async def _action_render_page(self, args: dict[str, Any]) -> dict[str, Any]:
        from maistro_canvas.canvas.asset_routes import (
            _planned_to_model,
        )

        # Reconstruct the RenderPlan we just planned via the same path
        # to avoid re-planning. We accept either the prior plan (dict)
        # or trigger a plan call on the spot.
        if "plan" in args:
            plan_dict = args["plan"]
            world_style = _deser_world_style(plan_dict["world_style"])
            from maistro_canvas.canvas.asset_compositor import (
                PlannedRender,
                RenderPlan,
            )

            rendered_plans = tuple(
                PlannedRender(
                    instance_id=p["instance_id"],
                    parent_chain=tuple(p["parent_chain"]),
                    resolved_transform=Transform(**p["resolved_transform"]),
                    prompt=p["prompt"],
                    asset_sheet_ref=p["asset_sheet_ref"],
                    skin_binding=p["skin_binding"],
                    z_index=p["z_index"],
                )
                for p in plan_dict["rendered"]
            )
            plan = RenderPlan(
                canvas_id=plan_dict["canvas_id"],
                page_index=plan_dict.get("page_index"),
                world_style=world_style,
                rendered=rendered_plans,
            )
        else:
            world_style = _deser_world_style(args["world_style"])
            volumes_raw = args.get("style_volumes") or []
            volumes = tuple(_deser_style_volume(v) for v in volumes_raw)
            render_style = (
                _deser_render_style(args["render_style"]) if args.get("render_style") else None
            )
            plan = await self._exec.plan(
                canvas_id=args["canvas_id"],
                world_style=world_style,
                style_volumes=volumes,
                page_index=args.get("page_index"),
                render_style=render_style,
                profile_id=args.get("profile_id"),
            )

        size = tuple(args.get("size") or (1024, 1024))
        rendered = await self._exec.render_page(
            canvas_id=args["canvas_id"],
            plan=plan,
            size=(int(size[0]), int(size[1])),
        )

        # Serialise per-layer image references; preserve ordering.
        return {
            "results": [
                {
                    "planned": _planned_to_model(planned).model_dump(),
                    "images": [
                        {"url": img.url, "width": img.width, "height": img.height} for img in images
                    ],
                }
                for planned, images in rendered
            ]
        }


# ─────────────────────────────────────────────────────────────────────
# Lightweight serialisation helpers used by the dispatcher.
# These wrap the existing _ser_*/_deser_* helpers from asset_store and
# add coverage for AssetInstance and AssetSheet which the store didn't
# need to expose at module level.
# ─────────────────────────────────────────────────────────────────────


def _ser_instance(i: AssetInstance) -> dict[str, Any]:
    if isinstance(i.definition, str):
        defn_field: str | dict[str, Any] = i.definition
    else:
        defn_field = _ser_definition(i.definition)
    return {
        "instance_id": i.instance_id,
        "canvas_id": i.canvas_id,
        "definition": defn_field,
        "parent_id": i.parent_id,
        "parent_socket": i.parent_socket,
        "transform": dataclasses.asdict(i.transform),
        "slot": dataclasses.asdict(i.slot) if i.slot is not None else None,
        "anchor": i.anchor.value if i.anchor is not None else None,
        "occlusion": {
            "in_front_of": list(i.occlusion.in_front_of),
            "behind": list(i.occlusion.behind),
        },
        "personalization": (
            {"kind": i.personalization.kind, "binding": i.personalization.binding}
            if i.personalization is not None
            else None
        ),
        "skin_binding": i.skin_binding,
        "prompt_nudge": i.prompt_nudge,
        "visible": i.visible,
        "locked": i.locked,
        "history": list(i.history),
        "z_index": i.z_index,
    }


def _deser_instance(d: dict[str, Any]) -> AssetInstance:
    raw_def = d["definition"]
    if isinstance(raw_def, str):
        definition: AssetDefinition | str = raw_def
    elif isinstance(raw_def, dict):
        definition = _deser_definition(raw_def)
    else:
        msg = f"definition must be str or dict, got {type(raw_def).__name__}"
        raise TypeError(msg)
    transform = d.get("transform") or {}
    slot_d = d.get("slot")
    occl = d.get("occlusion") or {"in_front_of": [], "behind": []}
    pers = d.get("personalization")
    return AssetInstance(
        instance_id=d["instance_id"],
        canvas_id=d["canvas_id"],
        definition=definition,
        parent_id=d.get("parent_id"),
        parent_socket=d.get("parent_socket"),
        transform=Transform(
            tx=float(transform.get("tx", 0.0)),
            ty=float(transform.get("ty", 0.0)),
            sx=float(transform.get("sx", 1.0)),
            sy=float(transform.get("sy", 1.0)),
            rotation=float(transform.get("rotation", 0.0)),
        ),
        slot=Slot(**slot_d) if slot_d is not None else None,
        anchor=Anchor(d["anchor"]) if d.get("anchor") is not None else None,
        occlusion=OcclusionHint(
            in_front_of=tuple(occl.get("in_front_of", [])),
            behind=tuple(occl.get("behind", [])),
        ),
        personalization=(
            PersonalizationSlot(kind=pers["kind"], binding=pers["binding"])
            if pers is not None
            else None
        ),
        skin_binding=dict(d["skin_binding"]) if d.get("skin_binding") is not None else None,
        prompt_nudge=d.get("prompt_nudge"),
        visible=bool(d.get("visible", True)),
        locked=bool(d.get("locked", False)),
        history=tuple(d.get("history", [])),
        z_index=int(d.get("z_index", 0)),
    )


def _ser_sheet(s: Any) -> dict[str, Any]:
    return {
        "asset_id": s.asset_id,
        "refs": list(s.refs),
        "sheet_image": s.sheet_image,
        "revision": s.revision,
        "generation_params": dict(s.generation_params),
    }


__all__ = ["AssetTool"]

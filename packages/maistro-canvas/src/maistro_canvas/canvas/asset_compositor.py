"""Canvas asset compositor — pure-logic scene-graph + occlusion + prompt
composition + personalisation compiler. Per ADR-041.

This module is deliberately PIL-free; pixel compositing remains in the
legacy ``compositor.py``. The output of ``plan_render`` is a
``RenderPlan`` consumed by the image-generation backend (or by tests).

Responsibilities:

- ``build_scene_graph``       — group instances into a parent → children
                                 tree; raises on missing parents and
                                 cycles.
- ``resolve_occlusion_order`` — topologically sort instances by
                                 ``OcclusionHint``; raises on cycles via
                                 ``OcclusionCycleError``.
- ``compile_personalization`` — fill in ``skin_binding`` from a
                                 ``ChildProfile``; raises
                                 ``SkinBindingError`` on unbound slots.
- ``compose_prompt``          — deterministic
                                 ``WorldStyle ⊕ matching StyleVolume ⊕
                                 RenderStyle ⊕ base_prompt ⊕ nudge ⊕
                                 skin_binding`` text composition.
- ``plan_render``             — top-level entry that runs the above and
                                 produces a ``RenderPlan``.

Transform composition: each ``PlannedRender`` carries a
``resolved_transform`` that is the matrix multiplication of every
ancestor's ``transform`` with the instance's own. Roots use their
``transform`` as-is.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace

from maistro_canvas.layers import (
    AssetDefinition,
    AssetInstance,
    ChildProfile,
    PersonalizationSlot,
    RenderStyle,
    StyleVolume,
    Transform,
    WorldStyle,
    merge_world_style,
)
from maistro_canvas.types import (
    OcclusionCycleError,
    SkinBindingError,
)

# ─────────────────────────────────────────────────────────────────────
# Scene graph
# ─────────────────────────────────────────────────────────────────────


@dataclass
class SceneNode:
    """Tree node wrapping an AssetInstance plus its children."""

    instance: AssetInstance
    children: list[SceneNode] = field(default_factory=list)
    parent: SceneNode | None = None


def build_scene_graph(instances: Iterable[AssetInstance]) -> list[SceneNode]:
    """Group instances into a parent → children tree.

    Raises ``ValueError`` if a ``parent_id`` references an instance not in
    the input list, or if the parent chain contains a cycle.
    """
    nodes: dict[str, SceneNode] = {}
    for instance in instances:
        if instance.instance_id in nodes:
            msg = f"Duplicate instance_id: {instance.instance_id!r}"
            raise ValueError(msg)
        nodes[instance.instance_id] = SceneNode(instance=instance)

    roots: list[SceneNode] = []
    for node in nodes.values():
        parent_id = node.instance.parent_id
        if parent_id is None:
            roots.append(node)
            continue
        parent = nodes.get(parent_id)
        if parent is None:
            msg = f"Instance {node.instance.instance_id!r} references missing parent {parent_id!r}"
            raise ValueError(msg)
        parent.children.append(node)
        node.parent = parent

    # Detect cycles — every node must be reachable from some root.
    seen: set[str] = set()
    for root in roots:
        for n in _walk_subtree(root):
            if n.instance.instance_id in seen:
                msg = f"Cycle detected involving {n.instance.instance_id!r}"
                raise ValueError(msg)
            seen.add(n.instance.instance_id)
    if len(seen) != len(nodes):
        unreachable = set(nodes) - seen
        msg = f"Cycle in parent chain; unreachable from any root: {sorted(unreachable)!r}"
        raise ValueError(msg)

    return roots


def _walk_subtree(node: SceneNode) -> Iterable[SceneNode]:
    """Depth-first walk of a subtree."""
    yield node
    for child in node.children:
        yield from _walk_subtree(child)


def _parent_chain(node: SceneNode) -> tuple[str, ...]:
    """Return root → node ids inclusive."""
    chain: list[str] = []
    cur: SceneNode | None = node
    while cur is not None:
        chain.append(cur.instance.instance_id)
        cur = cur.parent
    return tuple(reversed(chain))


# ─────────────────────────────────────────────────────────────────────
# Transform composition
# ─────────────────────────────────────────────────────────────────────


def _compose_transforms(parent: Transform, child: Transform) -> Transform:
    """Compose parent ∘ child (parent first, then child).

    Standard 2D affine composition: scale and rotation accumulate
    multiplicatively; translation is parent's plus child's translation
    in parent's local frame.

    For v1, rotation handling is small-angle (no actual rotation
    matrix on the translation); books rarely use compound rotation,
    and we'll revisit if needed.
    """
    return Transform(
        tx=parent.tx + child.tx * parent.sx,
        ty=parent.ty + child.ty * parent.sy,
        sx=parent.sx * child.sx,
        sy=parent.sy * child.sy,
        rotation=(parent.rotation + child.rotation) % 360.0,
    )


def _resolve_transform(node: SceneNode) -> Transform:
    """Walk root → node and compose transforms."""
    chain: list[Transform] = []
    cur: SceneNode | None = node
    while cur is not None:
        chain.append(cur.instance.transform)
        cur = cur.parent
    chain.reverse()
    out = chain[0]
    for t in chain[1:]:
        out = _compose_transforms(out, t)
    return out


# ─────────────────────────────────────────────────────────────────────
# Occlusion
# ─────────────────────────────────────────────────────────────────────


def _add_edge(
    edge_from: str,
    edge_to: str,
    relation_label: str,
    by_id: dict[str, AssetInstance],
    successors: dict[str, set[str]],
    indegree: dict[str, int],
) -> None:
    """Add a `from -> to` edge after validating it. Raises on self-loops
    and references to unknown instances. The unknown-instance check uses
    whichever endpoint of the edge isn't in by_id (since one endpoint
    comes from the OcclusionHint, the other from the source instance)."""
    if edge_from == edge_to:
        raise OcclusionCycleError(f"self-loop {relation_label} on {edge_from!r}")
    for endpoint in (edge_from, edge_to):
        if endpoint not in by_id:
            raise OcclusionCycleError(
                f"references unknown instance {endpoint!r} in {relation_label}"
            )
    if edge_to not in successors[edge_from]:
        successors[edge_from].add(edge_to)
        indegree[edge_to] += 1


def _build_occlusion_edges(
    instances: Sequence[AssetInstance],
    by_id: dict[str, AssetInstance],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Build successor sets and indegree counts from OcclusionHints.

    `A in_front_of B` means B appears before A → edge B -> A.
    `A behind C` means A appears before C → edge A -> C.
    """
    successors: dict[str, set[str]] = {iid: set() for iid in by_id}
    indegree: dict[str, int] = dict.fromkeys(by_id, 0)

    for instance in instances:
        iid = instance.instance_id
        for other in instance.occlusion.in_front_of:
            _add_edge(other, iid, "in_front_of", by_id, successors, indegree)
        for other in instance.occlusion.behind:
            _add_edge(iid, other, "behind", by_id, successors, indegree)

    return successors, indegree


def resolve_occlusion_order(instances: Sequence[AssetInstance]) -> list[AssetInstance]:
    """Topologically order instances honouring ``OcclusionHint``.

    Constraints:

    - For each instance A with ``in_front_of=(B, ...)``, A must appear
      after B in the result.
    - For each instance A with ``behind=(C, ...)``, A must appear before
      C in the result.
    - Within those constraints, ties break on ``z_index`` ASC then
      input order.

    Raises ``OcclusionCycleError`` on self-loop or any cycle, including
    references to instance_ids not in the input list (unresolvable).
    """
    by_id: dict[str, AssetInstance] = {i.instance_id: i for i in instances}
    if len(by_id) != len(instances):
        msg = "duplicate instance_id in input"
        raise ValueError(msg)

    successors, indegree = _build_occlusion_edges(instances, by_id)

    # Stable topological sort: zero-indegree pool prioritised by
    # (z_index, input order).
    input_order = {i.instance_id: idx for idx, i in enumerate(instances)}
    ready = [iid for iid, deg in indegree.items() if deg == 0]

    def _key(iid: str) -> tuple[int, int]:
        return (by_id[iid].z_index, input_order[iid])

    ready.sort(key=_key)
    out: list[AssetInstance] = []
    while ready:
        iid = ready.pop(0)
        out.append(by_id[iid])
        for succ in successors[iid]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                # Insert sorted to preserve stability.
                ready.append(succ)
                ready.sort(key=_key)

    if len(out) != len(by_id):
        remaining = sorted(set(by_id) - {i.instance_id for i in out})
        raise OcclusionCycleError(f"cycle in occlusion graph involving {remaining!r}")

    return out


# ─────────────────────────────────────────────────────────────────────
# Personalisation
# ─────────────────────────────────────────────────────────────────────


_BINDING_NAME_RE = re.compile(r"[^a-z_]")


def _normalise_binding_value(value: str) -> str:
    """Lowercase + strip non-[a-z_] chars (per ADR-039 EC-12)."""
    return _BINDING_NAME_RE.sub("", value.lower())


def compile_personalization(
    instances: Sequence[AssetInstance],
    profile: ChildProfile | None,
    *,
    registry: Callable[[str], AssetDefinition | None] | None = None,
) -> list[AssetInstance]:
    """Fill in ``skin_binding`` for every instance with a
    ``PersonalizationSlot``.

    ``registry`` is a lookup function used to validate that the
    chosen skin exists in the parent definition's ``skin_set``. If
    ``None``, only the ``ChildProfile``-sourced skin name is generated;
    validation against ``skin_set`` is deferred to render time.

    Raises ``SkinBindingError`` if a ``PersonalizationSlot`` references
    a skin that the parent definition's ``skin_set`` doesn't include.
    """
    out: list[AssetInstance] = []
    for instance in instances:
        if instance.personalization is None:
            out.append(instance)
            continue
        skin_name = _resolve_skin_name(instance.personalization, profile)
        binding = {instance.personalization.binding: skin_name}
        if registry is not None:
            defn = _resolve_definition(instance.definition, registry)
            if defn is not None and defn.skin_set is not None:
                allowed = set(defn.skin_set.get(instance.personalization.binding, ()))
                if allowed and skin_name not in allowed:
                    raise SkinBindingError(
                        f"{instance.instance_id!r}: skin {skin_name!r} not in "
                        f"definition.skin_set[{instance.personalization.binding!r}] = "
                        f"{sorted(allowed)!r}"
                    )
        out.append(replace(instance, skin_binding=binding))
    return out


def _resolve_definition(
    definition: AssetDefinition | str,
    registry: Callable[[str], AssetDefinition | None],
) -> AssetDefinition | None:
    if isinstance(definition, AssetDefinition):
        return definition
    return registry(definition)


def _resolve_skin_name(slot: PersonalizationSlot, profile: ChildProfile | None) -> str:
    """Map a PersonalizationSlot to a skin variant name."""
    if slot.kind == "child_likeness":
        if profile is None:
            raise SkinBindingError(
                f"PersonalizationSlot kind={slot.kind!r} requires a ChildProfile"
            )
        return _normalise_binding_value(profile.name)
    if slot.kind == "child_name":
        if profile is None:
            raise SkinBindingError(
                f"PersonalizationSlot kind={slot.kind!r} requires a ChildProfile"
            )
        return profile.name
    if slot.kind == "pronouns":
        if profile is None:
            raise SkinBindingError(
                f"PersonalizationSlot kind={slot.kind!r} requires a ChildProfile"
            )
        return profile.pronouns or "they/them"
    if slot.kind in ("companion", "pet", "gift", "place_name"):
        return slot.binding
    msg = f"Unknown PersonalizationSlot.kind: {slot.kind!r}"
    raise SkinBindingError(msg)


# ─────────────────────────────────────────────────────────────────────
# Prompt composition
# ─────────────────────────────────────────────────────────────────────


def _serialise_world_style(w: WorldStyle) -> str:
    parts = [
        f"era: {w.era}",
        f"realism: {w.realism}",
        f"architecture: {w.architectural_register}",
        f"vehicles: {w.vehicle_register}",
        f"fauna: {w.fauna_realism}",
    ]
    if w.palette_anchors:
        parts.append("palette: " + ", ".join(w.palette_anchors))
    return "; ".join(parts)


def _serialise_render_style(r: RenderStyle | None) -> str:
    if r is None:
        return ""
    parts: list[str] = []
    if r.style_token:
        parts.append(f"style: {r.style_token}")
    if r.palette_override:
        parts.append("palette override: " + ", ".join(r.palette_override))
    if r.line_weight is not None:
        parts.append(f"line weight: {r.line_weight}")
    return "; ".join(parts)


def _matching_volumes(
    style_volumes: Sequence[StyleVolume], page_index: int | None
) -> list[StyleVolume]:
    if page_index is None:
        return []
    return [sv for sv in style_volumes if sv.page_range[0] <= page_index <= sv.page_range[1]]


def _serialise_skin_binding(binding: dict[str, str] | None) -> str:
    if not binding:
        return ""
    return "; ".join(f"as {v}" for v in binding.values())


def compose_prompt(
    *,
    world_style: WorldStyle,
    style_volumes: Sequence[StyleVolume] = (),
    page_index: int | None = None,
    render_style: RenderStyle | None = None,
    base_prompt: str,
    prompt_nudge: str | None = None,
    skin_binding: dict[str, str] | None = None,
) -> str:
    """Compose the per-layer prompt deterministically.

    Order: WorldStyle ⊕ matching StyleVolumes (later wins) ⊕ RenderStyle
    ⊕ base_prompt ⊕ prompt_nudge ⊕ skin_binding. Empty fields skipped.
    """
    matched = _matching_volumes(style_volumes, page_index)
    effective_world = merge_world_style(world_style, *(sv.partial_world_style for sv in matched))

    # RenderStyle is the per-image override; per ADR-039 §6 it applies
    # above the WorldStyle. If a StyleVolume contributed a partial
    # render style, fold it in (later wins on overlapping fields).
    effective_render = render_style
    for sv in matched:
        if sv.partial_render_style is not None:
            if effective_render is None:
                effective_render = sv.partial_render_style
            else:
                effective_render = RenderStyle(
                    style_token=(
                        sv.partial_render_style.style_token
                        if sv.partial_render_style.style_token is not None
                        else effective_render.style_token
                    ),
                    palette_override=(
                        sv.partial_render_style.palette_override
                        if sv.partial_render_style.palette_override is not None
                        else effective_render.palette_override
                    ),
                    line_weight=(
                        sv.partial_render_style.line_weight
                        if sv.partial_render_style.line_weight is not None
                        else effective_render.line_weight
                    ),
                )

    parts = [
        _serialise_world_style(effective_world),
        _serialise_render_style(effective_render),
        base_prompt,
        prompt_nudge or "",
        _serialise_skin_binding(skin_binding),
    ]
    return "; ".join(p for p in parts if p)


__all_helpers__ = (
    "_serialise_world_style",
    "_serialise_render_style",
    "_matching_volumes",
)


# ─────────────────────────────────────────────────────────────────────
# Render plan
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlannedRender:
    """Resolved per-instance render decision."""

    instance_id: str
    parent_chain: tuple[str, ...]
    resolved_transform: Transform
    prompt: str
    asset_sheet_ref: str | None
    skin_binding: dict[str, str] | None
    z_index: int


@dataclass(frozen=True)
class RenderPlan:
    """Ordered render plan for a canvas. Consumed by the image
    backend or by previews."""

    canvas_id: str
    page_index: int | None
    world_style: WorldStyle
    rendered: tuple[PlannedRender, ...]


def plan_render(
    *,
    canvas_id: str,
    instances: Sequence[AssetInstance],
    world_style: WorldStyle,
    style_volumes: Sequence[StyleVolume] = (),
    page_index: int | None = None,
    render_style: RenderStyle | None = None,
    profile: ChildProfile | None = None,
    registry_lookup: Callable[[str], AssetDefinition | None] | None = None,
) -> RenderPlan:
    """Top-level: build the scene graph, resolve transforms and
    occlusion, compile personalisation, compose prompts, and emit a
    `RenderPlan`. Pure function of its inputs.
    """
    # Compile personalisation first so prompts can include skin bindings.
    compiled = compile_personalization(instances, profile, registry=registry_lookup)

    # Build the scene graph and an instance_id -> SceneNode index for
    # transform resolution.
    roots = build_scene_graph(compiled)
    by_id_node: dict[str, SceneNode] = {}
    for root in roots:
        for n in _walk_subtree(root):
            by_id_node[n.instance.instance_id] = n

    # Occlusion-ordered list across the whole canvas (siblings + roots
    # alike). Children that have parents still appear in this order;
    # the compositor can choose to render them with their parent's
    # transform applied.
    ordered = resolve_occlusion_order(compiled)

    rendered: list[PlannedRender] = []
    for instance in ordered:
        node = by_id_node[instance.instance_id]
        resolved = _resolve_transform(node)
        defn = _resolve_definition(
            instance.definition,
            registry_lookup if registry_lookup is not None else _no_registry,
        )
        base_prompt = defn.base_prompt if defn is not None else ""
        sheet_ref = (
            defn.asset_sheet.sheet_image
            if defn is not None and defn.asset_sheet is not None
            else None
        )
        prompt = compose_prompt(
            world_style=world_style,
            style_volumes=style_volumes,
            page_index=page_index,
            render_style=render_style,
            base_prompt=base_prompt,
            prompt_nudge=instance.prompt_nudge,
            skin_binding=instance.skin_binding,
        )
        rendered.append(
            PlannedRender(
                instance_id=instance.instance_id,
                parent_chain=_parent_chain(node),
                resolved_transform=resolved,
                prompt=prompt,
                asset_sheet_ref=sheet_ref,
                skin_binding=instance.skin_binding,
                z_index=instance.z_index,
            )
        )

    return RenderPlan(
        canvas_id=canvas_id,
        page_index=page_index,
        world_style=world_style,
        rendered=tuple(rendered),
    )


def _no_registry(_: str) -> AssetDefinition | None:
    return None


__all__ = [
    "PlannedRender",
    "RenderPlan",
    "SceneNode",
    "build_scene_graph",
    "compile_personalization",
    "compose_prompt",
    "plan_render",
    "resolve_occlusion_order",
]

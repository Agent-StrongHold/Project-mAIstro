"""FastAPI router for the ADR-039 canvas asset model. Per ADR-042.

Mounted at ``/v2/canvas`` (legacy ``/v1`` routes in routes.py are
unchanged). The router takes a ``get_store`` factory dependency so the
same code works with ``InMemoryAssetStore`` (tests) and
``PostgresAssetStore`` (production).

Each handler is a thin wrapper around the asset store + compositor.
Pydantic models define the request/response wire schemas; conversion
to/from the dataclasses uses the existing ``_ser_*`` / ``_deser_*``
helpers in ``asset_store.py`` (single source of truth for shape).
"""

# B008 (function-call-in-default-argument) is the standard FastAPI
# dependency-injection pattern (Body(...), Depends(...), Path(...),
# Query(...)). C901 (complex-structure) fires on make_router because
# the router exposes ~15 endpoints in one factory and on render_plan
# because the planner has many optional inputs to reconcile; both are
# inherent to the design.
# ruff: noqa: B008, C901

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from maistro_canvas.auth import CurrentUser, get_current_user
from maistro_canvas.canvas.asset_compositor import (
    PlannedRender,
    RenderPlan,
    plan_render,
)
from maistro_canvas.canvas.asset_store import (
    Book,
    InMemoryAssetStore,
    _deser_definition,
    _deser_render_style,
    _deser_style_volume,
    _ser_definition,
    _ser_style_volume,
    _ser_world_style,
)
from maistro_canvas.layers import Anchor as AnchorEnum
from maistro_canvas.layers import (
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    ChildProfile,
    OcclusionHint,
    PersonalizationSlot,
    Slot,
    StyleVolume,
    Transform,
    WorldStyle,
)
from maistro_canvas.types import (
    AssetDefinitionNotFoundError,
    AssetSheetNotFoundError,
    MissingSocketError,
    OcclusionCycleError,
    PoseGeometryMismatchError,
    SkinBindingError,
    WorldStyleConflictError,
)


class AssetStore(Protocol):
    """Structural protocol covering the methods this router calls.
    Both ``InMemoryAssetStore`` and ``PostgresAssetStore`` satisfy it."""

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def get_definition(self, asset_id: str) -> AssetDefinition | None: ...
    async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]: ...
    async def update_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def upsert_sheet(self, sheet: AssetSheet) -> AssetSheet: ...
    async def get_sheet(self, asset_id: str) -> AssetSheet | None: ...
    async def regenerate_sheet(
        self,
        asset_id: str,
        sheet_image: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet: ...
    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance: ...
    async def get_instance(self, instance_id: str) -> AssetInstance | None: ...
    async def list_instances(self, canvas_id: str) -> list[AssetInstance]: ...
    async def remove_instance(self, instance_id: str) -> None: ...
    async def upsert_profile(self, profile: ChildProfile) -> ChildProfile: ...
    async def get_profile(self, profile_id: str) -> ChildProfile | None: ...
    async def get_book(self, book_id: str) -> Book | None: ...
    async def update_book(self, book: Book) -> Book: ...


GetStore = Callable[[], AssetStore]


# ─────────────────────────────────────────────────────────────────────
# Pydantic wire schemas
# ─────────────────────────────────────────────────────────────────────


class AssetSheetIn(BaseModel):
    asset_id: str
    refs: list[str]
    sheet_image: str
    revision: int = 1
    generation_params: dict[str, Any] = Field(default_factory=dict)


class AssetSheetOut(AssetSheetIn):
    pass


class AssetDefinitionIn(BaseModel):
    """Wire shape mirroring `AssetDefinition`. Nested fields use
    `dict[str, Any]` so the existing deserialiser owns the shape rules."""

    asset_id: str
    kind: str
    base_prompt: str
    asset_sheet: AssetSheetIn | None = None
    sockets: list[dict[str, Any]] = Field(default_factory=list)
    skin_set: dict[str, list[str]] | None = None
    default_world_style: dict[str, Any] | None = None
    pose_geometry: dict[str, Any] | None = None


class AssetDefinitionOut(AssetDefinitionIn):
    pass


class TransformModel(BaseModel):
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rotation: float = 0.0


class SlotModel(BaseModel):
    x: float
    y: float
    w: float
    h: float


class OcclusionHintModel(BaseModel):
    in_front_of: list[str] = Field(default_factory=list)
    behind: list[str] = Field(default_factory=list)


class PersonalizationSlotModel(BaseModel):
    kind: str
    binding: str


class AssetInstanceIn(BaseModel):
    """Wire shape for AssetInstance. `definition` is either a registry
    id (string) or an inline AssetDefinitionIn."""

    instance_id: str
    canvas_id: str
    definition: str | AssetDefinitionIn
    parent_id: str | None = None
    parent_socket: str | None = None
    transform: TransformModel = Field(default_factory=TransformModel)
    slot: SlotModel | None = None
    anchor: str | None = None
    occlusion: OcclusionHintModel = Field(default_factory=OcclusionHintModel)
    personalization: PersonalizationSlotModel | None = None
    skin_binding: dict[str, str] | None = None
    prompt_nudge: str | None = None
    visible: bool = True
    locked: bool = False
    history: list[str] = Field(default_factory=list)
    z_index: int = 0


class AssetInstanceOut(AssetInstanceIn):
    pass


class ChildProfileIn(BaseModel):
    profile_id: str
    name: str
    pronouns: str | None = None
    likeness_refs: list[str] = Field(default_factory=list)
    accommodations: list[str] = Field(default_factory=list)
    age_range: str | None = None
    reading_level: str | None = None


class ChildProfileOut(ChildProfileIn):
    pass


class WorldStyleModel(BaseModel):
    era: str
    realism: str
    architectural_register: str
    vehicle_register: str
    palette_anchors: list[str]
    fauna_realism: str


class StyleVolumeModel(BaseModel):
    page_range: tuple[int, int]
    partial_world_style: dict[str, Any] | None = None
    partial_render_style: dict[str, Any] | None = None


class RenderStyleModel(BaseModel):
    style_token: str | None = None
    palette_override: list[str] | None = None
    line_weight: float | None = None


class RegenerateRequest(BaseModel):
    sheet_image: str
    refs: list[str] | None = None
    generation_params: dict[str, Any] | None = None


class BookIn(BaseModel):
    book_id: str
    title: str
    world_style: WorldStyleModel
    style_volumes: list[StyleVolumeModel] = Field(default_factory=list)
    profile_id: str | None = None
    org_id: str = ""


class BookOut(BookIn):
    pass


class PlanRequest(BaseModel):
    page_index: int | None = None
    profile_id: str | None = None
    render_style: RenderStyleModel | None = None
    # Override world_style + volumes from the book row when present.
    world_style: WorldStyleModel | None = None
    style_volumes: list[StyleVolumeModel] | None = None
    book_id: str | None = None


class PlannedRenderModel(BaseModel):
    instance_id: str
    parent_chain: list[str]
    resolved_transform: TransformModel
    prompt: str
    asset_sheet_ref: str | None
    skin_binding: dict[str, str] | None
    z_index: int


class RenderPlanModel(BaseModel):
    canvas_id: str
    page_index: int | None
    world_style: WorldStyleModel
    rendered: list[PlannedRenderModel]


# ─────────────────────────────────────────────────────────────────────
# Conversion helpers (Pydantic ↔ dataclass)
# ─────────────────────────────────────────────────────────────────────


def _definition_in_to_dataclass(d: AssetDefinitionIn) -> AssetDefinition:
    sheet_dict = d.asset_sheet.model_dump() if d.asset_sheet is not None else None
    payload = {
        "asset_id": d.asset_id,
        "kind": d.kind,
        "base_prompt": d.base_prompt,
        "asset_sheet": sheet_dict,
        "sockets": d.sockets,
        "skin_set": d.skin_set,
        "default_world_style": d.default_world_style,
        "pose_geometry": d.pose_geometry,
    }
    return _deser_definition(payload)


def _definition_to_out(d: AssetDefinition) -> AssetDefinitionOut:
    ser = _ser_definition(d)
    return AssetDefinitionOut.model_validate(ser)


def _instance_in_to_dataclass(i: AssetInstanceIn) -> AssetInstance:
    if isinstance(i.definition, str):
        definition: AssetDefinition | str = i.definition
    else:
        definition = _definition_in_to_dataclass(i.definition)
    return AssetInstance(
        instance_id=i.instance_id,
        canvas_id=i.canvas_id,
        definition=definition,
        parent_id=i.parent_id,
        parent_socket=i.parent_socket,
        transform=Transform(**i.transform.model_dump()),
        slot=Slot(**i.slot.model_dump()) if i.slot is not None else None,
        anchor=AnchorEnum(i.anchor) if i.anchor is not None else None,
        occlusion=OcclusionHint(
            in_front_of=tuple(i.occlusion.in_front_of),
            behind=tuple(i.occlusion.behind),
        ),
        personalization=(
            PersonalizationSlot(
                kind=i.personalization.kind,  # type: ignore[arg-type]
                binding=i.personalization.binding,
            )
            if i.personalization is not None
            else None
        ),
        skin_binding=dict(i.skin_binding) if i.skin_binding is not None else None,
        prompt_nudge=i.prompt_nudge,
        visible=i.visible,
        locked=i.locked,
        history=tuple(i.history),
        z_index=i.z_index,
    )


def _instance_to_out(i: AssetInstance) -> AssetInstanceOut:
    if isinstance(i.definition, str):
        defn_field: str | AssetDefinitionIn = i.definition
    else:
        defn_field = AssetDefinitionIn.model_validate(_ser_definition(i.definition))
    return AssetInstanceOut(
        instance_id=i.instance_id,
        canvas_id=i.canvas_id,
        definition=defn_field,
        parent_id=i.parent_id,
        parent_socket=i.parent_socket,
        transform=TransformModel(**dataclasses.asdict(i.transform)),
        slot=SlotModel(**dataclasses.asdict(i.slot)) if i.slot is not None else None,
        anchor=i.anchor.value if i.anchor is not None else None,
        occlusion=OcclusionHintModel(
            in_front_of=list(i.occlusion.in_front_of),
            behind=list(i.occlusion.behind),
        ),
        personalization=(
            PersonalizationSlotModel(kind=i.personalization.kind, binding=i.personalization.binding)
            if i.personalization is not None
            else None
        ),
        skin_binding=i.skin_binding,
        prompt_nudge=i.prompt_nudge,
        visible=i.visible,
        locked=i.locked,
        history=list(i.history),
        z_index=i.z_index,
    )


def _world_style_in_to_dc(w: WorldStyleModel) -> WorldStyle:
    return WorldStyle(
        era=w.era,
        realism=w.realism,  # type: ignore[arg-type]
        architectural_register=w.architectural_register,
        vehicle_register=w.vehicle_register,
        palette_anchors=tuple(w.palette_anchors),
        fauna_realism=w.fauna_realism,  # type: ignore[arg-type]
    )


def _world_style_to_out(w: WorldStyle) -> WorldStyleModel:
    return WorldStyleModel.model_validate(_ser_world_style(w))


def _book_to_out(b: Book) -> BookOut:
    return BookOut(
        book_id=b.book_id,
        title=b.title,
        world_style=_world_style_to_out(b.world_style),
        style_volumes=[
            StyleVolumeModel.model_validate(_ser_style_volume(sv)) for sv in b.style_volumes
        ],
        profile_id=b.profile_id,
        org_id=b.org_id,
    )


def _planned_to_model(p: PlannedRender) -> PlannedRenderModel:
    return PlannedRenderModel(
        instance_id=p.instance_id,
        parent_chain=list(p.parent_chain),
        resolved_transform=TransformModel(**dataclasses.asdict(p.resolved_transform)),
        prompt=p.prompt,
        asset_sheet_ref=p.asset_sheet_ref,
        skin_binding=p.skin_binding,
        z_index=p.z_index,
    )


def _plan_to_model(plan: RenderPlan) -> RenderPlanModel:
    return RenderPlanModel(
        canvas_id=plan.canvas_id,
        page_index=plan.page_index,
        world_style=_world_style_to_out(plan.world_style),
        rendered=[_planned_to_model(p) for p in plan.rendered],
    )


# ─────────────────────────────────────────────────────────────────────
# Domain-error → HTTP mapping
# ─────────────────────────────────────────────────────────────────────


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AssetDefinitionNotFoundError):
        return HTTPException(404, {"detail": str(exc), "code": exc.code})
    if isinstance(exc, AssetSheetNotFoundError):
        return HTTPException(404, {"detail": str(exc), "code": exc.code})
    if isinstance(
        exc,
        OcclusionCycleError
        | SkinBindingError
        | MissingSocketError
        | PoseGeometryMismatchError
        | WorldStyleConflictError,
    ):
        return HTTPException(422, {"detail": str(exc), "code": exc.code})
    if isinstance(exc, ValueError):
        return HTTPException(400, {"detail": str(exc)})
    return HTTPException(500, {"detail": str(exc)})


# ─────────────────────────────────────────────────────────────────────
# Router factory
# ─────────────────────────────────────────────────────────────────────


def make_router(get_store: GetStore) -> APIRouter:
    """Build a FastAPI router wired to a store factory.

    Tests pass an ``InMemoryAssetStore`` factory; production passes a
    factory producing a session-bound ``PostgresAssetStore``.
    """
    router = APIRouter(prefix="/v2/canvas", tags=["canvas-v2"])

    async def store_dep() -> AssetStore:
        return get_store()

    # ── AssetDefinition ─────────────────────────────────────────────

    @router.post(
        "/asset-definitions",
        response_model=AssetDefinitionOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def register_definition(
        body: AssetDefinitionIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetDefinitionOut:
        try:
            defn = _definition_in_to_dataclass(body)
            saved = await store.register_definition(defn)
            return _definition_to_out(saved)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/asset-definitions/{asset_id}", response_model=AssetDefinitionOut)
    async def get_definition(
        asset_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetDefinitionOut:
        defn = await store.get_definition(asset_id)
        if defn is None:
            raise HTTPException(
                404,
                {
                    "detail": f"AssetDefinition {asset_id!r} not found",
                    "code": "ASSET_DEFINITION_NOT_FOUND",
                },
            )
        return _definition_to_out(defn)

    @router.get("/asset-definitions", response_model=list[AssetDefinitionOut])
    async def list_definitions(
        kind: str = Query(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> list[AssetDefinitionOut]:
        defs = await store.list_definitions_by_kind(kind)
        return [_definition_to_out(d) for d in defs]

    @router.put("/asset-definitions/{asset_id}", response_model=AssetDefinitionOut)
    async def update_definition(
        asset_id: str = Path(...),
        body: AssetDefinitionIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetDefinitionOut:
        if asset_id != body.asset_id:
            raise HTTPException(409, {"detail": "asset_id in path and body do not match"})
        try:
            saved = await store.update_definition(_definition_in_to_dataclass(body))
            return _definition_to_out(saved)
        except Exception as exc:
            raise _http_error(exc) from exc

    # ── AssetSheet ──────────────────────────────────────────────────

    @router.put("/asset-sheets/{asset_id}", response_model=AssetSheetOut)
    async def upsert_sheet(
        asset_id: str = Path(...),
        body: AssetSheetIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetSheetOut:
        if asset_id != body.asset_id:
            raise HTTPException(409, {"detail": "asset_id in path and body do not match"})
        sheet = AssetSheet(
            asset_id=body.asset_id,
            refs=tuple(body.refs),
            sheet_image=body.sheet_image,
            revision=body.revision,
            generation_params=dict(body.generation_params),
        )
        await store.upsert_sheet(sheet)
        return AssetSheetOut(**body.model_dump())

    @router.get("/asset-sheets/{asset_id}", response_model=AssetSheetOut)
    async def get_sheet(
        asset_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetSheetOut:
        sheet = await store.get_sheet(asset_id)
        if sheet is None:
            raise HTTPException(
                404,
                {"detail": f"AssetSheet {asset_id!r} not found", "code": "ASSET_SHEET_NOT_FOUND"},
            )
        return AssetSheetOut(
            asset_id=sheet.asset_id,
            refs=list(sheet.refs),
            sheet_image=sheet.sheet_image,
            revision=sheet.revision,
            generation_params=dict(sheet.generation_params),
        )

    @router.post("/asset-sheets/{asset_id}/regenerate", response_model=AssetSheetOut)
    async def regenerate_sheet(
        asset_id: str = Path(...),
        body: RegenerateRequest = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetSheetOut:
        try:
            sheet = await store.regenerate_sheet(
                asset_id,
                body.sheet_image,
                refs=tuple(body.refs) if body.refs is not None else None,
                params=body.generation_params,
            )
            return AssetSheetOut(
                asset_id=sheet.asset_id,
                refs=list(sheet.refs),
                sheet_image=sheet.sheet_image,
                revision=sheet.revision,
                generation_params=dict(sheet.generation_params),
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    # ── AssetInstance ───────────────────────────────────────────────

    @router.post("/asset-instances", response_model=AssetInstanceOut)
    async def upsert_instance(
        body: AssetInstanceIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetInstanceOut:
        try:
            instance = _instance_in_to_dataclass(body)
            saved = await store.upsert_instance(instance)
            return _instance_to_out(saved)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/asset-instances/{instance_id}", response_model=AssetInstanceOut)
    async def get_instance(
        instance_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> AssetInstanceOut:
        instance = await store.get_instance(instance_id)
        if instance is None:
            raise HTTPException(404, {"detail": f"AssetInstance {instance_id!r} not found"})
        return _instance_to_out(instance)

    @router.delete("/asset-instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_instance(
        instance_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> None:
        await store.remove_instance(instance_id)

    @router.get(
        "/canvases/{canvas_id}/instances",
        response_model=list[AssetInstanceOut],
    )
    async def list_instances(
        canvas_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> list[AssetInstanceOut]:
        rows = await store.list_instances(canvas_id)
        return [_instance_to_out(r) for r in rows]

    # ── ChildProfile ────────────────────────────────────────────────

    @router.put("/child-profiles/{profile_id}", response_model=ChildProfileOut)
    async def upsert_profile(
        profile_id: str = Path(...),
        body: ChildProfileIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> ChildProfileOut:
        if profile_id != body.profile_id:
            raise HTTPException(409, {"detail": "profile_id in path and body do not match"})
        profile = ChildProfile(
            profile_id=body.profile_id,
            name=body.name,
            pronouns=body.pronouns,
            likeness_refs=tuple(body.likeness_refs),
            accommodations=tuple(body.accommodations),
            age_range=body.age_range,
            reading_level=body.reading_level,
        )
        await store.upsert_profile(profile)
        return ChildProfileOut(**body.model_dump())

    @router.get("/child-profiles/{profile_id}", response_model=ChildProfileOut)
    async def get_profile(
        profile_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> ChildProfileOut:
        profile = await store.get_profile(profile_id)
        if profile is None:
            raise HTTPException(404, {"detail": f"ChildProfile {profile_id!r} not found"})
        return ChildProfileOut(
            profile_id=profile.profile_id,
            name=profile.name,
            pronouns=profile.pronouns,
            likeness_refs=list(profile.likeness_refs),
            accommodations=list(profile.accommodations),
            age_range=profile.age_range,
            reading_level=profile.reading_level,
        )

    # ── Book ────────────────────────────────────────────────────────

    @router.post(
        "/books",
        response_model=BookOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_book(
        body: BookIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> BookOut:
        try:
            volumes = tuple(_deser_style_volume(sv.model_dump()) for sv in body.style_volumes)
            world_style = _world_style_in_to_dc(body.world_style)
            # In-memory store has create_book; same on PostgresAssetStore.
            book = await _create_book_via(
                store,
                book_id=body.book_id,
                title=body.title,
                world_style=world_style,
                style_volumes=volumes,
                profile_id=body.profile_id,
                org_id=body.org_id,
            )
            return _book_to_out(book)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/books/{book_id}", response_model=BookOut)
    async def get_book(
        book_id: str = Path(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> BookOut:
        book = await store.get_book(book_id)
        if book is None:
            raise HTTPException(404, {"detail": f"Book {book_id!r} not found"})
        return _book_to_out(book)

    @router.put("/books/{book_id}", response_model=BookOut)
    async def update_book(
        book_id: str = Path(...),
        body: BookIn = Body(...),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> BookOut:
        if book_id != body.book_id:
            raise HTTPException(409, {"detail": "book_id in path and body do not match"})
        try:
            volumes = tuple(_deser_style_volume(sv.model_dump()) for sv in body.style_volumes)
            book = Book(
                book_id=body.book_id,
                title=body.title,
                world_style=_world_style_in_to_dc(body.world_style),
                style_volumes=volumes,
                profile_id=body.profile_id,
                org_id=body.org_id,
            )
            saved = await store.update_book(book)
            return _book_to_out(saved)
        except Exception as exc:
            raise _http_error(exc) from exc

    # ── Render plan ─────────────────────────────────────────────────

    @router.post("/canvases/{canvas_id}/plan", response_model=RenderPlanModel)
    async def render_plan(
        canvas_id: str = Path(...),
        body: PlanRequest = Body(default_factory=PlanRequest),
        store: AssetStore = Depends(store_dep),
        auth: CurrentUser = Depends(get_current_user),
    ) -> RenderPlanModel:
        try:
            instances = await store.list_instances(canvas_id)
            world_style: WorldStyle | None = None
            volumes: tuple[StyleVolume, ...] = ()
            profile: ChildProfile | None = None

            if body.book_id is not None:
                book = await store.get_book(body.book_id)
                if book is None:
                    raise HTTPException(404, {"detail": f"Book {body.book_id!r} not found"})
                world_style = book.world_style
                volumes = book.style_volumes
                if profile is None and book.profile_id is not None:
                    profile = await store.get_profile(book.profile_id)

            if body.world_style is not None:
                world_style = _world_style_in_to_dc(body.world_style)
            if body.style_volumes is not None:
                volumes = tuple(_deser_style_volume(sv.model_dump()) for sv in body.style_volumes)
            if body.profile_id is not None:
                profile = await store.get_profile(body.profile_id)

            if world_style is None:
                raise HTTPException(
                    400,
                    {
                        "detail": "world_style is required: provide it in the body, "
                        "or pass a book_id whose row carries one.",
                    },
                )

            render_style = (
                _deser_render_style(body.render_style.model_dump())
                if body.render_style is not None
                else None
            )

            async def _registry_lookup(
                asset_id: str,
            ) -> AssetDefinition | None:
                return await store.get_definition(asset_id)

            # plan_render expects a sync callable; wrap by pre-fetching
            # all referenced definitions. For most pages this is small.
            referenced_ids = {i.definition for i in instances if isinstance(i.definition, str)}
            preloaded: dict[str, AssetDefinition | None] = {}
            for aid in referenced_ids:
                preloaded[aid] = await store.get_definition(aid)

            def lookup(asset_id: str) -> AssetDefinition | None:
                return preloaded.get(asset_id)

            plan = plan_render(
                canvas_id=canvas_id,
                instances=instances,
                world_style=world_style,
                style_volumes=volumes,
                page_index=body.page_index,
                render_style=render_style,
                profile=profile,
                registry_lookup=lookup,
            )
            return _plan_to_model(plan)
        except HTTPException:
            raise
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


async def _create_book_via(
    store: AssetStore,
    *,
    book_id: str,
    title: str,
    world_style: WorldStyle,
    style_volumes: tuple[StyleVolume, ...],
    profile_id: str | None,
    org_id: str,
) -> Book:
    """Helper that calls create_book regardless of the store flavour."""
    if isinstance(store, InMemoryAssetStore):
        return await store.create_book(
            book_id=book_id,
            title=title,
            world_style=world_style,
            style_volumes=style_volumes,
            profile_id=profile_id,
            org_id=org_id,
        )
    # PostgresAssetStore exposes the same signature.
    book: Book = await store.create_book(  # type: ignore[attr-defined]
        book_id=book_id,
        title=title,
        world_style=world_style,
        style_volumes=style_volumes,
        profile_id=profile_id,
        org_id=org_id,
    )
    return book


__all__ = [
    "AssetDefinitionIn",
    "AssetDefinitionOut",
    "AssetInstanceIn",
    "AssetInstanceOut",
    "AssetSheetIn",
    "AssetSheetOut",
    "BookIn",
    "BookOut",
    "ChildProfileIn",
    "ChildProfileOut",
    "PlanRequest",
    "PlannedRenderModel",
    "RenderPlanModel",
    "TransformModel",
    "WorldStyleModel",
    "make_router",
]

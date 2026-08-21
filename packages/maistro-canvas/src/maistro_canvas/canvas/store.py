"""PostgreSQL persistence for Canvas Studio (spec 1189).

All queries use raw SQL via sqlalchemy text() — same pattern as
pg_agents.py.  Z-index invariants are enforced inside transactions to
prevent races; the DB schema uses a UNIQUE constraint on
(canvas_id, z_index) as the authoritative guard.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from maistro_canvas.types import (
    _MAX_LAYERS,
    CanvasNotFoundError,
    CanvasRecord,
    CompositeResult,
    DuplicateZIndexError,
    GenerationJobRecord,
    IncompleteReorderError,
    LayerLimitExceededError,
    LayerNotFoundError,
    LayerRecord,
    TextConfig,
)

_MAX_LAYERS_CONST = _MAX_LAYERS


# ─────────────────────────────────────────────────────────────────────
# Row coercion helpers
# ─────────────────────────────────────────────────────────────────────


def _coerce_canvas(row: Any) -> CanvasRecord:
    d = dict(row)
    return CanvasRecord(
        id=str(d["id"]),
        name=d["name"],
        width=int(d["width"]),
        height=int(d["height"]),
        background_color=d.get("background_color", "#FFFFFF"),
        org_id=d.get("org_id", ""),
        layer_count=int(d.get("layer_count", 0)),
        archived_at=d.get("archived_at"),
        created_at=d.get("created_at", datetime.now(UTC)),
        updated_at=d.get("updated_at", datetime.now(UTC)),
    )


def _coerce_layer(row: Any) -> LayerRecord:
    d = dict(row)
    tc_raw = d.get("text_config")
    text_config: TextConfig | None = None
    if tc_raw:
        if isinstance(tc_raw, str):
            tc_raw = json.loads(tc_raw)
        text_config = TextConfig(
            content=tc_raw.get("content", ""),
            font=tc_raw.get("font", "sans-serif"),
            size=int(tc_raw.get("size", 48)),
            color=tc_raw.get("color", "#FFFFFF"),
            weight=tc_raw.get("weight", "normal"),
            alignment=tc_raw.get("alignment", "center"),
            shadow_color=tc_raw.get("shadow_color"),
        )
    return LayerRecord(
        id=str(d["id"]),
        canvas_id=str(d["canvas_id"]),
        name=d["name"],
        layer_type=d.get("layer_type", "background"),
        z_index=int(d.get("z_index", 0)),
        x=float(d.get("x", 0.0)),
        y=float(d.get("y", 0.0)),
        scale=float(d.get("scale", 1.0)),
        rotation=float(d.get("rotation", 0.0)),
        opacity=float(d.get("opacity", 1.0)),
        blend_mode=d.get("blend_mode", "normal"),
        visible=bool(d.get("visible", True)),
        locked=bool(d.get("locked", False)),
        image_path=d.get("image_path"),
        prompt=d.get("prompt"),
        negative_prompt=d.get("negative_prompt"),
        model_id=d.get("model_id"),
        tier=d.get("tier", "draft"),
        generation_seed=d.get("generation_seed"),
        text_config=text_config,
        created_at=d.get("created_at", datetime.now(UTC)),
        updated_at=d.get("updated_at", datetime.now(UTC)),
    )


def _coerce_job(row: Any) -> GenerationJobRecord:
    d = dict(row)
    result_paths_raw = d.get("result_paths", [])
    if isinstance(result_paths_raw, str):
        result_paths_raw = json.loads(result_paths_raw)
    params_raw = d.get("params", {})
    if isinstance(params_raw, str):
        params_raw = json.loads(params_raw)
    return GenerationJobRecord(
        id=str(d["id"]),
        layer_id=str(d["layer_id"]),
        canvas_id=str(d["canvas_id"]),
        action=d.get("action", "generate"),
        status=d.get("status", "pending"),
        model_id=d.get("model_id", ""),
        prompt=d.get("prompt", ""),
        params=params_raw or {},
        result_paths=result_paths_raw or [],
        selected_index=d.get("selected_index"),
        error_message=d.get("error_message"),
        started_at=d.get("started_at"),
        completed_at=d.get("completed_at"),
        created_at=d.get("created_at", datetime.now(UTC)),
    )


def _coerce_composite(row: Any) -> CompositeResult:
    d = dict(row)
    snapshot_raw = d.get("layer_snapshot", [])
    if isinstance(snapshot_raw, str):
        snapshot_raw = json.loads(snapshot_raw)
    return CompositeResult(
        canvas_id=str(d["canvas_id"]),
        image_bytes=bytes(d.get("image_bytes", b"")),
        width=int(d.get("width", 0)),
        height=int(d.get("height", 0)),
        layer_snapshot=snapshot_raw or [],
        created_at=d.get("created_at", datetime.now(UTC)),
    )


# ─────────────────────────────────────────────────────────────────────
# PgCanvasStore
# ─────────────────────────────────────────────────────────────────────


class PgCanvasStore:
    """Canvas Studio persistence layer using async PostgreSQL."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    # ── Canvases ──────────────────────────────────────────────────────

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord:
        canvas_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    INSERT INTO canvases
                        (id, name, width, height, background_color, org_id,
                         layer_count, created_at, updated_at)
                    VALUES
                        (:id, :name, :width, :height, :bg, :org,
                         0, :now, :now)
                """),
                {
                    "id": canvas_id,
                    "name": name,
                    "width": width,
                    "height": height,
                    "bg": background_color,
                    "org": org_id,
                    "now": now,
                },
            )
            await session.commit()
        record = CanvasRecord(
            id=canvas_id,
            name=name,
            width=width,
            height=height,
            background_color=background_color,
            org_id=org_id,
            layer_count=0,
            created_at=now,
            updated_at=now,
        )
        return record

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM canvases WHERE id = :id"),
                {"id": canvas_id},
            )
            row = result.mappings().first()
            return _coerce_canvas(row) if row else None

    async def list_canvases(
        self,
        org_id: str,
        *,
        include_archived: bool = False,
    ) -> list[CanvasRecord]:
        async with AsyncSession(self._engine) as session:
            if include_archived:
                result = await session.execute(
                    text("SELECT * FROM canvases WHERE org_id = :org ORDER BY updated_at DESC"),
                    {"org": org_id},
                )
            else:
                result = await session.execute(
                    text(
                        "SELECT * FROM canvases"
                        " WHERE org_id = :org AND archived_at IS NULL"
                        " ORDER BY updated_at DESC"
                    ),
                    {"org": org_id},
                )
            rows = result.mappings().all()
            return [_coerce_canvas(r) for r in rows]

    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord:
        canvas.updated_at = datetime.now(UTC)
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    UPDATE canvases SET
                        name = :name, background_color = :bg,
                        layer_count = :lc, archived_at = :archived,
                        updated_at = :updated
                    WHERE id = :id
                """),
                {
                    "id": canvas.id,
                    "name": canvas.name,
                    "bg": canvas.background_color,
                    "lc": canvas.layer_count,
                    "archived": canvas.archived_at,
                    "updated": canvas.updated_at,
                },
            )
            await session.commit()
        return canvas

    # ── Layers ────────────────────────────────────────────────────────

    async def add_layer(
        self,
        canvas_id: str,
        *,
        name: str,
        layer_type: str,
        z_index: int | None = None,
        **kwargs: Any,
    ) -> LayerRecord:
        async with AsyncSession(self._engine) as session:
            # Check ceiling
            cnt_result = await session.execute(
                text("SELECT layer_count FROM canvases WHERE id = :id FOR UPDATE"),
                {"id": canvas_id},
            )
            cnt_row = cnt_result.mappings().first()
            if cnt_row is None:
                raise CanvasNotFoundError(canvas_id)
            layer_count = int(cnt_row["layer_count"])
            if layer_count >= _MAX_LAYERS_CONST:
                raise LayerLimitExceededError(
                    f"canvas {canvas_id!r} already has {layer_count} "
                    f"layers (max {_MAX_LAYERS_CONST})"
                )

            # Auto z_index
            if z_index is None:
                z_result = await session.execute(
                    text(
                        "SELECT COALESCE(MAX(z_index), -1) AS max_z "
                        "FROM layers WHERE canvas_id = :cid"
                    ),
                    {"cid": canvas_id},
                )
                z_row = z_result.mappings().first()
                z_index = int(z_row["max_z"]) + 1 if z_row else 0

            layer_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            tc_json = json.dumps(None)
            text_config_obj: TextConfig | None = kwargs.get("text_config")
            if text_config_obj is not None:
                tc_json = json.dumps(
                    {
                        "content": text_config_obj.content,
                        "font": text_config_obj.font,
                        "size": text_config_obj.size,
                        "color": text_config_obj.color,
                        "weight": text_config_obj.weight,
                        "alignment": text_config_obj.alignment,
                        "shadow_color": text_config_obj.shadow_color,
                    }
                )

            await session.execute(
                text("""
                    INSERT INTO layers
                        (id, canvas_id, name, layer_type, z_index, x, y, scale,
                         rotation, opacity, blend_mode, visible, locked,
                         image_path, prompt, negative_prompt, model_id, tier,
                         generation_seed, text_config, created_at, updated_at)
                    VALUES
                        (:id, :cid, :name, :lt, :z, :x, :y, :sc,
                         :rot, :op, :bm, :vis, :lk,
                         :ip, :pr, :np, :mi, :ti,
                         :gs, :tc::jsonb, :now, :now)
                """),
                {
                    "id": layer_id,
                    "cid": canvas_id,
                    "name": name,
                    "lt": layer_type,
                    "z": z_index,
                    "x": kwargs.get("x", 0.0),
                    "y": kwargs.get("y", 0.0),
                    "sc": kwargs.get("scale", 1.0),
                    "rot": kwargs.get("rotation", 0.0),
                    "op": kwargs.get("opacity", 1.0),
                    "bm": kwargs.get("blend_mode", "normal"),
                    "vis": kwargs.get("visible", True),
                    "lk": kwargs.get("locked", False),
                    "ip": kwargs.get("image_path"),
                    "pr": kwargs.get("prompt"),
                    "np": kwargs.get("negative_prompt"),
                    "mi": kwargs.get("model_id"),
                    "ti": kwargs.get("tier", "draft"),
                    "gs": kwargs.get("generation_seed"),
                    "tc": tc_json,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "UPDATE canvases "
                    "SET layer_count = layer_count + 1, "
                    "updated_at = :now WHERE id = :id"
                ),
                {"now": now, "id": canvas_id},
            )
            await session.commit()

        return LayerRecord(
            id=layer_id,
            canvas_id=canvas_id,
            name=name,
            layer_type=layer_type,
            z_index=z_index,
            x=kwargs.get("x", 0.0),
            y=kwargs.get("y", 0.0),
            scale=kwargs.get("scale", 1.0),
            rotation=kwargs.get("rotation", 0.0),
            opacity=kwargs.get("opacity", 1.0),
            blend_mode=kwargs.get("blend_mode", "normal"),
            visible=kwargs.get("visible", True),
            locked=kwargs.get("locked", False),
            image_path=kwargs.get("image_path"),
            prompt=kwargs.get("prompt"),
            negative_prompt=kwargs.get("negative_prompt"),
            model_id=kwargs.get("model_id"),
            tier=kwargs.get("tier", "draft"),
            generation_seed=kwargs.get("generation_seed"),
            text_config=text_config_obj,
            created_at=now,
            updated_at=now,
        )

    async def get_layer(self, layer_id: str) -> LayerRecord | None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM layers WHERE id = :id"),
                {"id": layer_id},
            )
            row = result.mappings().first()
            return _coerce_layer(row) if row else None

    async def list_layers(self, canvas_id: str) -> list[LayerRecord]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM layers WHERE canvas_id = :cid ORDER BY z_index ASC"),
                {"cid": canvas_id},
            )
            rows = result.mappings().all()
            return [_coerce_layer(r) for r in rows]

    async def update_layer(self, layer: LayerRecord) -> LayerRecord:
        layer.updated_at = datetime.now(UTC)
        tc_json = json.dumps(None)
        if layer.text_config is not None:
            tc_json = json.dumps(
                {
                    "content": layer.text_config.content,
                    "font": layer.text_config.font,
                    "size": layer.text_config.size,
                    "color": layer.text_config.color,
                    "weight": layer.text_config.weight,
                    "alignment": layer.text_config.alignment,
                    "shadow_color": layer.text_config.shadow_color,
                }
            )
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    UPDATE layers SET
                        name = :name, z_index = :z, x = :x, y = :y, scale = :sc,
                        rotation = :rot, opacity = :op, blend_mode = :bm,
                        visible = :vis, locked = :lk, image_path = :ip,
                        prompt = :pr, negative_prompt = :np, model_id = :mi,
                        tier = :ti, generation_seed = :gs,
                        text_config = :tc::jsonb, updated_at = :updated
                    WHERE id = :id
                """),
                {
                    "id": layer.id,
                    "name": layer.name,
                    "z": layer.z_index,
                    "x": layer.x,
                    "y": layer.y,
                    "sc": layer.scale,
                    "rot": layer.rotation,
                    "op": layer.opacity,
                    "bm": layer.blend_mode,
                    "vis": layer.visible,
                    "lk": layer.locked,
                    "ip": layer.image_path,
                    "pr": layer.prompt,
                    "np": layer.negative_prompt,
                    "mi": layer.model_id,
                    "ti": layer.tier,
                    "gs": layer.generation_seed,
                    "tc": tc_json,
                    "updated": layer.updated_at,
                },
            )
            await session.commit()
        return layer

    async def remove_layer(self, layer_id: str) -> None:
        """Remove a layer and re-pack z_indices of higher layers (dense invariant)."""
        async with AsyncSession(self._engine) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT canvas_id, z_index FROM layers WHERE id = :id FOR UPDATE"),
                        {"id": layer_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LayerNotFoundError(layer_id)
            canvas_id = str(row["canvas_id"])
            removed_z = int(row["z_index"])

            await session.execute(text("DELETE FROM layers WHERE id = :id"), {"id": layer_id})
            # Re-pack: decrement z_index for all layers above the removed one
            await session.execute(
                text("""
                    UPDATE layers SET z_index = z_index - 1
                    WHERE canvas_id = :cid AND z_index > :z
                """),
                {"cid": canvas_id, "z": removed_z},
            )
            now = datetime.now(UTC)
            await session.execute(
                text(
                    "UPDATE canvases SET layer_count = layer_count - 1, updated_at = :now"
                    " WHERE id = :id"
                ),
                {"now": now, "id": canvas_id},
            )
            await session.commit()

    async def reorder_layers(
        self,
        canvas_id: str,
        assignments: list[dict[str, Any]],
    ) -> list[LayerRecord]:
        """Atomically reassign z_indices.  Validates completeness and uniqueness."""
        # Validate no duplicate z_index values
        z_values = [a["z_index"] for a in assignments]
        if len(z_values) != len(set(z_values)):
            raise DuplicateZIndexError("duplicate z_index values in reorder request")

        # Validate completeness
        async with AsyncSession(self._engine) as session:
            existing = (
                (
                    await session.execute(
                        text("SELECT id FROM layers WHERE canvas_id = :cid"), {"cid": canvas_id}
                    )
                )
                .scalars()
                .all()
            )
            existing_ids = {str(eid) for eid in existing}
            request_ids = {str(a["layer_id"]) for a in assignments}
            if existing_ids != request_ids:
                raise IncompleteReorderError(
                    f"reorder covers {len(request_ids)} layers but canvas has {len(existing_ids)}"
                )

            # Apply assignments
            for assignment in assignments:
                await session.execute(
                    text("UPDATE layers SET z_index = :z WHERE id = :id AND canvas_id = :cid"),
                    {
                        "z": assignment["z_index"],
                        "id": str(assignment["layer_id"]),
                        "cid": canvas_id,
                    },
                )
            await session.commit()

        return await self.list_layers(canvas_id)

    # ── Generation jobs ───────────────────────────────────────────────

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    INSERT INTO generation_jobs
                        (id, layer_id, canvas_id, action, status, model_id,
                         prompt, params, result_paths, selected_index,
                         error_message, started_at, completed_at, created_at)
                    VALUES
                        (:id, :lid, :cid, :action, :status, :model,
                         :prompt, :params::jsonb, :paths::jsonb, :sel,
                         :err, :start, :done, :created)
                """),
                {
                    "id": job.id,
                    "lid": job.layer_id,
                    "cid": job.canvas_id,
                    "action": job.action,
                    "status": job.status,
                    "model": job.model_id,
                    "prompt": job.prompt,
                    "params": json.dumps(job.params),
                    "paths": json.dumps(job.result_paths),
                    "sel": job.selected_index,
                    "err": job.error_message,
                    "start": job.started_at,
                    "done": job.completed_at,
                    "created": job.created_at,
                },
            )
            await session.commit()
        return job

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM generation_jobs WHERE id = :id"),
                {"id": job_id},
            )
            row = result.mappings().first()
            return _coerce_job(row) if row else None

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    UPDATE generation_jobs SET
                        status = :status, result_paths = :paths::jsonb,
                        selected_index = :sel, error_message = :err,
                        started_at = :start, completed_at = :done
                    WHERE id = :id
                """),
                {
                    "id": job.id,
                    "status": job.status,
                    "paths": json.dumps(job.result_paths),
                    "sel": job.selected_index,
                    "err": job.error_message,
                    "start": job.started_at,
                    "done": job.completed_at,
                },
            )
            await session.commit()
        return job

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("""
                    SELECT * FROM generation_jobs
                    WHERE layer_id = :lid AND status IN ('pending', 'running')
                    LIMIT 1
                """),
                {"lid": layer_id},
            )
            row = result.mappings().first()
            return _coerce_job(row) if row else None

    async def list_jobs_for_layer(self, layer_id: str) -> list[GenerationJobRecord]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text(
                    "SELECT * FROM generation_jobs WHERE layer_id = :lid ORDER BY created_at DESC"
                ),
                {"lid": layer_id},
            )
            rows = result.mappings().all()
            return [_coerce_job(r) for r in rows]

    # ── Composites ────────────────────────────────────────────────────

    async def save_composite(self, result: CompositeResult) -> CompositeResult:
        composite_id = str(uuid.uuid4())
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    INSERT INTO composite_records
                        (id, canvas_id, image_bytes, width, height,
                         layer_snapshot, created_at)
                    VALUES
                        (:id, :cid, :img, :w, :h, :snap::jsonb, :now)
                """),
                {
                    "id": composite_id,
                    "cid": result.canvas_id,
                    "img": result.image_bytes,
                    "w": result.width,
                    "h": result.height,
                    "snap": json.dumps(result.layer_snapshot),
                    "now": result.created_at,
                },
            )
            await session.commit()
        return result

    async def latest_composite(self, canvas_id: str) -> CompositeResult | None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("""
                    SELECT * FROM composite_records
                    WHERE canvas_id = :cid
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"cid": canvas_id},
            )
            row = result.mappings().first()
            return _coerce_composite(row) if row else None

    # ── Blobs ─────────────────────────────────────────────────────────

    async def store_blob(
        self,
        data: bytes,
        *,
        format: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        blob_id = str(uuid.uuid4())
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    INSERT INTO canvas_blobs
                        (id, data, format, metadata, created_at)
                    VALUES
                        (:id, :data, :format, :metadata::jsonb, :now)
                """),
                {
                    "id": blob_id,
                    "data": data,
                    "format": format,
                    "metadata": json.dumps(metadata or {}),
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()
        return blob_id

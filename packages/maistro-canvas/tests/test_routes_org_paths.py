"""Mainline route coverage for the org-scoped canvas v1 API (#857, #816).

``test_routes_auth.py`` proves authentication reaches the handlers; the
org-scope lane (#857) then rewired nearly every handler body to thread
``org_id`` through the store, which left those bodies uncovered. This
module drives each mainline body (and the on-demand export branch) with
an org-scoped fake store so the changed lines execute for real:

    update/archive canvas, update/delete/reorder layers, layer jobs,
    job cancel/accept, composite save/latest, and the export path that
    composites on demand when nothing is stored.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro_canvas.canvas.routes import make_canvas_router
from maistro_canvas.types import (
    CanvasRecord,
    CompositeResult,
    GenerationJobRecord,
    JobStatus,
    LayerRecord,
)

TEST_TOKEN = "test-canvas-token"
ORG = "default"  # CurrentUser().org_id default for the standalone deployment


class _OrgStore:
    """In-memory CanvasStore stub scoped by org, mirroring the real guard."""

    def __init__(self) -> None:
        self._canvases: dict[str, CanvasRecord] = {}
        self._layers: dict[str, LayerRecord] = {}
        self._jobs: dict[str, GenerationJobRecord] = {}
        self._composites: dict[str, CompositeResult] = {}
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord:
        cid = self._next("canvas")
        rec = CanvasRecord(id=cid, name=name, width=width, height=height, org_id=org_id)
        self._canvases[cid] = rec
        return rec

    async def get_canvas(self, canvas_id: str, *, org_id: str = "") -> CanvasRecord | None:
        rec = self._canvases.get(canvas_id)
        if rec is None or rec.org_id != org_id:
            return None
        return rec

    async def update_canvas(self, canvas: CanvasRecord, *, org_id: str = "") -> CanvasRecord:
        canvas.updated_at = datetime.now(UTC)
        self._canvases[canvas.id] = canvas
        return canvas

    async def add_layer(
        self, canvas_id: str, *, org_id: str = "", name: str = "Layer", **kw: Any
    ) -> LayerRecord:
        lid = self._next("layer")
        layer = LayerRecord(id=lid, canvas_id=canvas_id, name=name)
        self._layers[lid] = layer
        return layer

    async def get_layer(self, layer_id: str, *, org_id: str = "") -> LayerRecord | None:
        layer = self._layers.get(layer_id)
        if layer is None:
            return None
        canvas = self._canvases.get(layer.canvas_id)
        if canvas is None or canvas.org_id != org_id:
            return None
        return layer

    async def list_layers(self, canvas_id: str, *, org_id: str = "") -> list[LayerRecord]:
        return [lyr for lyr in self._layers.values() if lyr.canvas_id == canvas_id]

    async def update_layer(self, layer: LayerRecord, *, org_id: str = "") -> LayerRecord:
        layer.updated_at = datetime.now(UTC)
        self._layers[layer.id] = layer
        return layer

    async def remove_layer(self, layer_id: str, *, org_id: str = "") -> None:
        self._layers.pop(layer_id, None)

    async def reorder_layers(
        self, canvas_id: str, assignments: list[dict[str, Any]], *, org_id: str = ""
    ) -> list[LayerRecord]:
        for a in assignments:
            lyr = self._layers.get(str(a.get("id", "")))
            if lyr is not None and "z_index" in a:
                lyr.z_index = int(a["z_index"])
        return [lyr for lyr in self._layers.values() if lyr.canvas_id == canvas_id]

    async def active_job_for_layer(
        self, layer_id: str, *, org_id: str = ""
    ) -> GenerationJobRecord | None:
        for job in self._jobs.values():
            if job.layer_id == layer_id and job.is_active():
                return job
        return None

    async def get_job(self, job_id: str, *, org_id: str = "") -> GenerationJobRecord | None:
        job = self._jobs.get(job_id)
        if job is None or job.org_id != org_id:
            return None
        return job

    async def list_jobs_for_layer(
        self, layer_id: str, *, org_id: str = ""
    ) -> list[GenerationJobRecord]:
        return [j for j in self._jobs.values() if j.layer_id == layer_id]

    async def save_composite(self, comp: CompositeResult, *, org_id: str = "") -> CompositeResult:
        self._composites[comp.canvas_id] = comp
        return comp

    async def latest_composite(self, canvas_id: str, *, org_id: str = "") -> CompositeResult | None:
        return self._composites.get(canvas_id)


class _OrgExecutor:
    def __init__(self, store: _OrgStore) -> None:
        self._store = store
        self.cancel_raises = False

    async def start_job(
        self, *, canvas_id: str, layer_id: str, org_id: str = "", **kw: Any
    ) -> GenerationJobRecord:
        job = GenerationJobRecord(
            id=f"job-{len(self._store._jobs) + 1}",
            layer_id=layer_id,
            canvas_id=canvas_id,
            status=JobStatus.RUNNING,
            org_id=org_id,
        )
        self._store._jobs[job.id] = job
        return job

    async def cancel_job(self, job_id: str, *, org_id: str = "") -> GenerationJobRecord:
        if self.cancel_raises:
            raise RuntimeError("cancel backend unavailable")
        job = self._store._jobs[job_id]
        job.status = JobStatus.CANCELLED
        return job

    async def accept_variant(
        self, job_id: str, variant_index: int, *, org_id: str = ""
    ) -> tuple[GenerationJobRecord, LayerRecord]:
        job = self._store._jobs[job_id]
        job.status = JobStatus.DONE
        job.selected_index = variant_index
        layer = next(lyr for lyr in self._store._layers.values() if lyr.id == job.layer_id)
        layer.image_path = f"/accepted/{variant_index}.png"
        return job, layer


class _OrgCompositor:
    def __init__(self) -> None:
        self.calls = 0

    async def composite(self, canvas: CanvasRecord, layers: list[LayerRecord]) -> CompositeResult:
        self.calls += 1
        return CompositeResult(
            canvas_id=canvas.id,
            image_bytes=b"\x89PNG-fake",
            width=canvas.width,
            height=canvas.height,
            layer_snapshot=[lyr.id for lyr in layers],
        )


class _Harness:
    def __init__(self) -> None:
        self.store = _OrgStore()
        self.executor = _OrgExecutor(self.store)
        self.compositor = _OrgCompositor()

    def app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(
            make_canvas_router(
                store=self.store,  # type: ignore[arg-type]
                executor=self.executor,  # type: ignore[arg-type]
                compositor=self.compositor,  # type: ignore[arg-type]
            ),
            prefix="/api/canvas",
        )
        return app

    async def seed_canvas(self, *, org: str = ORG) -> CanvasRecord:
        return await self.store.create_canvas(name="Seed", width=1024, height=1024, org_id=org)

    async def seed_layer(self, canvas: CanvasRecord) -> LayerRecord:
        return await self.store.add_layer(canvas.id, org_id=canvas.org_id, name="L1")

    async def seed_job(self, canvas: CanvasRecord) -> tuple[LayerRecord, GenerationJobRecord]:
        layer = await self.seed_layer(canvas)
        job = await self.executor.start_job(
            canvas_id=canvas.id, layer_id=layer.id, org_id=canvas.org_id
        )
        return layer, job


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, _Harness]]:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    h = _Harness()
    with TestClient(
        h.app(),
        raise_server_exceptions=True,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as c:
        yield c, h


async def test_get_canvas_returns_layers(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    await h.seed_layer(canvas)
    r = client.get(f"/api/canvas/{canvas.id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == canvas.id
    assert len(r.json()["layers"]) == 1


async def test_update_canvas_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    r = client.patch(f"/api/canvas/{canvas.id}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"


async def test_delete_canvas_archives_and_cancels_active_jobs(
    harness: tuple[TestClient, _Harness],
) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    _layer, _job = await h.seed_job(canvas)
    r = client.delete(f"/api/canvas/{canvas.id}")
    assert r.status_code == 200, r.text
    assert r.json()["archived"] is True
    job = next(iter(h.store._jobs.values()))
    assert job.status == JobStatus.CANCELLED


async def test_delete_canvas_survives_cancel_backend_failure(
    harness: tuple[TestClient, _Harness],
) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    await h.seed_job(canvas)
    h.executor.cancel_raises = True
    r = client.delete(f"/api/canvas/{canvas.id}")
    assert r.status_code == 200, r.text


async def test_update_layer_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    layer = await h.seed_layer(canvas)
    r = client.patch(f"/api/canvas/{canvas.id}/layers/{layer.id}", json={"name": "Renamed layer"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed layer"


async def test_delete_layer_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    layer = await h.seed_layer(canvas)
    r = client.delete(f"/api/canvas/{canvas.id}/layers/{layer.id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True


async def test_reorder_layers_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    layer = await h.seed_layer(canvas)
    r = client.post(
        f"/api/canvas/{canvas.id}/layers/reorder", json=[{"id": layer.id, "z_index": 3}]
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["z_index"] == 3


async def test_list_layer_jobs_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    _layer, _job = await h.seed_job(canvas)
    layer_id = next(iter(h.store._jobs.values())).layer_id
    r = client.get(f"/api/canvas/{canvas.id}/layers/{layer_id}/jobs")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_get_job_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    _layer, job = await h.seed_job(canvas)
    r = client.get(f"/api/canvas/jobs/{job.id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == job.id


async def test_cancel_job_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    _layer, job = await h.seed_job(canvas)
    r = client.delete(f"/api/canvas/jobs/{job.id}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == JobStatus.CANCELLED


async def test_accept_variant_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    _layer, job = await h.seed_job(canvas)
    r = client.post(f"/api/canvas/jobs/{job.id}/accept/0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["selected_index"] == 0
    assert body["layer"]["image_path"] == "/accepted/0.png"


async def test_composite_canvas_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    r = client.post(f"/api/canvas/{canvas.id}/composite")
    assert r.status_code == 200, r.text
    assert h.compositor.calls == 1
    assert r.json()["canvas_id"] == canvas.id


async def test_latest_composite_mainline(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    layers = await h.store.list_layers(canvas.id, org_id=canvas.org_id)
    comp = await h.compositor.composite(canvas, layers)
    await h.store.save_composite(comp, org_id=canvas.org_id)
    r = client.get(f"/api/canvas/{canvas.id}/composite/latest")
    assert r.status_code == 200, r.text
    assert r.json()["canvas_id"] == canvas.id


async def test_latest_composite_without_any_is_404(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    r = client.get(f"/api/canvas/{canvas.id}/composite/latest")
    assert r.status_code == 404, r.text


async def test_export_composites_on_demand_when_nothing_stored(
    harness: tuple[TestClient, _Harness],
) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    r = client.get(f"/api/canvas/{canvas.id}/export")
    assert r.status_code == 200, r.text
    assert h.compositor.calls == 1, "export must composite on demand when nothing is stored"
    assert r.headers["content-type"].startswith("image/png")
    assert "attachment" in r.headers["content-disposition"]


async def test_export_of_archived_canvas_is_404(harness: tuple[TestClient, _Harness]) -> None:
    client, h = harness
    canvas = await h.seed_canvas()
    canvas.archived_at = datetime.now(UTC)
    await h.store.update_canvas(canvas, org_id=canvas.org_id)
    r = client.get(f"/api/canvas/{canvas.id}/export")
    assert r.status_code == 404, r.text

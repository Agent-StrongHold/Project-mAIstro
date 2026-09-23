"""Route-boundary coverage for Canvas generation idempotency (#1055 review).

Two gaps Codex flagged in PR #1531 live at the HTTP boundary, below the
`CanvasExecutor`/`CanvasCanonicalExecution` unit coverage in
``test_canonical_execution.py`` and ``test_canonical_executor_integration.py``:

- An explicit ``"idempotency_key": null`` in the JSON body must not suppress
  a valid ``Idempotency-Key`` header (finding 7).
- A conflicting retry that reaches ``admit()`` and raises the core
  ``RunIntegrityError`` must become a deterministic 409, not fall through to
  the global exception handler as a 500 (finding 8).

Both need a real request/response round trip through ``start_generate`` --
not just the executor called directly -- so this drives the actual route with
a real ``CanvasExecutor`` bound to a real ``CanvasCanonicalExecution`` over an
``InMemoryRunStore``, the same composition production uses.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.canvas.routes import _make_canvas_router
from maistro_canvas.protocols import ImageData
from maistro_canvas.types import CanvasRecord, GenerationJobRecord, JobStatus, LayerRecord

pytestmark = pytest.mark.asyncio

TEST_TOKEN = "test-canvas-token"
ORG = "default"  # CurrentUser().org_id default for the standalone deployment


class _Store:
    def __init__(self) -> None:
        self.canvas = CanvasRecord(id="canvas-1", name="Canvas", width=64, height=64, org_id=ORG)
        self.layer = LayerRecord(id="layer-1", canvas_id=self.canvas.id, name="Background")
        self.jobs: dict[str, GenerationJobRecord] = {}

    async def get_canvas(self, canvas_id: str, *, org_id: str = "") -> CanvasRecord | None:
        return self.canvas if canvas_id == self.canvas.id and org_id == ORG else None

    async def get_layer(self, layer_id: str, *, org_id: str = "") -> LayerRecord | None:
        return self.layer if layer_id == self.layer.id and org_id == ORG else None

    async def active_job_for_layer(
        self, layer_id: str, *, org_id: str = ""
    ) -> GenerationJobRecord | None:
        return next(
            (
                job
                for job in self.jobs.values()
                if job.layer_id == layer_id and job.status in {JobStatus.PENDING, JobStatus.RUNNING}
            ),
            None,
        )

    async def create_job(
        self, job: GenerationJobRecord, *, org_id: str = ""
    ) -> GenerationJobRecord:
        self.jobs[job.id] = job
        return job

    async def get_job(self, job_id: str, *, org_id: str = "") -> GenerationJobRecord | None:
        return self.jobs.get(job_id)

    async def update_job(
        self, job: GenerationJobRecord, *, org_id: str = ""
    ) -> GenerationJobRecord:
        self.jobs[job.id] = job
        return job


class _Registry:
    def is_registered(self, model_id: str) -> bool:
        return model_id == "draft-model"

    def get_default_draft(self) -> str:
        return "draft-model"


class _Warden:
    async def scan_prompt(self, _prompt: str) -> str:
        return "ALLOW"


class _ImageClient:
    async def generate(self, **_kwargs: object) -> list[ImageData]:
        return [ImageData(width=64, height=64, url="image://generated")]

    async def refine(self, **_kwargs: object) -> ImageData:
        return ImageData(width=64, height=64, url="image://refined")


class _Harness:
    """Real executor/canonical-execution/RunStore, wired the way production is."""

    def __init__(self) -> None:
        self.store = _Store()

    async def build(self) -> FastAPI:
        projects = InMemoryProjectScopeStore()
        root = await projects.create_root("workspace-1")
        runs = InMemoryRunStore(project_store=projects)
        canonical = CanvasCanonicalExecution(
            runs, workspace_id="workspace-1", project_id=root.project_id
        )
        executor = CanvasExecutor(
            store=self.store,  # type: ignore[arg-type]
            image_client=_ImageClient(),  # type: ignore[arg-type]
            model_registry=_Registry(),
            warden=_Warden(),
            canonical_execution=canonical,
        )
        app = FastAPI()
        app.include_router(
            _make_canvas_router(
                store=self.store,  # type: ignore[arg-type]
                executor=executor,
                compositor=object(),  # type: ignore[arg-type]
            ),
            prefix="/api/canvas",
        )
        return app


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, _Harness]]:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    h = _Harness()
    app = await h.build()
    with TestClient(
        app,
        raise_server_exceptions=True,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as c:
        yield c, h


async def test_explicit_null_body_key_falls_back_to_the_header(
    harness: tuple[TestClient, _Harness],
) -> None:
    """A generated client's ``"idempotency_key": null`` must not drop the header.

    ``dict.get("idempotency_key", header)`` only falls back to its default
    when the key is *absent*; an explicit ``null`` supplies the key with
    value ``None`` and, before the fix, silently admitted the request with no
    operation identity at all. Proven the same way the executor-level tests
    prove idempotency: two requests that should be one operation must return
    the same job id.
    """
    client, _harness = harness
    body = {"prompt": "safe", "idempotency_key": None}
    headers = {"Idempotency-Key": "generation-null-body"}

    first = client.post("/api/canvas/canvas-1/layers/layer-1/generate", json=body, headers=headers)
    assert first.status_code == 202, first.text
    second = client.post("/api/canvas/canvas-1/layers/layer-1/generate", json=body, headers=headers)
    assert second.status_code == 202, second.text

    assert first.json()["job_id"] == second.json()["job_id"]


async def test_conflicting_header_and_body_keys_is_422(
    harness: tuple[TestClient, _Harness],
) -> None:
    """Header and body naming *different* non-null keys is a genuine conflict."""
    client, _harness = harness

    response = client.post(
        "/api/canvas/canvas-1/layers/layer-1/generate",
        json={"prompt": "safe", "idempotency_key": "body-key"},
        headers={"Idempotency-Key": "header-key"},
    )

    assert response.status_code == 422, response.text


async def test_conflicting_retry_after_terminal_is_409_not_500(
    harness: tuple[TestClient, _Harness],
) -> None:
    """Once the earlier operation is no longer active, a changed-payload retry
    of the same key is a deterministic 409, not a 500 from the global handler.

    `admit()` raises the core `RunIntegrityError` for this case, which is not
    one of the Canvas domain errors `_error()`/`_ERROR_STATUS_MAP` translate;
    without the route boundary catching it explicitly, this fell through to
    the global exception handler.
    """
    client, harness_obj = harness
    headers = {"Idempotency-Key": "generation-conflict"}

    first = client.post(
        "/api/canvas/canvas-1/layers/layer-1/generate",
        json={"prompt": "a safe landscape"},
        headers=headers,
    )
    assert first.status_code == 202, first.text
    job_id = first.json()["job_id"]
    # Retire the receipt so the retry reaches admission instead of the
    # still-active in-flight check -- the scenario the finding names.
    harness_obj.store.jobs[job_id].status = JobStatus.DONE

    conflicting = client.post(
        "/api/canvas/canvas-1/layers/layer-1/generate",
        json={"prompt": "a completely different landscape"},
        headers=headers,
    )

    assert conflicting.status_code == 409, conflicting.text

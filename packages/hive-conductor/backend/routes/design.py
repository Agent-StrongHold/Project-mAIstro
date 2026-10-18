"""Design skill routes — project preparation, discovery, artifact retrieval.

POST /design/projects — prepare and persist a design project/prompt stack
GET /design/projects/{id} — fetch project + outputs
GET /design/projects — list org projects
GET /design/skills — list available skills
GET /design/skills/{slug}/discovery — get skill discovery form
GET /design/systems — list registered design systems + catalog state
GET /design/packs — list domain packs (one uniform selector listing; #793)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.design_service import (
    get_design_engine,
    get_design_status,
    get_design_store,
    get_renderer_registry,
)

from maistro_design.consistency import (
    CreativeProjectSnapshot,
    evaluate_project_snapshot,
)
from maistro_design.packs import PackRegistry
from maistro_design.systems.importer import ORIGIN_EXTERNAL
from maistro_design.types import (
    DesignError,
    DesignSystemNotFoundError,
    DiscoveryIncompleteError,
    DiscoveryResult,
    SkillNotFoundError,
)

router = APIRouter(prefix="/design", tags=["design"])


def _require_ready() -> Any:
    """The design service's startup outcome, or 503 with the cause it recorded.

    #293 gave startup an answerable status; #413 is that only one route asked.
    The rest called `get_design_engine()`, caught its generic
    `RuntimeError("DesignEngine not initialized ...")` in a blanket handler and
    returned 500 -- discarding the recorded cause and the service-unavailable
    semantics the status exists to express. A broken install answered "internal
    server error" on three routes out of four, which is the shape of #293 with
    a smaller blast radius.

    Called before the blanket `except Exception` in each route, so its
    HTTPException is raised rather than reclassified.
    """
    status = get_design_status()
    if not status.ready:
        raise HTTPException(
            status_code=503,
            detail=f"Design service unavailable: {status.cause or 'cause not recorded'}",
        )
    return status


#: The scope every Design Studio project in this deployment belongs to.
#:
#: The Agent Conductor is single-org by construction — one household, one
#: installation — so one deployment-wide scope is the truth here, and minting a
#: per-user org would be a tenancy model this repository has not decided (ADR-068
#: keeps `org` a soft axis and leaves hard tenancy to Stronghold). A deployment
#: that does have several sets `request.state.org_id`, which still wins below.
#:
#: This was an inline `"default-org"` literal, which was fine as a value and
#: misleading as a name: migration 003's foreign key made it the one org id that
#: could never be written, so every Design Studio creation failed against a
#: freshly migrated database (#326).
CONDUCTOR_ORG_ID = "default-org"


_ABSENT = object()


def _get_org_id(request: Request) -> str:
    """The scope this request's design projects belong to.

    The fallback applies only when the deployment set *no* scope at all. A
    middleware that sets `request.state.org_id` to `""` or `None` is saying the
    scope is unresolved or unauthorized, and `or CONDUCTOR_ORG_ID` would have
    turned that into the deployment's default scope — a request that could then
    read, render and create projects there (Codex, #326). Present-but-empty is
    refused instead.
    """
    org_id = getattr(getattr(request, "state", None), "org_id", _ABSENT)
    if org_id is _ABSENT:
        return CONDUCTOR_ORG_ID
    if not org_id:
        raise HTTPException(status_code=403, detail="No design scope resolved for this request")
    return str(org_id)


def _require_store() -> Any:
    """Require persistence for a route that reports or uses project state.

    Design resources can remain available without a database, but an empty
    project list would turn missing persistence into a false durable fact. The
    service returns ``None`` for a disabled store during startup and older
    callers can still expose its initialization ``RuntimeError``; normalize
    both forms to the same explicit unavailable response.
    """
    try:
        store = get_design_store()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Design persistence unavailable: {exc}",
        ) from None
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Design persistence unavailable (DATABASE_URL not set)",
        )
    return store


@router.post("/projects")
async def create_design_project(request: Request, discovery: DiscoveryResult) -> dict[str, Any]:
    """Prepare and persist a design project from discovery responses.

    This is project/prompt preparation, not visual generation: the DesignEngine
    does not call an LLM or a renderer. A later canonical Run may consume the
    persisted prompt stack to produce visual artifacts.

    Pipeline:
    1. Validate skill + design system exist
    2. Scan discovery responses (Warden)
    3. Assemble prompt stack
    4. Persist project + outputs to database

    Request body:
      {skill_slug, responses, design_system_slug, trust_tier}

    Returns:
      {id, name, skill_slug, design_system_slug, org_id, team_id, trust_tier,
       output_count, created_at, updated_at}
    """
    _require_ready()
    # Before the `try`, for the reason `_require_ready`'s own docstring gives:
    # each route ends in a blanket `except Exception` that turns whatever it
    # catches into a 500. A refused scope resolved inside it came back as
    # "Project preparation failed: 403: No design scope resolved", hiding an
    # authorization decision behind a 500.
    org_id = _get_org_id(request)
    try:
        # A project preparation response is durable state, never a successful
        # in-memory substitute when persistence is not configured.
        _require_store()
        engine = get_design_engine()
        project = await engine.generate(discovery, org_id=org_id, team_id=None)
        return project.to_dict()
    except HTTPException:
        raise
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except DesignSystemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except DiscoveryIncompleteError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project preparation failed: {e!s}") from None


@router.get("/projects/{project_id}")
async def get_design_project(project_id: str, request: Request) -> dict[str, Any]:
    """Fetch a design project with all outputs, within the caller's scope.

    A project in another scope answers 404, not 403: whether one exists
    elsewhere is itself scoped information (#326).

    Returns:
      {id, name, skill_slug, design_system_slug, org_id, team_id, trust_tier,
       outputs: [{format, content, url, trust_tier, metadata}], discovery: {...}, ...}
    """
    _require_ready()
    org_id = _get_org_id(request)
    try:
        store = _require_store()
        project = await store.get(project_id, org_id=org_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        # Include outputs in response
        project_dict = project.to_dict()
        project_dict["outputs"] = [o.to_dict() for o in project.outputs]
        return project_dict
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/projects")
async def list_design_projects(
    request: Request, skill_slug: str | None = None
) -> list[dict[str, Any]]:
    """List design projects for an org, optionally filtered by skill.

    Query params:
      skill_slug: filter by skill (e.g. "login-flow")

    Returns:
      [{id, name, skill_slug, design_system_slug, org_id, output_count, created_at, ...}]
    """
    _require_ready()
    # Before the `try`, for the same reason as the create route above.
    org_id = _get_org_id(request)
    try:
        store = _require_store()

        if skill_slug:
            projects = await store.list_by_skill(skill_slug, org_id)
        else:
            projects = await store.list_by_org(org_id)

        return [p.to_dict() for p in projects]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/skills")
async def list_design_skills() -> list[dict[str, Any]]:
    """List design skills whose renderer is available (SPEC-070426-a22b).

    Skills whose ``render_slot`` has no discovered provider are silently omitted — the
    reflowable-web/video skills only appear when their external provider is up. Canvas-native
    (fixed-page/deck) skills are always listed.

    Returns:
      [{slug, name, mode, description, featured, output_formats, tags, discovery_form, render_slot}]
    """
    _require_ready()
    try:
        engine = get_design_engine()
        try:
            filled = get_renderer_registry().filled_slots()
            skills = engine._skills.list_available(filled)
        except RuntimeError:
            # renderer registry not initialized — fall back to the full catalog
            skills = engine._skills.list_all()
        return [
            {
                "slug": s.slug,
                "name": s.name,
                "mode": s.mode.value,
                "description": s.description,
                "featured": s.featured,
                "output_formats": [fmt.value for fmt in s.output_formats],
                "tags": s.tags,
                "discovery_form": [f.to_dict() for f in s.discovery_form],
                "render_slot": s.render_slot.value if s.render_slot else None,
            }
            for s in skills
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/packs")
async def list_design_packs() -> list[dict[str, Any]]:
    """List domain packs (M7-A4 #793) — the Design Studio selector payload.

    One listing route over the one pack registry, one uniform entry shape per
    pack: a pack is a registry entry, never a product identity, so there is
    deliberately no per-pack route and no pack-specific fields here.
    Product/game/book are three bundles of the same loop; `execute_backends`
    is where canvas shows up (a binding), never in `pack_id`.

    Unlike the engine-backed routes above, this does not call
    `_require_ready()`: packs are in-repo manifests read through
    `maistro_design.packs.PackRegistry`, not engine state, so the selector
    renders before (or without) a started DesignEngine.
    """
    return [summary.model_dump(mode="json") for summary in PackRegistry.builtin().summaries()]


@router.get("/systems")
async def list_design_systems() -> dict[str, Any]:
    """List the registered design systems, each traceable to where it came from.

    #293. The Conductor used to register one fabricated `DesignSystem` under a
    real system's slug when the bundled set failed to import, so this list --
    had it existed -- would have shown a complete-looking catalogue of one
    entry indistinguishable from the packaged article. Two things follow, and
    they are the shape of this response:

    - **Every system says its origin.** `bundled` and `catalog` are the two
      packaged sets; `external` is anything a caller registered itself. The
      value is recorded by the loader that read the files, not inferred here
      from `trust_tier`, which cannot tell a vendored Tier-2 system from one
      handed over at runtime.
    - **A service that did not start says so, with the cause.** 503 rather
      than an empty list: "no systems" and "we could not load the systems" are
      different facts, and the second is the one #293 spent months rendering
      as the first.

    The `catalog` block is the optional Tier-2 half -- 144 importable systems,
    none registered until asked for. Unavailable is reported as degraded with
    its cause, for the same reason.

    Returns:
      {systems: [{slug, name, description, origin, trust_tier, color_count,
       spacing_count, personas}], catalog: {available, cause, count}, ready,
       cause, bundled_count}
    """
    status = _require_ready()
    engine = get_design_engine()
    systems = [
        {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "origin": s.metadata.get("origin", ORIGIN_EXTERNAL),
            "trust_tier": s.trust_tier.value,
            "color_count": len(s.colors),
            "spacing_count": len(s.spacing),
            # The persona contract a first-party system advertises
            # (ADR-091626-ba4f); None for the vendored brand systems.
            "personas": s.metadata.get("personas"),
        }
        for s in sorted(engine.systems.list_all(), key=lambda s: s.slug)
    ]
    return {"systems": systems, **status.to_dict()}


@router.get("/skills/{skill_slug}/discovery")
async def get_skill_discovery_form(skill_slug: str) -> list[dict[str, Any]]:
    """Get the discovery form for a skill.

    Used by frontend to render the skill configuration form.

    Returns:
      [{key, label, description, field_type, options, required, default}]
    """
    _require_ready()
    try:
        engine = get_design_engine()
        form = await engine.run_discovery(skill_slug)
        return form
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/projects/{project_id}/render")
async def create_render_job(
    project_id: str, request: Request, format: str = "pdf"
) -> dict[str, Any]:
    """Report that project rendering is unavailable until its canonical seam exists.

    The former facade created an in-memory pending job, but no worker advanced
    it or persisted an output. Returning that job made an execution-looking
    state out of a capability that is not connected to Canvas or a canonical
    Run. Keep the scoped existence check, then fail explicitly instead.

    Query params:
      format: reserved output format (pdf, pptx, docx, png)
    """
    _require_ready()
    org_id = _get_org_id(request)
    try:
        store = _require_store()

        # Check the project within the caller's scope before reporting the
        # unavailable capability; another scope must remain indistinguishable.
        project = await store.get(project_id, org_id=org_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        raise HTTPException(
            status_code=501,
            detail="Design rendering is unavailable until the canonical Canvas rendering seam is enabled",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render job creation failed: {e!s}") from None


@router.post("/projects/{project_id}/consistency")
async def evaluate_project_consistency(
    project_id: str, snapshot: CreativeProjectSnapshot
) -> dict[str, Any]:
    """Inspect one creative family for cross-artifact consistency (#779).

    The Design Studio submits the project's frozen snapshot — brief, persona,
    design system, shared decisions, artifacts and provided evidence as the
    creative session holds them — and receives the evaluator's full result
    contract back: per-dimension verdicts, evidence-backed findings, exact
    brief/decision/artifact versions that were evaluated, and a refinement
    proposal for the affected branches only. The evaluation is deliberately
    read-only: it proposes work, it never rewrites the project — canonical
    DAG/Run logic decides what actually runs, under the user's locks and
    control mode. The same evaluation is available as the canonical graph node
    ``design.consistency_eval`` (kind registered in ``maistro_design.nodes``)
    when it must run inside a Run with NodeRun/Attempt provenance; this route
    is the Design Studio's synchronous inspection surface over the identical
    pure evaluator, so both surfaces cannot disagree.

    Body: a ``CreativeProjectSnapshot``. A snapshot naming a different
    project than the path is refused (400) instead of silently mis-filing the
    result — the same canonical-provenance guard the graph node applies.

    Returns:
      The ``ConsistencyEvaluation`` result contract (passed, provenance,
      dimension_results, findings, refinement).
    """
    _require_ready()
    if snapshot.project_id != project_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"snapshot project_id {snapshot.project_id!r} does not match "
                f"the requested project {project_id!r}"
            ),
        )
    return evaluate_project_snapshot(snapshot).model_dump(mode="json")


@router.get("/projects/{project_id}/render/{job_id}")
async def get_render_job_status(project_id: str, job_id: str, request: Request) -> dict[str, Any]:
    """Report that render-job polling is unavailable until Canvas is connected.

    The old implementation polled a process-local ``DesignPreviewService``.
    That state was neither durable nor backed by a worker, so it could not
    truthfully describe execution after a restart. Keep the compatibility
    endpoint scoped, but never expose its fabricated pending/completed state.
    """
    _require_ready()
    org_id = _get_org_id(request)
    try:
        store = _require_store()
        project = await store.get(project_id, org_id=org_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        raise HTTPException(
            status_code=501,
            detail="Design render-job polling is unavailable until the canonical Canvas rendering seam is enabled",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Render job status unavailable: {e!s}"
        ) from None

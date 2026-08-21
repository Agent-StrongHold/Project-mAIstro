"""Design skill routes — project creation, discovery, artifact retrieval.

POST /design/projects — generate design project
GET /design/projects/{id} — fetch project + outputs
GET /design/projects — list org projects
GET /design/skills — list available skills
GET /design/skills/{slug}/discovery — get skill discovery form
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.design_service import (
    get_design_engine,
    get_design_store,
    get_renderer_registry,
)

from maistro_design.types import (
    DesignError,
    DesignSystemNotFoundError,
    DiscoveryIncompleteError,
    DiscoveryResult,
    SkillNotFoundError,
)

router = APIRouter(prefix="/design", tags=["design"])


def _get_org_id(request: Request) -> str:
    """Extract org_id from request context.

    Returns the org_id from authenticated request state, or "default-org" for fallback.
    TODO: Once auth context is wired, extract from request.state.user or request.state.org_id.
    """
    # Phase 2: Extract from request.state.user or similar auth context
    if hasattr(request, "state") and hasattr(request.state, "org_id"):
        return request.state.org_id
    return "default-org"


@router.post("/projects")
async def create_design_project(request: Request, discovery: DiscoveryResult) -> dict[str, Any]:
    """Generate a design project from discovery responses.

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
    try:
        engine = get_design_engine()
        org_id = _get_org_id(request)
        project = await engine.generate(discovery, org_id=org_id, team_id=None)
        return project.to_dict()
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except DesignSystemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except DiscoveryIncompleteError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e!s}") from None


@router.get("/projects/{project_id}")
async def get_design_project(project_id: str) -> dict[str, Any]:
    """Fetch a design project with all outputs.

    Returns:
      {id, name, skill_slug, design_system_slug, org_id, team_id, trust_tier,
       outputs: [{format, content, url, trust_tier, metadata}], discovery: {...}, ...}
    """
    try:
        store = get_design_store()
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Design persistence not configured (DATABASE_URL not set)",
            )
        project = await store.get(project_id)
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
    try:
        store = get_design_store()
        if store is None:
            return []  # Graceful degradation: return empty list if persistence disabled

        org_id = _get_org_id(request)

        if skill_slug:
            projects = await store.list_by_skill(skill_slug, org_id)
        else:
            projects = await store.list_by_org(org_id)

        return [p.to_dict() for p in projects]
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


@router.get("/skills/{skill_slug}/discovery")
async def get_skill_discovery_form(skill_slug: str) -> list[dict[str, Any]]:
    """Get the discovery form for a skill.

    Used by frontend to render the skill configuration form.

    Returns:
      [{key, label, description, field_type, options, required, default}]
    """
    try:
        engine = get_design_engine()
        form = await engine.run_discovery(skill_slug)
        return form
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/projects/{project_id}/render")
async def create_render_job(project_id: str, format: str = "pdf") -> dict[str, Any]:
    """Request server-side rendering of a project output.

    Validates code (for T3 artifacts), creates async render job.
    Returns immediately with job_id for polling.

    Query params:
      format: output format (pdf, pptx, docx, png)

    Returns:
      {job_id, status, created_at}
    """
    try:
        from services.design_preview import get_design_preview_service

        from maistro_design.types import OutputFormat

        store = get_design_store()
        preview_svc = get_design_preview_service()

        # Fetch project
        project = await store.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        # Validate format
        try:
            output_format = OutputFormat(format)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format: {format}. Allowed: pdf, pptx, docx, png",
            ) from None

        # Create render job
        job = preview_svc.create_render_job(project_id, output_format)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "format": output_format,
            "created_at": job.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render job creation failed: {e!s}") from None


@router.get("/projects/{project_id}/render/{job_id}")
async def get_render_job_status(project_id: str, job_id: str) -> dict[str, Any]:
    """Poll render job status and get download URL when ready.

    Returns:
      {job_id, status, url, error, created_at, updated_at}

    Status: pending | rendering | completed | failed
    """
    try:
        from services.design_preview import get_design_preview_service

        preview_svc = get_design_preview_service()
        job = preview_svc.get_render_job(job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Render job {job_id} not found")

        if job.project_id != project_id:
            raise HTTPException(
                status_code=403, detail="Render job does not belong to this project"
            )

        return job.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None

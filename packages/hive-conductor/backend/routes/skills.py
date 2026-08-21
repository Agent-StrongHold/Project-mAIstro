from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException
from models.schemas import Skill
from pydantic import BaseModel, ConfigDict

from maistro.skills.parser import security_scan

router = APIRouter(tags=["skills"])


def _now() -> datetime:
    return datetime.now(UTC)


def _skill_text(name: str, description: str, parameters: list[dict]) -> str:
    """The attacker-controlled text of a skill, as one blob for the scanner.

    Everything here reaches an LLM prompt or a tool-call schema, so all of it
    is a prompt-injection surface, not just the body.
    """
    return "\n".join([name, description, json.dumps(parameters, sort_keys=True, default=str)])


def _reject_if_unsafe(name: str, description: str, parameters: list[dict]) -> None:
    """Fail closed on the same CRITICAL findings the import pipeline blocks on.

    This is the parser-level scan only (``maistro.skills.parser.security_scan``,
    the primitive ``import_pipeline.import_skill`` composes). It is NOT the full
    ADR-083 import gate: no salvage pass, no Warden scan, no T3 sandboxing, and
    no ``rescan_on_use`` policy attachment -- those need a wired Container,
    which these in-memory CRUD routes do not have.
    """
    safe, findings = security_scan(_skill_text(name, description, parameters))
    if not safe:
        critical = [f for f in findings if f.startswith("CRITICAL:")]
        raise HTTPException(
            status_code=400,
            detail=f"skill content failed security scan: {', '.join(critical)}",
        )


@router.get("", response_model=list[Skill])
def list_skills() -> list[Skill]:
    return list(stores.skills.values())


@router.get("/{skill_id}", response_model=Skill)
def get_skill(skill_id: str) -> Skill:
    if skill_id not in stores.skills:
        raise HTTPException(status_code=404, detail="skill not found")
    return stores.skills[skill_id]


class CreateSkillBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    author: str = "hive"
    parameters: list[dict] = []


@router.post("", response_model=Skill, status_code=201)
def create_skill(body: CreateSkillBody) -> Skill:
    _reject_if_unsafe(body.name, body.description, body.parameters)
    sid = str(uuid4())
    skill = Skill(
        id=sid,
        name=body.name,
        description=body.description,
        version=body.version,
        category=body.category,
        author=body.author,
        enabled=True,
        usage_count=0,
        parameters=body.parameters,
    )
    stores.skills[sid] = skill
    return skill


class UpdateSkillBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    version: str | None = None
    category: str | None = None
    author: str | None = None
    parameters: list[dict] | None = None
    enabled: bool | None = None


@router.put("/{skill_id}", response_model=Skill)
def update_skill(skill_id: str, body: UpdateSkillBody) -> Skill:
    if skill_id not in stores.skills:
        raise HTTPException(status_code=404, detail="skill not found")
    skill = stores.skills[skill_id]
    updates = body.model_dump(exclude_none=True)
    skill = skill.model_copy(update=updates)
    # Scan the post-update skill, not the delta: otherwise create-clean /
    # update-dirty smuggles the same payload past the create gate.
    _reject_if_unsafe(skill.name, skill.description, skill.parameters)
    stores.skills[skill_id] = skill
    return skill


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str) -> None:
    if skill_id not in stores.skills:
        raise HTTPException(status_code=404, detail="skill not found")
    stores.skills.pop(skill_id)


class ScanSkillsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    """Raw skill payload to scan ad hoc. When omitted, every stored skill is scanned."""


@router.post("/scan")
def scan_skills(body: ScanSkillsBody | None = None) -> dict:
    """Run the real scanner over stored skills (or an ad-hoc payload).

    Uses ``maistro.skills.parser.security_scan`` -- the same primitive the
    ADR-083 import pipeline blocks on. ``status`` is derived from the findings,
    so a dirty skill reports ``flagged``.

    Scope note (do not read more into a ``clean`` here than it says): this is a
    content scan of the text the app actually stores. It is not a provenance
    check -- these CRUD-created skills never went through
    ``Container.import_skill``, so nothing here attests to signing, T3
    sandboxing, or a ``rescan_on_use`` content-hash binding.
    """
    findings: list[dict] = []

    if body is not None and body.content is not None:
        safe, issues = security_scan(body.content)
        if not safe or issues:
            findings.append({"skill_id": None, "skill_name": None, "issues": issues})
        return {
            "findings": findings,
            "status": "clean" if not findings else "flagged",
            "scanned": 1,
            "scan": "content_only",
        }

    scanned = list(stores.skills.values())
    for skill in scanned:
        safe, issues = security_scan(_skill_text(skill.name, skill.description, skill.parameters))
        if not safe or issues:
            findings.append({"skill_id": skill.id, "skill_name": skill.name, "issues": issues})

    return {
        "findings": findings,
        "status": "clean" if not findings else "flagged",
        "scanned": len(scanned),
        "scan": "content_only",
    }


class ForgeSkillBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str


@router.post("/forge", response_model=Skill)
def forge_skill(body: ForgeSkillBody) -> Skill:
    sid = str(uuid4())
    _reject_if_unsafe(f"forge-{sid[:8]}", body.description, [])
    skill = Skill(
        id=sid,
        name=f"forge-{sid[:8]}",
        description=body.description,
        version="0.1.0",
        category="generated",
        author="forge",
        enabled=True,
        usage_count=0,
        parameters=[],
    )
    stores.skills[sid] = skill
    return skill


@router.patch("/{skill_id}/toggle", response_model=Skill)
def toggle_skill(skill_id: str) -> Skill:
    if skill_id not in stores.skills:
        raise HTTPException(status_code=404, detail="skill not found")
    skill = stores.skills[skill_id]
    skill = skill.model_copy(update={"enabled": not skill.enabled})
    stores.skills[skill_id] = skill
    return skill

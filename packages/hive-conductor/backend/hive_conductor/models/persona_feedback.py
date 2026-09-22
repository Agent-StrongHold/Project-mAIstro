"""PersonaFeedback — thumbs +/- and free-text feedback on a persona.

Persona/Workspace system, Phase I. Submitted against one Workspace but
persisted keyed by that workspace's `persona_template_id`, not the workspace
itself, so feedback from every workspace instantiating the same persona
aggregates into one place -- the future input surface for ADR-060's Tier 2
preference-residual calibration (not built in this slice; see the plan).

This is additive alongside, not a replacement for, the existing
`services/feedback_service.py` DAG-run-scoped thumbs signal -- that one
feeds the DAG-level optimizer via a `maistro.memory.outcomes.Outcome`
record; this one is persona-scoped and workspace-agnostic once submitted.
`dag_run_id`/`node_id` are optional pointers back to that signal for
traceability when the feedback happens to be about one specific run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Thumb = Literal["up", "down"]


class PersonaFeedback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    persona_template_id: str
    workspace_id: str
    user_id: str
    thumb: Thumb
    comment: str = Field(default="", max_length=2000)
    dag_run_id: str = ""
    node_id: str = ""
    created_at: datetime

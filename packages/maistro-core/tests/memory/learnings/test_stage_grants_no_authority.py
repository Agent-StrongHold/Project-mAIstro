"""The knowledge stage never grants permissions or execution authority (ADR-103).

A REPERTOIRE-stage learning is shared knowledge, and that is *all* it is:
metadata about how a claim came to be believed. Two independent tripwires pin
this. The first is behavioural — promoted knowledge about a tool does not
move the Sentinel's fail-closed decision for that tool by one inch. The
second is architectural — no module on the authorization path even imports
the stage machinery, so no future "trusted knowledge" shortcut can appear
without this test failing first.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.security._types import AuthContext
from maistro.security.sentinel.policy import check_permission
from maistro.types.memory import Learning, LearningStage

CORE_SRC = Path(__file__).resolve().parents[3] / "src" / "maistro"
ORG = "org-a"

#: Fragments that would mean the authorization path is consulting knowledge
#: state. Substring level, because the forbidden coupling could arrive via a
#: helper import as easily as via the types directly.
_FORBIDDEN_FRAGMENTS = (
    "memory.learnings",
    "LearningStage",
    "learning_stage_transitions",
    "stage_history",
    "advance_stage",
)


def _sentinel_sources() -> list[Path]:
    security = CORE_SRC / "security"
    return sorted(p for p in security.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_authorization_module_imports_the_knowledge_stage_machinery() -> None:
    """The Sentinel path must not even be able to see a learning's stage."""
    offenders: list[str] = []
    for path in _sentinel_sources():
        text = path.read_text(encoding="utf-8")
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(CORE_SRC)}: {fragment}")
    assert not offenders, f"knowledge state reached the authorization path (ADR-103): {offenders}"


def test_promoted_knowledge_does_not_move_the_fail_closed_permission_decision() -> None:
    """A repertoire learning naming a tool grants nothing for that tool."""

    async def scenario() -> None:
        store = InMemoryLearningStore()
        lid = await store.store(
            Learning(
                tool_name="bash",
                trigger_keys=["bash"],
                learning="bash is safe here",
                org_id=ORG,
            )
        )
        for stage, actor in (
            (LearningStage.LEARNING, "planner"),
            (LearningStage.VALIDATED, "gauntlet"),
            (LearningStage.REPERTOIRE, "curator"),
        ):
            learning = await store.advance_stage(lid, to_stage=stage, actor=actor, org_id=ORG)
        assert learning.stage is LearningStage.REPERTOIRE

        auth_context = AuthContext(user_id="u1", org_id=ORG)
        # Fail-closed default (#1165): a tool absent from the table is denied
        # — and the knowledge ladder offers no exception to that rule.
        assert check_permission(auth_context, "bash", {}) is False

    asyncio.run(scenario())


def test_a_repertoire_learning_is_not_an_execution_authority() -> None:
    """The stage machinery itself confers no run/capability handles.

    The ladder's public surface is plan/record functions over a Learning row.
    Assert its return shapes carry nothing executable: no store, no runner,
    no permission token — the type name itself is the promise.
    """
    import dataclasses

    from maistro.memory.learnings.lifecycle import StageTransition, plan_advance

    learning, _ = plan_advance(
        Learning(tool_name="bash", trigger_keys=["x"], org_id=ORG),
        to_stage=LearningStage.LEARNING,
        actor="planner",
    )
    assert dataclasses.is_dataclass(learning)
    transition = StageTransition(
        learning_id=1,
        org_id=ORG,
        from_stage=LearningStage.MEMORY,
        to_stage=LearningStage.LEARNING,
        actor="planner",
    )
    fields = {f.name for f in dataclasses.fields(transition)}
    assert fields == {
        "learning_id",
        "org_id",
        "from_stage",
        "to_stage",
        "actor",
        "reason",
    }, "the audit record names knowledge provenance only — never an authority"

"""`human.ask_question` — pause the DAG; surface a question to the user;
resume when the user answers.

The node has two execution states:

  - **First reach**: no answer in ctx.metadata['hitl_answers'][node_id] yet.
    The node calls :func:`pause_until` with a structured `paused_reason` so
    the runtime checkpoints the run state to SQLite and surfaces the
    question in DagRuns.tsx.

  - **Resume**: the runtime re-invokes the node with the user's answer
    already attached at ctx.metadata['hitl_answers'][node_id]. The node
    validates it against `response_schema` (a JSON-schema-like dict) and
    returns the answer as the node output.

The runtime piece (durable persistence + WebSocket push to the UI) is the
last piece of Phase 1c.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import (
    PAUSE_AWAITING_HUMAN_ANSWER,
    BaseNode,
    NodeContext,
    now_utc,
    pause_until,
)


class AskQuestionIn(BaseModel):
    question: str = Field(description="Question text shown to the user")
    response_kind: str = Field(
        default="text",
        description="text | yes_no | choice | json (controls UI widget)",
    )
    choices: list[str] = Field(
        default_factory=list,
        description="For response_kind='choice', the allowed answers",
    )
    timeout_seconds: int = Field(
        default=86_400,
        description="If user doesn't answer within this window, the run fails",
    )
    context_markdown: str = Field(
        default="",
        description="Extra context shown above the question (Markdown)",
    )


class AskQuestionOut(BaseModel):
    question: str
    answer: Any = None
    answered_at: str = ""
    timed_out: bool = False


@register_node
class HumanAskQuestionNode(BaseNode[AskQuestionIn, AskQuestionOut]):
    kind: ClassVar[str] = "human.ask_question"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = AskQuestionIn
    output_schema: ClassVar[type[BaseModel]] = AskQuestionOut
    cost_hint: ClassVar[float] = 0.0  # free for the system; expensive for the human
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False  # the I/O is the human, not an external API
    display_name: ClassVar[str] = "Human: ask a question"
    description: ClassVar[str] = (
        "Pause the DAG and surface a question to the user. The DAG resumes "
        "when the user submits an answer."
    )

    async def _execute(self, inputs: AskQuestionIn, ctx: NodeContext) -> AskQuestionOut:
        # Have we been resumed with an answer already?
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        existing = answers.get(ctx.node_id)
        if existing is not None:
            return AskQuestionOut(
                question=inputs.question,
                answer=existing.get("answer"),
                answered_at=str(existing.get("answered_at") or ""),
                timed_out=bool(existing.get("timed_out", False)),
            )

        # First reach — pause. The runtime will:
        #   1. persist the dag_run row with status='paused_hitl'
        #   2. write a 'pending_question' record indexed by (run_id, node_id)
        #   3. push a WebSocket event so DagRuns.tsx renders the input widget
        #   4. when the user POSTs an answer, set status='running' and re-call
        #      this node — which will pick up the answer above.
        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            PAUSE_AWAITING_HUMAN_ANSWER,
            resume_at=resume_at,
            metadata={
                "question": inputs.question,
                "response_kind": inputs.response_kind,
                "choices": list(inputs.choices),
                "context_markdown": inputs.context_markdown,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        # unreachable
        return AskQuestionOut(question=inputs.question)

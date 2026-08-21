from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    import uuid


class PipelineLogEntry(SQLModel):
    order_id: uuid.UUID | None = None  # type: ignore[name-defined]
    template_id: uuid.UUID | None = None  # type: ignore[name-defined]
    creator_id: uuid.UUID | None = None  # type: ignore[name-defined]
    stage: str
    scene_number: int | None = None
    page_number: int | None = None
    iteration: int = 1
    input_context: dict = Field(default_factory=dict)
    ai_output: str = ""
    ai_output_url: str = ""
    ai_output_metadata: dict = Field(default_factory=dict)
    verdict: str = "pending"
    edited_output: str = ""
    edited_output_url: str = ""
    edit_reason: str = ""


async def log_generation(session, entry: PipelineLogEntry) -> uuid.UUID:
    from .models.generation_attempt import GenerationAttempt

    attempt = GenerationAttempt(
        order_id=entry.order_id,
        template_id=entry.template_id,
        creator_id=entry.creator_id,
        stage=entry.stage,
        scene_number=entry.scene_number,
        page_number=entry.page_number,
        iteration=entry.iteration,
        input_context=entry.input_context,
        ai_output=entry.ai_output,
        ai_output_url=entry.ai_output_url,
        ai_output_metadata=entry.ai_output_metadata,
        verdict=entry.verdict,
        edited_output=entry.edited_output,
        edited_output_url=entry.edited_output_url,
        edit_reason=entry.edit_reason,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt.id


async def update_verdict(session, attempt_id: uuid.UUID, verdict: str, **kwargs) -> None:
    from sqlmodel import select

    from .models.generation_attempt import GenerationAttempt

    stmt = select(GenerationAttempt).where(GenerationAttempt.id == attempt_id)
    result = await session.exec(stmt)
    attempt = result.first_one()
    attempt.verdict = verdict
    for key, value in kwargs.items():
        if hasattr(attempt, key):
            setattr(attempt, key, value)
    session.add(attempt)
    await session.commit()

"""Shared Builders runtime for Frank, Mason, and Auditor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from maistro.builders.contracts import RunRequest, RunResult, RunStatus, WorkerName

StageHandler = Callable[[RunRequest], Awaitable[RunResult]]


@dataclass
class BuildersRuntime:
    """Stateless stage dispatcher shared by Builders roles."""

    _handlers: dict[WorkerName, dict[str, StageHandler]] = field(default_factory=dict)
    _prompts: dict[tuple[WorkerName, str, str], str] = field(default_factory=dict)
    _tools: dict[tuple[WorkerName, str], tuple[str, ...]] = field(default_factory=dict)

    def register(self, worker: WorkerName, stage: str, handler: StageHandler) -> None:
        self._handlers.setdefault(worker, {})[stage] = handler

    def supports(self, worker: WorkerName, stage: str) -> bool:
        return stage in self._handlers.get(worker, {})

    def register_prompt(self, worker: WorkerName, stage: str, version: str, prompt: str) -> None:
        self._prompts[(worker, stage, version)] = prompt

    def load_prompt(self, worker: WorkerName, stage: str, version: str) -> str:
        return self._prompts[(worker, stage, version)]

    def register_tools(self, worker: WorkerName, stage: str, tools: tuple[str, ...]) -> None:
        self._tools[(worker, stage)] = tools

    def allowed_tools(self, worker: WorkerName, stage: str) -> tuple[str, ...]:
        return self._tools.get((worker, stage), ())

    async def execute(self, request: RunRequest) -> RunResult:
        handler = self._handlers.get(request.worker, {}).get(request.stage)
        if handler is None:
            return RunResult(
                run_id=request.run_id,
                worker=request.worker,
                stage=request.stage,
                status=RunStatus.FAILED,
                summary=f"Unsupported role/stage: {request.worker.value}/{request.stage}",
            )
        return await handler(request)

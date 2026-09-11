"""Canonical execution adapter for the shipped Builders ReAct turn.

SPEC-201 deliberately keeps the interactive product as a ReAct loop. This
module makes that loop a domain strategy behind canonical Graph -> Run ->
NodeRun -> Attempt execution rather than letting it own execution identity.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maistro.builders.graph import PipelineGraph, PipelineNode
from maistro.builders.graph_executor import (
    CanonicalGraphPipelineExecutor,
    DispatchResult,
)
from maistro.builders.pipeline import PipelineRun, PipelineStage
from maistro.config.database import resolve_database_url, to_asyncpg_dsn
from maistro.graph.durable_runs import CanonicalDurableRunStore
from maistro.runs.model import RunStatus
from maistro.runs.store import RunStore
from maistro.runs.wiring import wire_execution_spine

_DEFAULT_WORKSPACE_ID = "default"
_DEFAULT_DATABASE_PATH = Path.home() / ".maistro" / "builders.db"
_TURN_NODE_NAME = "interactive-turn"


@dataclass(frozen=True)
class InteractiveTurnResult:
    """Result of one interactive turn, including its canonical identity."""

    run_id: str
    status: RunStatus
    output: str
    raw_result: dict[str, Any] | None
    error: str = ""


class _ReActDispatcher:
    """Adapt SPEC-201's TurnRunner as physical work for one canonical node."""

    def __init__(self, runner: Any, messages: list[dict[str, Any]]) -> None:
        self._runner = runner
        self._messages = messages
        self.raw_result: dict[str, Any] | None = None
        self.output = ""

    def supports(self, agent_name: str, node_name: str) -> bool:
        return agent_name == "builders-react" and node_name == _TURN_NODE_NAME

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: dict[str, Any],
    ) -> DispatchResult:
        del run_id, node_name, agent_name, prompt, context
        try:
            # TurnRunner remains the ReAct domain strategy. The caller is the
            # canonical graph adapter, so this call is physical node work and
            # not an independent execution admission path.
            result = await self._runner.execute_turn(messages=list(self._messages))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return DispatchResult(ok=False, error=str(exc) or type(exc).__name__)

        self.raw_result = result
        stop_reason = result.get("stop_reason")
        if stop_reason in {"error", "max_turns"}:
            return DispatchResult(
                ok=False,
                error=str(result.get("error") or f"interactive turn stopped: {stop_reason}"),
            )
        content = result.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("text")
            )
        self.output = str(content)
        return DispatchResult(ok=True, output=self.output)


class CanonicalInteractiveTurnExecutor:
    """Admit and execute one Builders interactive turn on the canonical spine."""

    def __init__(
        self,
        *,
        run_store: RunStore,
        durable_store: Any,
        workspace_id: str,
        project_id: str,
    ) -> None:
        self._run_store = run_store
        self._durable_store = durable_store
        self._workspace_id = workspace_id
        self._project_id = project_id

    async def execute(
        self,
        *,
        session_id: str,
        repo: str,
        prompt: str,
        messages: list[dict[str, Any]],
        runner: Any,
    ) -> InteractiveTurnResult:
        """Execute a bounded ReAct continuation as one canonical Run."""
        domain_run = PipelineRun(
            id=f"builders-turn-{uuid.uuid4().hex}",
            issue_number=0,
            title=prompt[:200] or "Builders interactive turn",
            repo=repo,
            stages=[
                PipelineStage(
                    name=_TURN_NODE_NAME,
                    agent_name="builders-react",
                    prompt_template="{prompt}",
                )
            ],
        )
        domain_run.context.update(
            {
                "prompt": prompt,
                "repo": repo,
                "session_id": session_id,
                "interactive": True,
            }
        )
        dispatcher = _ReActDispatcher(runner, messages)
        graph = PipelineGraph(
            [
                PipelineNode(
                    name=_TURN_NODE_NAME,
                    agent_name="builders-react",
                    prompt_template="{prompt}",
                )
            ]
        )
        record = await CanonicalGraphPipelineExecutor(
            dispatcher,
            run_store=self._run_store,
            durable_store=self._durable_store,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        ).execute(graph, domain_run)
        return InteractiveTurnResult(
            run_id=record.run_id,
            status=record.run.status,
            output=dispatcher.output,
            raw_result=dispatcher.raw_result,
            error=domain_run.failed_stage_error,
        )


@dataclass
class BuildersExecutionSpine:
    """Configured canonical stores used by the interactive CLI process."""

    workspace_id: str
    project_id: str
    run_store: RunStore
    durable_store: Any
    _close: Any

    @classmethod
    async def open(
        cls,
        *,
        workspace_id: str = _DEFAULT_WORKSPACE_ID,
        database_url: str | None = None,
    ) -> BuildersExecutionSpine:
        """Open the configured canonical backend for the Builders CLI scope.

        A standalone CLI with no deployment URL uses a private SQLite file,
        not an in-memory store, so session resume and inspection retain the
        same Run identity across process restarts.
        """
        url = database_url or resolve_database_url()
        if not url:
            _DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{_DEFAULT_DATABASE_PATH}"

        closer: Any
        if url.startswith("sqlite:"):
            import aiosqlite

            path = url.removeprefix("sqlite:///")
            conn = await aiosqlite.connect(os.path.expanduser(path))
            (
                projects,
                run_store,
                _admitter,
                _templates,
                _schedules,
                continuations,
            ) = await wire_execution_spine(conn, workspace_id=workspace_id)

            async def close() -> None:
                await conn.close()

            closer = close
        else:
            from maistro.persistence import get_pool, release_pool

            pool = await get_pool(to_asyncpg_dsn(url))
            (
                projects,
                run_store,
                _admitter,
                _templates,
                _schedules,
                continuations,
            ) = await wire_execution_spine(None, workspace_id=workspace_id, pg_pool=pool)

            async def close() -> None:
                await release_pool(pool)

            closer = close

        project = await projects.root_for_workspace(workspace_id)
        return cls(
            workspace_id=workspace_id,
            project_id=project.project_id,
            run_store=run_store,
            durable_store=CanonicalDurableRunStore(run_store, continuations),
            _close=closer,
        )

    async def close(self) -> None:
        await self._close()

    def executor(self) -> CanonicalInteractiveTurnExecutor:
        return CanonicalInteractiveTurnExecutor(
            run_store=self.run_store,
            durable_store=self.durable_store,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
        )


__all__ = [
    "BuildersExecutionSpine",
    "CanonicalInteractiveTurnExecutor",
    "InteractiveTurnResult",
]

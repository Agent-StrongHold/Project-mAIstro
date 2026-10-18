"""Live projection recording for the interactive DAG-Run websocket (#1183).

`routes.dags._record_run_projection` mirrors a settled canonical Run into the
bounded Recent Runs projection in one shot. The websocket transport cannot
wait for settlement: its whole contract is frames while the Run is in flight.
`LiveRunProjection` is the same projection, recorded incrementally — one
`pm_node_*` event per live node transition, each durably appended (with its
sequence number) BEFORE the transport sends the matching frame, plus the
terminal `finish_run` when the Run settles.

Scope comes from the caller's `DagExecutionScope` — the same authorized
scope the execution itself was admitted into (`canonical_dag_runner._scope`
resolves the identical values), so a projection row is born with its
canonical Workspace and is inspectable from its first live event (#1174).
Nothing here mints a second execution identity: the row is keyed by, and
`canonical_run_id`-linked to, the canonical Run the executing nodes report.

Like `_record_run_projection`, recording failures are logged, never raised:
projection is presentation, and a failing append must not flip a NodeRun
outcome or break the stream.
"""

from __future__ import annotations

import logging
from typing import Any

from services.dag_execution_scope import DagExecutionScope

logger = logging.getLogger("hive.dag_run_live")

#: Longest response text kept in one live event payload, matching the cap the
#: settled projection path applies (`dag_run_store.MAX_RESULT_CHARS`). The
#: full text remains in the canonical NodeRun result.
MAX_EVENT_RESPONSE_CHARS = 2000

_EVENT_TYPES = {
    "node_started": "pm_node_started",
    "node_completed": "pm_node_completed",
    "node_failed": "pm_node_failed",
}


class LiveRunProjection:
    """Record one interactive Run's projection as it happens, not after."""

    def __init__(self, *, dag_id: str, scope: DagExecutionScope) -> None:
        self._dag_id = dag_id
        self._scope = scope
        self._started_run_ids: set[str] = set()

    async def _ensure_started(self, store: Any, run_id: str) -> None:
        if run_id in self._started_run_ids:
            return
        await store.start_run(
            run_id=run_id,
            canonical_run_id=run_id,
            dag_id=self._dag_id,
            user_id=self._scope.user_id,
            workspace_id=self._scope.workspace_id,
            project_id=self._scope.project_id,
        )
        self._started_run_ids.add(run_id)

    async def record_event(self, event: dict[str, Any]) -> int | None:
        """Append one live node transition; returns its projection seq.

        The returned sequence number is the frame's resume cursor (#1183): a
        consumer that saw seq N knows the projection holds everything through
        N and can detect any later gap.
        """
        run_id = str(event.get("run_id") or "")
        node_id = str(event.get("node_id") or "")
        event_type = _EVENT_TYPES.get(str(event.get("kind") or ""))
        if not run_id or not node_id or event_type is None:
            return None
        try:
            from services.dag_run_store import get_dag_run_store

            store = get_dag_run_store()
            await self._ensure_started(store, run_id)
            payload: dict[str, Any] = {"source": "canonical_node_run"}
            if event_type == "pm_node_completed":
                response = str(event.get("response") or "")
                payload["response"] = response[:MAX_EVENT_RESPONSE_CHARS]
            ev = await store.append_event(
                run_id,
                event_type=event_type,
                role=str(event.get("role") or "worker"),
                capability=node_id,
                payload=payload,
            )
            return ev.seq or None
        except Exception:
            logger.warning(
                "dag_run_live_projection_event_not_recorded run_id=%s node_id=%s",
                run_id,
                node_id,
                exc_info=True,
            )
            return None

    async def record_result(self, result: dict[str, Any]) -> None:
        """Mirror the settled canonical outcome (start-if-needed + finish).

        Node events were already appended live; re-appending them here would
        duplicate every node in the SSE replay, so this records only what the
        live path could not know: the terminal status and the bounded result.
        A Run that produced no live events (recovered/detached execution)
        still gets its full projection row here.
        """
        run_id = str(result.get("run_id") or "")
        if not run_id:
            return
        try:
            from services.dag_run_store import get_dag_run_store

            store = get_dag_run_store()
            await self._ensure_started(store, run_id)
            await store.finish_run(
                run_id,
                status=str(result.get("status") or "failed"),
                result=result,
            )
        except Exception:
            logger.warning(
                "dag_run_live_projection_result_not_recorded run_id=%s dag_id=%s",
                run_id,
                self._dag_id,
                exc_info=True,
            )

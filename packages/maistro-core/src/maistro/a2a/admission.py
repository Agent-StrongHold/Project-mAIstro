"""Admitting a delegation as a child Run (#147, ADR-082226-c126's siblings).

The fourth entry point onto the same seam, after the task queue (#41), chat
(#131) and schedules (#145). It differs from all three in one way that matters:
a delegation has a parent. Tasks, chat turns and schedule firings are root
Runs; delegated work is a child of the Run and NodeRun that asked for it.

`RunStore.create_run` has always accepted `parent_run_id`/`parent_node_run_id`
and has always enforced the two guards #47 asks for — a child may not cross a
Workspace boundary, and may not implicitly cross a Project boundary. Delegation
simply never reached them, because it created no Run at all: the delegated
work's identity was an `A2ATask` id and a `TaskStatus` enum running alongside
the spine rather than on it.

The A2A task stays. It is the receipt — the transport's record of what it was
asked to carry — in exactly the way `TaskResponse` remains the queue's receipt.
What changes is that it stops being the only record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.runs.admission import USER_ID_KEY, admit_direct_work
from maistro.runs.task_kinds import resolve_direct_work

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.intents import IntentRegistry
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore

#: `admission_source` value for work that entered through a delegation.
DELEGATION_SOURCE = "a2a_delegation"

#: Provenance keys a delegated Run carries.
#: The A2A task id — the transport receipt this Run was admitted alongside.
A2A_TASK_ID_KEY = "a2a_task_id"
#: The agent that asked for the delegation.
FROM_AGENT_KEY = "from_agent"
#: The agent (or peer) the work was handed to.
TO_AGENT_KEY = "to_agent"
#: `in_process` or `guest_peer` — which of the two delegation models ran it.
DELEGATION_MODE_KEY = "delegation_mode"
#: The registered peer name, on the cross-instance path only.
PEER_NAME_KEY = "peer_name"


class DelegationRunAdmitter:
    """Admit delegated work as a child Run of the Run that delegated it."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        intents: IntentRegistry | None = None,
    ) -> None:
        self._runs = run_store
        self._intents = intents

    async def admit_delegation(
        self,
        *,
        parent_run_id: str,
        parent_node_run_id: str | None,
        task: str,
        to_agent: str,
        from_agent: str = "",
        mode: str = "in_process",
        peer_name: str | None = None,
        a2a_task_id: str = "",
        user_id: str | None = None,
    ) -> Run:
        """Create the child Run for one delegation and return it.

        The Workspace and Project come from the parent Run, never from the
        caller. A delegation that could name its own scope would be a way to
        move work into a tenant the delegating agent has no authority in, which
        is the escape the store's guards exist to refuse — and refusing it here
        by construction is better than refusing it there by check.
        """
        parent = await self._runs.get_run(parent_run_id)
        if parent is None:
            from maistro.runs.store import RunIntegrityError

            raise RunIntegrityError(
                f"cannot delegate from Run {parent_run_id!r}: it does not resolve"
            )
        work = resolve_direct_work(
            description=task,
            agent_id=to_agent,
            from_agent=from_agent,
            registry=self._intents,
        )
        provenance: dict[str, Any] = {
            FROM_AGENT_KEY: from_agent,
            TO_AGENT_KEY: work.agent_name,
            DELEGATION_MODE_KEY: mode,
        }
        if a2a_task_id:
            provenance[A2A_TASK_ID_KEY] = a2a_task_id
        if peer_name:
            provenance[PEER_NAME_KEY] = peer_name
        if user_id:
            provenance[USER_ID_KEY] = user_id
        return await admit_direct_work(
            self._runs,
            workspace_id=parent.workspace_id,
            project_id=parent.project_id,
            node_type=work.node_type,
            name=work.name,
            source=DELEGATION_SOURCE,
            parameters=work.parameters,
            description=task,
            actor_principal_id=user_id or parent.actor_principal_id,
            persona_id=parent.persona_id,
            provenance=provenance,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
        )


__all__ = [
    "A2A_TASK_ID_KEY",
    "DELEGATION_MODE_KEY",
    "DELEGATION_SOURCE",
    "FROM_AGENT_KEY",
    "PEER_NAME_KEY",
    "TO_AGENT_KEY",
    "DelegationRunAdmitter",
]

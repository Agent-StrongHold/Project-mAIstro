"""DAG-as-agent registry.

A saved DAG (`DagDefinition`) is registered under `dag:<id>` so other
agents — and the existing `GET /v1/agents` listing — see it as a
callable. Calling `dag:<id>` resolves to `run_durable_dag(snapshot, ...)`.

This is pure maistro-core; Hive consumes it (services/dag_registry.py)
and exposes the catalog over HTTP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .dag_validator import ValidationReport, validate_dag


@dataclass(frozen=True)
class DagAgentDescriptor:
    """One DAG, presented as a callable agent.

    `agent_id` follows the convention `dag:<dag_id>` so the rest of the
    fleet can route to it like any other agent. `snapshot` is the frozen
    DAGFile dict captured at registration time — runs are reproducible
    regardless of later edits.
    """

    agent_id: str
    dag_id: str
    name: str
    description: str
    snapshot: dict[str, Any]
    use_case: str = "generic"
    project_id: str | None = None
    version: int = 1


class DagRegistry:
    """In-process registry of DAG-as-agent entries.

    Hive wires a single shared instance in its container DI; tests use a
    fresh instance per test. No globals.
    """

    def __init__(self) -> None:
        self._by_agent_id: dict[str, DagAgentDescriptor] = {}

    def register(
        self,
        dag: dict[str, Any],
        *,
        project_id: str | None = None,
        validator: Callable[[dict[str, Any]], ValidationReport] = validate_dag,
    ) -> DagAgentDescriptor:
        """Validate + register a DAG. Raises ValueError on validation errors.

        The agent_id is `dag:<dag.id>`. If a DAG with the same id is
        already registered, this is treated as an update (version bumps).
        """
        report = validator(dag)
        if not report.is_valid:
            raise ValueError(
                f"DAG failed validation with {report.error_count} error(s): "
                f"{[f.message for f in report.findings if f.severity == 'error'][:3]}"
            )
        dag_id = str(dag.get("id") or dag.get("name") or "")
        if not dag_id:
            raise ValueError("DAG must have an `id` (or `name`) for registration")
        agent_id = f"dag:{dag_id}"
        existing = self._by_agent_id.get(agent_id)
        version = (existing.version + 1) if existing else 1
        descriptor = DagAgentDescriptor(
            agent_id=agent_id,
            dag_id=dag_id,
            name=str(dag.get("name") or dag_id),
            description=str(dag.get("description") or ""),
            snapshot=dict(dag),  # shallow copy of the spec
            use_case=str(dag.get("use_case") or "generic"),
            project_id=project_id,
            version=version,
        )
        self._by_agent_id[agent_id] = descriptor
        return descriptor

    def deregister(self, dag_id_or_agent_id: str) -> bool:
        """Remove a DAG from the registry. Accepts either form (`dag:foo`
        or `foo`). Returns True if it existed."""
        agent_id = (
            dag_id_or_agent_id
            if dag_id_or_agent_id.startswith("dag:")
            else f"dag:{dag_id_or_agent_id}"
        )
        return self._by_agent_id.pop(agent_id, None) is not None

    def get(self, dag_id_or_agent_id: str) -> DagAgentDescriptor | None:
        agent_id = (
            dag_id_or_agent_id
            if dag_id_or_agent_id.startswith("dag:")
            else f"dag:{dag_id_or_agent_id}"
        )
        return self._by_agent_id.get(agent_id)

    def list_agents(
        self,
        *,
        project_id: str | None = None,
        use_case: str | None = None,
    ) -> list[DagAgentDescriptor]:
        """List registered DAG agents.

        Filter by `project_id` and/or `use_case`. Sorted by agent_id for
        deterministic output (UI palettes + tests like this).
        """
        out: list[DagAgentDescriptor] = []
        for desc in self._by_agent_id.values():
            if project_id is not None and desc.project_id != project_id:
                continue
            if use_case is not None and desc.use_case != use_case:
                continue
            out.append(desc)
        out.sort(key=lambda d: d.agent_id)
        return out

    def as_agent_catalog(self) -> list[dict[str, Any]]:
        """Serialize the full registry for `GET /v1/agents` extensions.

        Returns one entry per DAG, shaped to interleave with the existing
        agent listing without surprising the frontend (id + name +
        description fields match what fleet agents expose).
        """
        return [
            {
                "id": desc.agent_id,
                "name": desc.name,
                "description": desc.description,
                "kind": "dag",
                "use_case": desc.use_case,
                "project_id": desc.project_id,
                "version": desc.version,
            }
            for desc in self.list_agents()
        ]

    def __len__(self) -> int:
        return len(self._by_agent_id)

    def __contains__(self, dag_id_or_agent_id: str) -> bool:
        return self.get(dag_id_or_agent_id) is not None


# --- Runner adapter -------------------------------------------------------


DagRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Function the registry uses to actually invoke a DAG.

Caller (Hive) supplies a runner that takes the snapshot dict and returns
the run-result dict — typically `lambda snap: await run_durable_dag(snap,
store=…, node_resolver=…)` curried with the live store + resolver.
"""


async def invoke_dag_agent(
    agent_id: str,
    *,
    registry: DagRegistry,
    runner: DagRunner,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke a registered DAG agent by id.

    Returns the runner's result (the durable run record serialized as a
    dict by the caller). Raises ``KeyError`` if the agent doesn't exist.
    """
    desc = registry.get(agent_id)
    if desc is None:
        raise KeyError(f"No DAG agent registered for {agent_id!r}")
    snap = dict(desc.snapshot)
    if inputs is not None:
        snap["_runtime_inputs"] = inputs
    return await runner(snap)

"""EngineService — singleton that wires maistro-core into hive-conductor.

Exposes two surfaces:
  chat   — route_request() delegates to MaistroCoreBridge
  tasks  — submit_task() / get_task() / list_tasks() / iter_task_events() via
           a TaskBackend (ADR-096 / SPEC-226): MaistroServerTaskBackend calls
           maistro-server's /tasks API in production; LocalTaskBackend wraps
           an in-process TaskQueue/runner, demo mode only.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from adapters.task_backend import TaskRecord
from protocols.agent import AgentPort

logger = logging.getLogger("hive.engine")

#: The Workspace name both this app and maistro-core default to. Only a
#: deployment that changed it needs the warning below.
DEFAULT_WORKSPACE_ID = "default"

if TYPE_CHECKING:
    from config import Settings

__all__ = ["EngineService", "TaskRecord", "get_engine", "start_engine", "stop_engine"]


class EngineService:
    def __init__(self) -> None:
        # The port, not a concrete adapter: the engine's job is to hold the
        # seam (ADR-037's provider-agnostic telemetry/agent boundary), and
        # every consumer below routes through `route()` rather than the
        # bridge's own surface. `_bind_agent_port` is the one assignment
        # point, so the conformance of both implementations is checked where
        # they are chosen, not assumed where they are used (#63).
        self._agent_port: AgentPort | None = None
        self._backend: Any = None
        self._configured = False
        self._capabilities: Any = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def capabilities(self) -> Any:
        """The CapabilityRegistry backing the API. Sourced from the core Container
        when configured, else a standalone canonical registry (stub/dev mode)."""
        if self._capabilities is None:
            from maistro.capabilities.bootstrap import default_capability_registry

            self._capabilities = default_capability_registry()
        return self._capabilities

    @property
    def episodic_store(self) -> Any:
        """The core Container's EpisodicStore, or None in stub/unconfigured mode.

        The memory-decay driver (SPEC-080126-9e42) sweeps this. None is a real
        answer, not an error: without the bridge there is no episodic memory in
        this process, so there is nothing to decay — and the driver says so.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "episodic_store", None)

    @property
    def task_admitter(self) -> Any:
        """The core Container's seam onto the canonical Run spine, or None.

        None is a real answer, like `episodic_store` above: without the bridge
        there is no Run store in this process, and a task queue told to admit
        against nothing would fail every submission.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "task_admitter", None)

    @property
    def run_store(self) -> Any:
        """The core Container's canonical Run store, or None.

        None for the same reason as `task_admitter`: without the bridge there
        is no Run store in this process, and the task runner then executes
        without recording a NodeRun rather than inventing one (#143).
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "run_store", None)

    @property
    def schedule_store(self) -> Any:
        """The core Container's canonical Schedule store, or None.

        None for the same reason as `run_store`. Without it the scheduler keeps
        its cursor on the in-memory `/v1/schedules` row, which is where it lived
        before #231 — lost on restart, and private to one replica.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "schedule_store", None)

    @property
    def schedule_admitter(self) -> Any:
        """The core Container's schedule admission seam, or None.

        None for the same reason as `schedule_store`: without the bridge there
        is no canonical spine in this process, and the scheduler then keeps the
        behavior it had — evaluate locally and run the registered DAG — rather
        than failing every tick. With the bridge, this is what makes a firing
        and its Run one act instead of two (#231).
        """
        container = getattr(getattr(self, "_agent_port", None), "container", None)
        return getattr(container, "schedule_admitter", None)

    @property
    def outcome_store(self) -> Any:
        """The core Container's durable outcome store, or None.

        None for the same reason as `run_store`: without the bridge there is no
        durable store in this process, and `feedback_service` then keeps the
        Hive-local in-memory one rather than writing thumbs nowhere.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "outcome_store", None)

    def _wire_outcome_store(self) -> None:
        """Point feedback writes at the container's durable store.

        `set_outcome_store` has existed since the feedback route landed and had
        no production caller, so every thumb a user gave went into a capped
        in-process list and was lost on restart. This is the call the setter's
        own docstring already described (#696).

        Without a container this installs a *fresh* Hive-local store rather
        than leaving whatever was bound before. Returning early would be a bug
        on the second start in one process -- an engine restart, or a
        configuration retry that falls back to the stub -- because the module
        global would still point at the previous container's store, and
        feedback would keep being written to a database this engine no longer
        owns, or to a closed connection. `start()` decides the store for the
        engine it is starting; it does not inherit one.
        """
        from maistro.memory.outcomes import InMemoryOutcomeStore
        from services import feedback_service

        store = self.outcome_store or InMemoryOutcomeStore()
        feedback_service.set_outcome_store(store)
        logger.info("feedback_outcome_store_bound store=%s", type(store).__name__)

    async def start(self, settings: Settings) -> None:
        from adapters.maistro_core import MaistroCoreBridge, StubAgentPort

        if settings.maistro_router_api_key:
            bridge = MaistroCoreBridge()
            try:
                await bridge.start(settings)
                self._bind_agent_port(bridge)
                self._configured = True
            except Exception as exc:
                # The module logger, not a function-local `import logging`:
                # that import bound `logging` as a local for the whole
                # function, so the later handler's `logging.getLogger(...)`
                # raised UnboundLocalError whenever this branch was not taken —
                # turning any failure below into a different, wrong error.
                logger.warning("maistro-core bridge failed (%s) — falling back to stub", exc)
                self._bind_agent_port(StubAgentPort())
        else:
            self._bind_agent_port(StubAgentPort())

        self._wire_capabilities(settings)
        self._wire_outcome_store()

        # A fresh metrics buffer per engine start. `set_store` had no
        # production caller -- the wired-but-unread shape #236 gates -- and a
        # buffer carried across a restart would mix the previous process's
        # observations into this one's window (#698).
        from services.node_metrics_store import reset_store

        reset_store()

        # Recovery is a system reconciliation cadence, not a user schedule.
        # Start it only after the core bridge has established the canonical Run
        # and Graph-continuation stores so another replica can recover a process
        # that died between Run admission and checkpoint 1 (#835/#837).
        from services.dag_recovery import start_dag_recovery

        start_dag_recovery()

        try:
            if settings.hive_mode == "demo":
                from adapters.task_backend import LocalTaskBackend

                from maistro.agents.conductor import run_task

                # Demo mode retains the local backend, but not a product-specific
                # executor switch. Workspace Persona identity is resolved before
                # submission through the generic materialized roster; execution
                # has one authority regardless of legacy POC environment values.
                backend = LocalTaskBackend(
                    executor=run_task,
                    admitter=self.task_admitter,
                    run_store=self.run_store,
                )
                await backend.start()
                self._backend = backend
                logger.info("LocalTaskBackend (demo) using canonical conductor executor")
            else:
                from adapters.task_backend import MaistroServerTaskBackend

                self._backend = MaistroServerTaskBackend(
                    base_url=settings.maistro_base_url,
                    api_key=settings.maistro_router_api_key,
                )
                if settings.hive_default_workspace_id != DEFAULT_WORKSPACE_ID:
                    # This deployment's tasks are admitted by a separate
                    # maistro-server, which reads its own WORKSPACE_ID. A Hive
                    # that customized its default without an identical remote
                    # setting silently files every unscoped submission outside
                    # the Workspace it thinks it configured -- said out loud,
                    # because the symptom is a correct-looking Run in the wrong
                    # Project rather than an error.
                    logger.warning(
                        "hive_default_workspace_id=%s is not applied to the remote task "
                        "server; set the same WORKSPACE_ID there or unscoped submissions "
                        "will land in its own default",
                        settings.hive_default_workspace_id,
                    )
                logger.info(
                    "MaistroServerTaskBackend wired — production tasks via %s",
                    settings.maistro_base_url,
                )
        except Exception as exc:
            logger.warning("TaskBackend setup failed (%s) — mission dispatch disabled", exc)

    def _bind_agent_port(self, port: AgentPort) -> None:
        """Assign the one agent seam, checking the port contract as chosen.

        `AgentPort` is runtime-checkable, so the structural claim both
        adapters make is verified at the composition point instead of
        failing later at the first call with a different AttributeError for
        each implementation (#63).
        """
        if not isinstance(port, AgentPort):
            raise TypeError(
                f"{type(port).__name__} does not satisfy AgentPort; "
                "the engine cannot route chat through it"
            )
        self._agent_port = port

    def _wire_capabilities(self, settings: Settings) -> None:
        """Source the registry (Container when configured, else canonical) and
        register host-health providers + apply activation. Never crashes startup."""
        container = getattr(self._agent_port, "container", None)
        if container is not None and getattr(container, "capabilities", None) is not None:
            self._capabilities = container.capabilities
        else:
            from maistro.capabilities.bootstrap import default_capability_registry

            self._capabilities = default_capability_registry()

        try:
            from services import settings_store
            from services.capabilities_wiring import wire_capabilities
            from services.foundation import get_foundation

            try:
                vault = get_foundation().vault
            except Exception:
                vault = None

            wire_capabilities(
                self._capabilities,
                settings_model=settings_store.current(),
                config=settings,
                vault=vault,
            )
        except Exception as exc:
            logger.warning("capability wiring failed (%s) — slots use baselines/SAFE_NOOP", exc)

    async def stop(self) -> None:
        from services.dag_recovery import stop_dag_recovery

        await stop_dag_recovery()
        if self._backend is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await self._backend.stop()

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        return await self._agent_port.route(
            messages,
            session_id=session_id,
            intent_hint=intent_hint,
        )

    async def submit_task(
        self,
        name: str,
        description: str,
        *,
        user_id: str = "",
        workspace_id: str | None = None,
        task_type: str | None = None,
        agent_id: str | None = None,
        capability: str | None = None,
        program_context: dict | None = None,
    ) -> TaskRecord:
        """Submit one task, optionally under a named Hive Workspace (#158).

        `workspace_id` must already be authorized by the route that accepted the
        request — this service does not know Hive's membership model and does
        not check it. None means the deployment's default Workspace, which is
        what every caller that names no Workspace still gets.
        """
        if self._backend is None:
            raise RuntimeError("TaskQueue not available")
        from maistro.agents.pm_capabilities import is_gated, normalize_capability
        from maistro.tasks.models import TaskCreate

        cap = normalize_capability(capability or "")
        pctx_probe = program_context if isinstance(program_context, dict) else {}
        if is_gated(cap) and not pctx_probe.get("confirmed"):
            raise ValueError(
                f"Capability {cap!r} must use the work-item draft flow (POST /v1/work-items/suggest → confirm)"
            )

        pctx = program_context
        if pctx is None and user_id:
            try:
                from maistro.agents.program_context import context_for_task
                from services import program_store as prog

                pctx = context_for_task(prog.get_context(user_id))
            except Exception:
                pctx = None

        rec = await self._backend.submit(
            TaskCreate(
                description=description or name,
                task_type=task_type,
                agent_id=agent_id,
                capability=capability,
                program_context=pctx,
            ),
            user_id=user_id,
            workspace_id=workspace_id,
        )
        logger.info(
            "task_submitted id=%s user=%s workspace=%s agent=%s capability=%s type=%s",
            rec.id,
            user_id or "-",
            workspace_id or "-",
            agent_id or "-",
            capability or "-",
            task_type or "-",
        )
        return rec

    def get_task(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None:
        if self._backend is None:
            return None
        return self._backend.get(task_id, user_id=user_id)

    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]:
        if self._backend is None:
            return []
        return self._backend.list_tasks(user_id=user_id)

    def delete_task(self, task_id: str) -> bool:
        if self._backend is None:
            return False
        remove = getattr(self._backend, "remove", None)
        if remove is not None:
            return bool(remove(task_id))
        return False

    @property
    def supports_clear(self) -> bool:
        """Whether this deployment's backend can bulk-clear tasks.

        `MaistroServerTaskBackend` cannot: it has no `remove_where`, so
        `clear_tasks` returns 0 and a caller is told a clear succeeded that
        removed nothing. A UI that can read this can decline to offer the
        control instead of reporting "cleared 0" as a success.
        """
        return self._backend is not None and hasattr(self._backend, "remove_where")

    def clear_tasks(self, *, status: str | None = None) -> int:
        if self._backend is None:
            return 0
        remove_where = getattr(self._backend, "remove_where", None)
        if remove_where is None:
            return 0
        from maistro.tasks.models import TaskStatus

        filter_status: TaskStatus | None = None
        if status == "failed":
            filter_status = TaskStatus.FAILED
        elif status == "completed":
            filter_status = TaskStatus.COMPLETED
        return remove_where(status=filter_status)

    async def iter_task_events(
        self, task_id: str, *, user_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        if self._backend is None:
            return
        # When scoped to a user, stream only that user's own task. The backend's
        # get() enforces ownership (empty-owner tasks fail closed), so a None
        # result means "not yours / not found" — yield nothing rather than
        # leaking another principal's in-flight events.
        if user_id is not None and self._backend.get(task_id, user_id=user_id) is None:
            return
        async for event in self._backend.iter_events(task_id):
            yield event


_singleton: EngineService | None = None


def get_engine() -> EngineService:
    if _singleton is None:
        raise RuntimeError("EngineService not started — call start_engine() at app lifespan")
    return _singleton


async def start_engine(settings: Settings) -> EngineService:
    global _singleton
    _singleton = EngineService()
    await _singleton.start(settings)
    return _singleton


async def stop_engine() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.stop()
        _singleton = None

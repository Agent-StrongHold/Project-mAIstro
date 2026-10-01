"""EngineService — singleton that wires maistro-core into hive-conductor.

Exposes two surfaces:
  chat   — route_request() delegates to MaistroCoreBridge
  tasks  — submit_task() / get_task() / list_tasks() / iter_task_events() via
           a TaskBackend (ADR-096 / SPEC-226): MaistroServerTaskBackend calls
           maistro-server's /tasks API in production; LocalTaskBackend wraps
           an in-process TaskQueue/runner, demo mode only.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from adapters.task_backend import TaskRecord
from protocols.agent import AgentPort

logger = logging.getLogger("hive.engine")

#: The Workspace name both this app and maistro-core default to. Only a
#: deployment that changed it needs the warning below.
DEFAULT_WORKSPACE_ID = "default"

if TYPE_CHECKING:
    from config import Settings

__all__ = [
    "EngineService",
    "EngineState",
    "TaskRecord",
    "engine_health",
    "get_engine",
    "start_engine",
    "stop_engine",
]

#: Lifecycle states the engine moves through (#1181). /health must be able to
#: tell a successfully stopped engine apart from a boot that failed halfway,
#: and both apart from one that is serving — possibly with a degraded
#: optional component.
EngineState = Literal["not_started", "starting", "ready", "degraded", "startup_failed", "stopped"]

#: Health/JSON surfaces carry a bounded, type-qualified failure cause — never
#: a raw traceback, and no settings value is ever interpolated into one (#1181).
#: Text is also passed through the ADR-064 redactor before retention: startup
#: dependency errors (DSNs, tokens, connection strings) reach the unauthenticated
#: /health as `cause`/`degradations`, so truncation alone is not enough.
_CAUSE_MAX_CHARS = 300


def _sanitize_cause(exc: BaseException) -> str:
    """One bounded, redacted, type-qualified line for /health and structured logs."""
    try:
        from maistro.security.redact import redact

        text = redact(f"{type(exc).__name__}: {exc}")
    except Exception:
        # Fail closed: if the redactor itself is unavailable we cannot vouch
        # for the message body, so publish the exception type only.
        text = type(exc).__name__
    if len(text) > _CAUSE_MAX_CHARS:
        text = text[:_CAUSE_MAX_CHARS] + "…"
    return text


async def _reset_runtime_source() -> None:
    """Unwind the bridge's agent_materialization runtime registration (#1181).

    `MaistroCoreBridge.start` has no stop half, but it does leave one piece of
    process-global state behind: the runtime source the boot materializer
    resolves against. A boot that fails after that point must forget it, or a
    registry that never published would still own the materialization seam.
    """
    from services.agent_materialization import reset_runtime_source

    reset_runtime_source()


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
        # Lifecycle state machine (#1181): `start()` runs the whole boot
        # sequence under one failure/cleanup contract, and `state`/`health()`
        # are the only externally visible account of where it got to.
        self._state: EngineState = "not_started"
        self._startup_error: str | None = None
        self._degradations: list[str] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def state(self) -> EngineState:
        """The lifecycle state (#1181) — see `health()`."""
        return self._state

    def health(self) -> dict[str, Any]:
        """Lifecycle health snapshot (#1181).

        `state` distinguishes what /health must tell apart: `starting` (boot
        in flight), `ready` (all required steps succeeded), `degraded`
        (serving, but a documented optional component failed),
        `startup_failed` (a required step failed and startup was rolled
        back), and `stopped`. `cause` is the sanitized startup failure;
        `degradations` lists the optional-component failures this start
        absorbed. Component entries are type names only.
        """
        return {
            "state": self._state,
            "cause": self._startup_error,
            "degradations": list(self._degradations),
            "agent_port": type(self._agent_port).__name__ if self._agent_port is not None else None,
            "task_backend": type(self._backend).__name__ if self._backend is not None else None,
            "bridge_configured": self._configured,
        }

    def _record_degradation(self, component: str, exc: BaseException) -> None:
        """Absorb one optional-component failure as a health-visible degradation."""
        self._degradations.append(f"{component}: {_sanitize_cause(exc)}")

    @property
    def agent_port(self) -> AgentPort | None:
        """The bound AgentPort, for boot seams that need the runtime itself
        (the roster materializer reads the bridge's container off it)."""
        return self._agent_port

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
    def run_reader(self) -> Any:
        """The core Container's Workspace-scoped Run reader, or None (#1152).

        `create_container` builds it over the Container's own `run_store`, so
        it is None when there is no Container, as `run_store` is.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "run_reader", None)

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

    async def _reset_outcome_store_binding(self) -> None:
        """Unwind step for `_wire_outcome_store` (#1181).

        The restart hazard its docstring describes applies to a failed boot
        too: if a later step fails, feedback must not keep pointing at the
        previous engine's store. Rebind the fresh Hive-local one so the
        post-failure process is deterministic.
        """
        from maistro.memory.outcomes import InMemoryOutcomeStore
        from services import feedback_service

        feedback_service.set_outcome_store(InMemoryOutcomeStore())

    async def start(self, settings: Settings) -> None:
        """Run the whole boot sequence under one explicit failure/cleanup
        contract (#1181).

        Every step below is required, except the two documented optional
        degradations: a configured bridge that cannot start falls back to the
        stub port, and capability wiring that cannot apply falls back to
        baselines/SAFE_NOOP — both now recorded as health-visible
        degradations. A required step that raises unwinds the steps that did
        start, in reverse order, marks this instance `startup_failed` with a
        sanitized cause, clears its component handles, and re-raises — so
        `start_engine` never publishes a partially-initialized singleton. A
        failed start is retryable: the next `start()` resets this state and
        re-runs the sequence from the top once the dependency is restored.
        There is no path where a failed boot leaves a live-looking engine
        behind.
        """
        from adapters.maistro_core import MaistroCoreBridge, StubAgentPort

        self._state = "starting"
        self._startup_error = None
        self._degradations = []
        #: Steps that started successfully, in order. The failure path stops
        #: them in reverse — one cleanup contract for the whole sequence.
        unwind: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        try:
            # Required: the agent seam. A configured bridge that fails takes
            # the documented stub path — an optional degradation, not a boot
            # failure. The module logger, not a function-local `import
            # logging`: that import bound `logging` as a local for the whole
            # function, so the later handler's `logging.getLogger(...)` raised
            # UnboundLocalError whenever this branch was not taken — turning
            # any failure below into a different, wrong error.
            if settings.maistro_router_api_key:
                bridge = MaistroCoreBridge()
                try:
                    await bridge.start(settings)
                    self._bind_agent_port(bridge)
                    self._configured = True
                    # The bridge registered the module-global runtime source
                    # in services.agent_materialization; if a later step
                    # fails, the unwind must forget it so no seam keeps
                    # pointing at a container this engine no longer owns.
                    unwind.append(("agent_port", _reset_runtime_source))
                except Exception as exc:
                    logger.warning("maistro-core bridge failed (%s) — falling back to stub", exc)
                    self._bind_agent_port(StubAgentPort())
                    self._record_degradation("agent_port", exc)
            else:
                self._bind_agent_port(StubAgentPort())

            # Required to source the registry; its wiring half is the second
            # documented optional degradation (baselines/SAFE_NOOP).
            self._wire_capabilities(settings)

            # Required: the feedback outcome store.
            self._wire_outcome_store()
            unwind.append(("outcome_store", self._reset_outcome_store_binding))

            # A fresh metrics buffer per engine start. `set_store` had no
            # production caller -- the wired-but-unread shape #236 gates -- and
            # a buffer carried across a restart would mix the previous
            # process's observations into this one's window (#698).
            from services.node_metrics_store import reset_store

            reset_store()

            # Required: recovery. Recovery is a system reconciliation cadence,
            # not a user schedule. Start it only after the core bridge has
            # established the canonical Run and Graph-continuation stores so
            # another replica can recover a process that died between Run
            # admission and checkpoint 1 (#835/#837).
            from services.canonical_recovery import (
                start_canonical_recovery,
                stop_canonical_recovery,
            )
            from services.dag_recovery import start_dag_recovery, stop_dag_recovery

            start_dag_recovery()
            unwind.append(("dag_recovery", stop_dag_recovery))
            # The Container's own recovery ticks (lease reclaim, stranded chat
            # admissions, elapsed-pause resume) are operator-scheduled
            # (ADR-019); this process is their operator (#62).
            start_canonical_recovery()
            unwind.append(("canonical_recovery", stop_canonical_recovery))

            # Canonical Evolve Run recovery (#1064) is bracketed by the Evolve
            # service's own lifecycle (`services.evolution.start_evolution`/
            # `stop_evolution`), not the engine's: `services.evolution_graph`'s
            # recovery resolver requires the Evolve singleton to exist, and this
            # engine start runs before `start_evolution()` does in application
            # startup. Starting the cadence here raced that ordering -- a due
            # RUNNING Run inspected in the gap terminalized FAILED for no reason
            # but startup sequencing. See `services.evolution.start_evolution`.

            # Required (#1181): the task backend. This was a guarded block
            # that downgraded to "mission dispatch disabled" on failure,
            # leaving a running engine whose every submission path fails only
            # at call time; it now follows the same contract as every other
            # required step — failure rolls the boot back.
            await self._start_task_backend(settings)
            unwind.append(("task_backend", self._stop_backend))
        except Exception as exc:
            # One deterministic rollback: stop what started, in reverse, then
            # clear every component handle so the instance reads as
            # not-running while `state`/`cause` keep the failure visible
            # (#1181). `start_engine` does not publish an engine that got
            # here, and the sanitized cause survives for `engine_health()`.
            self._startup_error = _sanitize_cause(exc)
            self._state = "startup_failed"
            for name, stop_step in reversed(unwind):
                try:
                    await stop_step()
                except Exception:
                    logger.exception("engine_start_unwind_failed component=%s", name)
            self._backend = None
            self._agent_port = None
            self._capabilities = None
            self._configured = False
            logger.error("engine_start_failed cause=%s", self._startup_error)
            raise
        self._state = "degraded" if self._degradations else "ready"
        logger.info("engine_started state=%s", self._state)

    async def _start_task_backend(self, settings: Settings) -> None:
        """Start the task backend — a required startup step (#1181)."""
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
            try:
                await backend.start()
            except Exception:
                # The runner may have half-started before raising; the
                # backend's own stop is exception-suppressed, so this is the
                # deterministic rollback for the backend's own step.
                with contextlib.suppress(Exception):
                    await backend.stop()
                raise
            self._backend = backend
            logger.info("LocalTaskBackend (demo) using canonical conductor executor")
        else:
            from adapters.task_backend import MaistroServerTaskBackend

            configured_delegation_key = getattr(settings, "maistro_delegation_key", None)
            delegation_key = (
                configured_delegation_key.get_secret_value()
                if configured_delegation_key is not None
                else None
            )
            self._backend = MaistroServerTaskBackend(
                base_url=settings.maistro_base_url,
                api_key=settings.maistro_router_api_key,
                delegation_key=delegation_key,
                service_principal=getattr(settings, "maistro_service_principal", "conductor"),
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

    async def _stop_backend(self) -> None:
        if self._backend is not None:
            with contextlib.suppress(Exception):
                await self._backend.stop()

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
                effect_context=getattr(container, "capability_effects", None),
            )
        except Exception as exc:
            logger.warning("capability wiring failed (%s) — slots use baselines/SAFE_NOOP", exc)
            self._record_degradation("capabilities", exc)

    async def stop(self) -> None:
        from services.canonical_recovery import stop_canonical_recovery
        from services.dag_recovery import stop_dag_recovery

        await stop_dag_recovery()
        await stop_canonical_recovery()
        # Evolve recovery cadence stop moved to `services.evolution.stop_evolution`
        # (#1064) -- see the matching note in `start()`.
        await self._stop_backend()
        if self._state in ("ready", "degraded", "startup_failed", "starting"):
            # Truthful terminal state (#1181): a stopped engine reads as
            # stopped, never as whatever it was while (or before) serving.
            # A never-attempted engine stays `not_started`.
            self._state = "stopped"

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        return await self._agent_port.route(
            messages,
            auth=auth,
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
        from maistro.agents.pm_capabilities import (
            AUTONOMOUS_CAPABILITIES,
            GATED_CAPABILITIES,
            is_gated,
            normalize_capability,
        )
        from maistro.tasks.models import TaskCreate

        cap = normalize_capability(capability or "")
        pctx_probe = program_context if isinstance(program_context, dict) else {}
        if is_gated(cap) and not pctx_probe.get("confirmed"):
            raise ValueError(
                f"Capability {cap!r} must use the work-item draft flow (POST /v1/work-items/suggest → confirm)"
            )
        if cap in AUTONOMOUS_CAPABILITIES or cap in GATED_CAPABILITIES:
            raise ValueError(
                f"PM capability execution {cap!r} through the generic task queue is retired; "
                "keep it as a Workspace Persona proposal until canonical Graph execution owns it"
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

    def delete_task(self, task_id: str, *, user_id: str | None = None) -> bool:
        """Remove a terminal local receipt; production cancellation is async."""
        if self._backend is None:
            return False
        remove = getattr(self._backend, "remove", None)
        if remove is None:
            return False
        if user_id is not None and self._backend.get(task_id, user_id=user_id) is None:
            return False
        return bool(remove(task_id))

    async def cancel_task(self, task_id: str, *, user_id: str | None = None) -> bool:
        """Cancel through the one backend, preserving its ownership check.

        The probe is `get_async`, not the sync `get`: this coroutine runs on
        the event loop (async `DELETE /v1/missions/{id}`), and the production
        backend's sync probe is a 30s-timeout httpx GET that would pin every
        coroutine in the worker behind one slow maistro-server response —
        the same blocking boundary #1180 moved out of the stream.
        """
        if self._backend is None or await self._backend.get_async(task_id, user_id=user_id) is None:
            return False
        return await self._backend.cancel(task_id, user_id=user_id)

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
        # When scoped to a user, stream only that user's own task. A None from
        # get_async() means "not yours / not found" — yield nothing rather than
        # leaking another principal's in-flight events. LocalTaskBackend scopes
        # by owner (empty-owner tasks fail closed); MaistroServerTaskBackend
        # cannot yet forward the user principal, so it only checks existence
        # (#1057).
        if user_id is not None and await self._backend.get_async(task_id, user_id=user_id) is None:
            return
        if user_id is None:
            events = self._backend.iter_events(task_id)
        else:
            events = self._backend.iter_events(task_id, user_id=user_id)
        async for event in events:
            yield event


_singleton: EngineService | None = None
#: The most recent start attempt that failed, kept for health reporting only:
#: a failed start is never published, but /health must still show why the
#: product cannot serve (#1181).
_failed_startup: EngineService | None = None


def get_engine() -> EngineService:
    if _singleton is None:
        raise RuntimeError("EngineService not started — call start_engine() at app lifespan")
    return _singleton


def engine_health() -> dict[str, Any]:
    """Engine lifecycle health, answerable at any point in the process (#1181).

    A start that failed is not published — `get_engine()` keeps raising — but
    /health must still distinguish a clean not-started engine from one whose
    boot failed and was rolled back, so the failed attempt's snapshot stays
    reachable here until the next start succeeds or the engine stops.
    """
    engine = _singleton if _singleton is not None else _failed_startup
    if engine is None:
        return {
            "state": "not_started",
            "cause": None,
            "degradations": [],
            "agent_port": None,
            "task_backend": None,
            "bridge_configured": False,
        }
    return engine.health()


async def start_engine(settings: Settings) -> EngineService:
    """Build, start, and only then publish the process-global engine (#1181).

    Publication is the last step, so a boot that fails cannot leave
    `_singleton` installed over half-wired components — the poisoned
    process-global this module used to expose. Policy: a failed start is
    retryable. The failed attempt is retained only for `engine_health()`; the
    next `start_engine()` call runs a fresh boot once the dependency is
    restored.
    """
    global _singleton, _failed_startup
    engine = EngineService()
    try:
        await engine.start(settings)
    except Exception:
        _failed_startup = engine
        raise
    _singleton = engine
    _failed_startup = None
    return engine


async def stop_engine() -> None:
    global _singleton, _failed_startup
    if _singleton is not None:
        await _singleton.stop()
        _singleton = None
    _failed_startup = None

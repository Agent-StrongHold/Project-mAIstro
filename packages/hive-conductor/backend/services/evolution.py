"""Evolution service -- wires maistro-evolve into hive-conductor.

Population, fitness, lineage and tournament state remain Evolve domain state.
Actual cycle execution is delegated to ``services.evolution_graph`` so the live
product path records one canonical Run with NodeRuns and physical Attempts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY, ModelChatEgress
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, ModelChatRequest
from maistro.graph.nodes.base import NodeContext
from maistro.runs.model import RunStatus

logger = logging.getLogger(__name__)

_service: _EvolutionService | None = None


class _GovernedModelCall:
    """Adapt Evolve's prompt callable onto the canonical model egress.

    Evolve still owns prompt shaping and response parsing. This adapter only
    supplies execution identity and a stable per-NodeRun effect key so the
    canonical Invocation service owns provider dispatch and retry safety.
    """

    def __init__(
        self,
        *,
        effects: CapabilityEffectContext,
        egress: ModelChatEgress,
        declarations: tuple[Any, ...],
        workspace_id: str,
        default_model: str,
    ) -> None:
        self._effects = effects
        self._egress = egress
        self._declarations = declarations
        self._workspace_id = workspace_id
        self._default_model = default_model
        self._first_failure: BaseException | None = None

    @property
    def first_failure(self) -> BaseException | None:
        return self._first_failure

    def for_context(self, ctx: NodeContext) -> Any:
        call_number = 0

        async def call(messages: Any, **kwargs: Any) -> str:
            nonlocal call_number
            if self._first_failure is not None:
                raise RuntimeError("a prior Evolve model effect failed") from self._first_failure
            try:
                binding_id = self._binding_id(ctx)
                binding = await self._effects.bindings.resolve(
                    binding_id,
                    workspace_id=str(ctx.workspace_id or self._workspace_id),
                    project_id=str(ctx.project_id or ""),
                    node_id=ctx.node_id,
                    capability=MODEL_CHAT_CAPABILITY,
                )
                if isinstance(messages, str):
                    shaped_messages = [{"role": "user", "content": messages}]
                else:
                    shaped_messages = [dict(message) for message in messages]
                model = str(kwargs.get("model") or self._default_model)
                request = ModelChatRequest(
                    model=model,
                    messages=shaped_messages,
                    temperature=float(kwargs.get("temperature", 0.3)),
                    max_tokens=kwargs.get("max_tokens", 4096),
                )
                request_digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()[:16]
                effect_key = f"evolve.model:{ctx.node_id}:{call_number}:{request_digest}"
                call_number += 1
                result = await self._egress.complete(
                    binding=binding,
                    run_id=ctx.run_id,
                    node_run_id=ctx.node_run_id,
                    attempt_id=ctx.attempt_id,
                    effect_key=effect_key,
                    request=request,
                )
                choices = result.body.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise RuntimeError("model gateway response contained no choices")
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str):
                    raise RuntimeError("model gateway response contained no text content")
                return content
            except BaseException as exc:
                if not isinstance(exc, asyncio.CancelledError) and self._first_failure is None:
                    self._first_failure = exc
                raise

        call.governed_model_call = self  # type: ignore[attr-defined]
        return call

    def _binding_id(self, ctx: NodeContext) -> str:
        workspace_id = str(ctx.workspace_id or self._workspace_id)
        project_id = str(ctx.project_id or "")
        exact: list[str] = []
        generic: list[str] = []
        for declaration in self._declarations:
            declared_workspace = str(getattr(declaration, "workspace_id", "") or self._workspace_id)
            if (
                declared_workspace != workspace_id
                or str(getattr(declaration, "project_id", "")) != project_id
            ):
                continue
            binding_id = str(getattr(declaration, "binding_id", ""))
            if not binding_id:
                continue
            if str(getattr(declaration, "node_id", "")) == ctx.node_id:
                exact.append(binding_id)
            elif not str(getattr(declaration, "node_id", "")):
                generic.append(binding_id)
        selected = exact[0] if exact else (generic[0] if generic else "")
        if not selected:
            raise BindingNotFound(
                "Evolve model work requires an operator-declared model.chat Binding "
                f"for Workspace {workspace_id!r} and Project {project_id!r}"
            )
        return selected


class EvolutionServiceNotStarted(RuntimeError):
    """The Evolve service has not been installed by application lifespan."""


class EvolutionUnavailableError(RuntimeError):
    """Evolve domain state exists, but canonical execution cannot admit work."""

    def __init__(self, message: str, *, availability: str) -> None:
        super().__init__(message)
        self.availability = availability


class CanonicalEvolutionRunError(RuntimeError):
    """A canonical Evolve Run reached a terminal non-success state."""

    def __init__(self, *, run_id: str, status: RunStatus, diagnostic: str) -> None:
        self.run_id = run_id
        self.status = status
        self.diagnostic = diagnostic
        super().__init__(f"Evolution cycle canonical Run {run_id} did not complete: {diagnostic}")

    def as_detail(self) -> dict[str, str]:
        return {
            "code": "canonical_run_failed",
            "run_id": self.run_id,
            "status": self.status.value,
            "diagnostic": self.diagnostic,
            "message": str(self),
        }


def get_evolution_service() -> _EvolutionService:
    if _service is None:
        raise EvolutionServiceNotStarted("EvolutionService not started")
    return _service


async def start_evolution() -> None:
    global _service
    _service = _EvolutionService()
    _service.initialize_domain_state()
    # A degraded/stub engine retains Evolve's domain projection for inspection,
    # but must not start a cadence that is guaranteed to fail admission.
    if _service.execution_available:
        # Keep a reference to the background task so it isn't garbage-collected mid-flight.
        _service.task = asyncio.ensure_future(_service.run_loop())

    # The restart/recovery cadence (#1064) is bracketed by THIS service's own
    # lifecycle, not the engine's. Application startup previously started it
    # from `EngineService.start()`, well before this function ever ran --
    # `_recovery_resolver` then raised `EvolutionServiceNotStarted` for any
    # due RUNNING Run inspected in that window, which the executor's own
    # failure boundary turns into a terminal FAILED Run for no reason but
    # lifecycle ordering. Starting it here, only once `_service` exists, closes
    # that window. Unconditional (unlike the cadence task above): a
    # degraded/stub engine still needs recovery ticking so a later Run stays
    # eligible instead of stalling until a restart that happens to start with
    # a healthy engine -- the tick itself already no-ops safely (0 recovered)
    # via `canonical_execution_owner()` when the engine cannot admit work.
    from services.evolution_recovery import start_evolution_recovery

    start_evolution_recovery()


async def stop_evolution() -> None:
    global _service
    # Stop and join the recovery cadence BEFORE clearing the singleton, the
    # mirror image of start: application shutdown previously cleared this
    # singleton in `_shutdown_background_services` before `EngineService.stop()`
    # got around to cancelling the cadence task, leaving the same
    # `EvolutionServiceNotStarted` window open at the other end of the
    # process's life. Stopping first means the cadence can never observe
    # `_service is None` mid-tick.
    from services.evolution_recovery import stop_evolution_recovery

    await stop_evolution_recovery()
    if _service is not None:
        _service.stop()
        _service = None


class _EvolutionService:
    def __init__(self) -> None:
        self._running = True
        self._population: Any = None
        self._cycle_count = 0
        self._last_cycle_error: str | None = None
        self._last_run_id: str | None = None
        self._last_run_status: RunStatus | None = None
        self.task: asyncio.Task[None] | None = None
        self._tournament: Any = None
        # Manual requests and the cadence task share one admission lock. This
        # serializes cycle planning/finalization without making the population
        # store a second execution authority.
        self._cycle_lock = asyncio.Lock()
        self._execution_available = False
        self._availability = "unavailable"
        self._availability_reason: str | None = "canonical engine execution has not been checked"
        self._refresh_execution_availability()

    @property
    def execution_available(self) -> bool:
        return self._execution_available

    def _refresh_execution_availability(self) -> None:
        from services.evolution_graph import (
            CanonicalExecutionUnavailable,
            canonical_execution_owner,
        )

        try:
            canonical_execution_owner()
        except CanonicalExecutionUnavailable as exc:
            self._execution_available = False
            self._availability = exc.availability
            self._availability_reason = str(exc)
            return
        # A healthy engine is necessary, not sufficient: a cycle also needs the
        # domain state `initialize_domain_state` builds. Advertising
        # "executable" without it enabled the Run Cycle button and started the
        # cadence, and every request then failed before Run admission with
        # "population is not initialized" (Codex review). Readiness is one
        # answer, not two.
        if self._population is None or self._tournament is None:
            self._execution_available = False
            self._availability = "unavailable"
            self._availability_reason = self._domain_state_reason()
            return
        self._execution_available = True
        self._availability = "executable"
        self._availability_reason = None

    def _domain_state_reason(self) -> str:
        reason = "Evolution population is not initialized"
        if self._last_cycle_error:
            reason = f"{reason}: {self._last_cycle_error}"
        return reason

    def initialize_domain_state(self) -> None:
        """Initialize inspectable Evolve state without claiming execution is live.

        Ends by re-deriving availability either way: the domain state is part
        of what "executable" means, so a successful init is what turns the
        flag on and a failed one is what keeps it off.
        """
        if self._population is not None and self._tournament is not None:
            self._refresh_execution_availability()
            return
        try:
            from maistro_evolve.population import PopulationStore
            from maistro_evolve.tournament import EloTournament

            self._population = PopulationStore()
            self._tournament = EloTournament()
        except Exception as exc:
            self._last_cycle_error = str(exc)
            logger.warning("Evolution population init failed: %s", exc)
        self._refresh_execution_availability()

    def stop(self) -> None:
        self._running = False

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def population(self) -> Any:
        return self._population

    @property
    def tournament(self) -> Any:
        return self._tournament

    @property
    def last_run_id(self) -> str | None:
        return self._last_run_id

    @property
    def cycle_lock(self) -> asyncio.Lock:
        """The lock manual/cadence cycles and seeding share (#1064).

        A recovery tick must hold this same lock while it executes graph
        nodes and mutates ``population``/``tournament``, exactly as
        ``seed_population`` and ``_run_one_cycle_locked`` already do, or
        recovery could interleave with a live cycle/seed and corrupt the
        shared domain state despite the normal path's own serialization.
        """
        return self._cycle_lock

    def record_recovered_run(
        self, run_id: str, status: RunStatus, *, error: str | None = None
    ) -> None:
        """Fold one recovery-terminalized Run into this service's status (#1064).

        Mirrors the bookkeeping ``_run_one_cycle_locked`` performs for a live
        cycle. Without this, a stranded/due Run recovered to a terminal
        status left ``/evolution/status`` reporting the previous cycle's
        ``cycle_count``/``last_run_id``/``last_run_status``, and the next
        live admission could reuse the recovered cycle's ``cycle_number``.
        """
        self._last_run_id = run_id
        self._last_run_status = status
        if status is RunStatus.COMPLETED:
            self._cycle_count += 1
            self._last_cycle_error = None
        else:
            self._last_cycle_error = error or f"canonical Run ended {status.value}"

    async def run_loop(self) -> None:
        self.initialize_domain_state()
        if self._population is None or self._tournament is None:
            return
        self._refresh_execution_availability()
        if not self._execution_available:
            return

        while self._running:
            await asyncio.sleep(300)
            if not self._running:
                break
            self._refresh_execution_availability()
            if not self._execution_available:
                logger.warning("Evolution cadence stopped: %s", self._availability_reason)
                break
            try:
                await self._run_one_cycle()
            except Exception as exc:
                self._last_cycle_error = str(exc)
                logger.warning("Evolution cycle failed: %s", exc)

    async def seed_population(self, count: int) -> tuple[int, int]:
        """Fence seeding against cycle planning, traversal, and finalization."""
        from maistro_evolve.diversity import emergency_spawn

        async with self._cycle_lock:
            if self._population is None:
                raise RuntimeError("Evolution population is not initialized")
            existing = self._population.list_all()
            spawned = emergency_spawn(existing, count)
            for genome in spawned:
                self._population.add(genome)
            return len(spawned), len(self._population.list_all())

    async def _run_one_cycle(self, *, actor_principal_id: str | None = None) -> str:
        async with self._cycle_lock:
            return await self._run_one_cycle_locked(actor_principal_id=actor_principal_id)

    async def _run_one_cycle_locked(self, *, actor_principal_id: str | None = None) -> str:
        from maistro_evolve.cycle import EvolutionConfig
        from maistro_evolve.harness import EvalHarness
        from services.evolution_graph import (
            CanonicalExecutionUnavailable,
            canonical_execution_owner,
            run_canonical_evolution_cycle,
        )

        try:
            canonical_execution_owner()
        except CanonicalExecutionUnavailable as exc:
            self._execution_available = False
            self._availability = exc.availability
            self._availability_reason = str(exc)
            raise EvolutionUnavailableError(
                self._availability_reason,
                availability=self._availability,
            ) from exc
        if self._population is None or self._tournament is None:
            # Same answer `/status` gives: unavailable, with the reason, as a
            # 503 rather than a bare 500 from a RuntimeError.
            self._execution_available = False
            self._availability = "unavailable"
            self._availability_reason = self._domain_state_reason()
            raise EvolutionUnavailableError(
                self._availability_reason, availability=self._availability
            )
        self._execution_available = True
        self._availability = "executable"
        self._availability_reason = None

        config = EvolutionConfig(
            self_improve=True,
            self_improve_top_n=3,
        )
        harness = EvalHarness(benchmark_fidelity="proxy")
        record = await run_canonical_evolution_cycle(
            population=self._population,
            tournament=self._tournament,
            config=config,
            harness=harness,
            llm_call=self._build_llm_call(),
            actor_principal_id=actor_principal_id,
            cycle_number=self._cycle_count + 1,
        )
        self._last_run_id = record.run_id
        self._last_run_status = record.run.status
        if record.run.status is not RunStatus.COMPLETED:
            detail = record.run.error or f"canonical Run ended {record.run.status.value}"
            failure = CanonicalEvolutionRunError(
                run_id=record.run_id,
                status=record.run.status,
                diagnostic=detail,
            )
            self._last_cycle_error = str(failure)
            raise failure

        self._cycle_count += 1
        self._last_cycle_error = None
        pop_size = len(self._population.list_all())
        logger.info(
            "Evolution cycle %d complete as canonical Run %s, population: %d",
            self._cycle_count,
            record.run_id,
            pop_size,
        )
        return record.run_id

    def build_llm_call(self):
        """Public accessor so a restart-recovery resolver can reconstruct the
        same llm_call this service would have built for a live cycle (#1064).
        """
        return self._build_llm_call()

    def _build_llm_call(self):
        """Build the Evolve adapter over the container's governed model egress."""
        try:
            from config import get_settings

            from services.evolution_graph import _engine_container
            from services.secrets import litellm_api_key, maistro_llm_api_key

            settings = get_settings()
            base = settings.litellm_api_base
            if not base:
                return None
            owner = _engine_container()
            effects = owner.capability_effects
            endpoint = GatewayEndpoint(
                base_url=base,
                api_key=maistro_llm_api_key(settings) or litellm_api_key(settings) or "",
                timeout_s=120.0,
            )
            return _GovernedModelCall(
                effects=effects,
                egress=ModelChatEgress(
                    effects,
                    registry=owner.provider_registry,
                    router=owner.llm_router,
                    endpoint=endpoint,
                ),
                declarations=tuple(getattr(owner.config, "model_bindings", ())),
                workspace_id=str(owner.config.workspace_id),
                default_model=settings.chat_default_model,
            )
        except Exception:
            # A service can start before the embedded canonical container. The
            # cycle remains governed: once a container exists this builder is
            # retried at cycle admission, while an unavailable model path is
            # never replaced by a private HTTP fallback.
            return None

    def status(self) -> dict:
        self._refresh_execution_availability()
        get_stats = getattr(self._tournament, "get_stats", None)
        tournament_stats = get_stats() if callable(get_stats) else {}
        return {
            # `running` is deliberately executable availability, not merely the
            # lifetime of this projection service.
            "running": self._running and self._execution_available,
            "execution_available": self._execution_available,
            "availability": self._availability,
            "availability_reason": self._availability_reason,
            "domain_state_only": not self._execution_available,
            "cycle_count": self._cycle_count,
            "population_size": len(self._population.list_all()) if self._population else 0,
            "last_error": self._last_cycle_error,
            "last_run_id": self._last_run_id,
            "last_run_status": self._last_run_status.value if self._last_run_status else None,
            "tournament": tournament_stats,
        }

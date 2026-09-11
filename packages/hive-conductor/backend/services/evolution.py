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


def get_evolution_service() -> _EvolutionService:
    if _service is None:
        raise RuntimeError("EvolutionService not started")
    return _service


async def start_evolution() -> None:
    global _service
    _service = _EvolutionService()
    # Keep a reference to the background task so it isn't garbage-collected mid-flight.
    _service.task = asyncio.ensure_future(_service.run_loop())


async def stop_evolution() -> None:
    global _service
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
        self.task: asyncio.Task[None] | None = None
        self._tournament: Any = None

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

    async def run_loop(self) -> None:
        try:
            from maistro_evolve.population import PopulationStore
            from maistro_evolve.tournament import EloTournament

            self._population = PopulationStore()
            self._tournament = EloTournament()
        except Exception as exc:
            logger.warning("Evolution population init failed: %s", exc)
            return

        while self._running:
            await asyncio.sleep(300)
            if not self._running:
                break
            try:
                await self._run_one_cycle()
            except Exception as exc:
                self._last_cycle_error = str(exc)
                logger.warning("Evolution cycle failed: %s", exc)

    async def _run_one_cycle(self, *, actor_principal_id: str | None = None) -> str:
        from maistro_evolve.cycle import EvolutionConfig
        from maistro_evolve.harness import EvalHarness
        from services.evolution_graph import run_canonical_evolution_cycle

        if self._population is None or self._tournament is None:
            raise RuntimeError("Evolution population is not initialized")

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
        if record.run.status is not RunStatus.COMPLETED:
            detail = record.run.error or f"canonical Run ended {record.run.status.value}"
            raise RuntimeError(
                f"Evolution cycle canonical Run {record.run_id} did not complete: {detail}"
            )

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
        tournament_stats = self._tournament.get_stats() if self._tournament else {}
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "population_size": len(self._population.list_all()) if self._population else 0,
            "last_error": self._last_cycle_error,
            "last_run_id": self._last_run_id,
            "tournament": tournament_stats,
        }

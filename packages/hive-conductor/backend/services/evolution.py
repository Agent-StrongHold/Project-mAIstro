"""Evolution service -- wires maistro-evolve into hive-conductor.

Population, fitness, lineage and tournament state remain Evolve domain state.
Actual cycle execution is delegated to ``services.evolution_graph`` so the live
product path records one canonical Run with NodeRuns and physical Attempts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from maistro.capabilities.binding_store import BindingNotFound, BindingStore
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY, ModelChatEgress, ModelChatRequest
from maistro.graph.nodes.base import NodeContext
from maistro.runs.model import RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.types.config import ModelBindingConfig

logger = logging.getLogger(__name__)

_service: _EvolutionService | None = None


def _public_failure(exc: BaseException) -> str:
    """What /status and the browser may learn: the kind, never the message.

    Exception text here carries import paths, Container diagnostics, and
    provider replies; those stay in the server log (CodeQL py/stack-trace-exposure).
    """
    return f"{type(exc).__name__}: evolution failed; see server logs"


class _GovernedModelCall:
    """Bind Evolve prompts to the execution and declared model authority it already has.

    No Binding or credential is created here. Container bootstrap owns both;
    each call resolves the operator declaration in this NodeContext's scope.
    The Invocation service remains the only dispatch/replay/usage authority.
    """

    def __init__(
        self,
        *,
        egress: ModelChatEgress,
        bindings: BindingStore,
        declarations: tuple[ModelBindingConfig, ...],
        workspace_id: str,
        default_model: str,
    ) -> None:
        self._egress = egress
        self._bindings = bindings
        self._declarations = declarations
        self._workspace_id = workspace_id
        self._default_model = default_model

    def _binding_id(self, ctx: NodeContext) -> str:
        candidates = [
            declaration
            for declaration in self._declarations
            if (declaration.workspace_id.strip() or self._workspace_id) == ctx.workspace_id
            and declaration.project_id == ctx.project_id
            and declaration.node_id in ("", ctx.node_id)
        ]
        exact = [item for item in candidates if item.node_id == ctx.node_id]
        selected = exact or candidates
        if len(selected) != 1:
            raise BindingNotFound(
                "Evolve model work requires one unambiguous operator-declared model.chat "
                f"Binding for Workspace {ctx.workspace_id!r}, Project {ctx.project_id!r} "
                f"and Node {ctx.node_id!r}"
            )
        return selected[0].binding_id

    @contextmanager
    def for_context(self, ctx: NodeContext) -> Iterator[Callable[..., Any]]:
        """One call sequence per physical Attempt, with a failure fence before publication.

        Benchmarks may catch provider errors and return a score anyway. Retain
        the first failure inside this node only, so no such score is published;
        a later recovery Attempt receives a fresh fence and the same effect keys.
        """
        identity = (
            ctx.run_id,
            ctx.node_run_id,
            ctx.attempt_id,
            ctx.node_id,
            ctx.workspace_id,
            ctx.project_id,
            ctx.user_id,
        )
        if any(not value or not value.strip() for value in identity):
            raise RunIntegrityError("Evolve model work requires a complete canonical NodeContext")
        call_number = 0
        failure: BaseException | None = None
        active = True

        async def call(messages: list[dict[str, Any]] | str, **kwargs: Any) -> str:
            nonlocal call_number, failure
            if not active:
                raise RunIntegrityError("Evolve model callable outlived its NodeContext")
            if failure is not None:
                raise RuntimeError("a prior Evolve model effect failed") from failure
            sequence = call_number
            call_number += 1
            try:
                return await self._complete(ctx, sequence, messages, kwargs)
            except BaseException as exc:
                # A benchmark timeout cancels the callable before swallowing
                # TimeoutError. That also cannot become an accepted score.
                failure = exc
                raise

        try:
            yield call
            if failure is not None:
                raise RuntimeError("Evolve model effect failed") from failure
        finally:
            active = False

    async def _complete(
        self,
        ctx: NodeContext,
        sequence: int,
        messages: list[dict[str, Any]] | str,
        kwargs: dict[str, Any],
    ) -> str:
        binding = await self._bindings.resolve(
            self._binding_id(ctx),
            workspace_id=str(ctx.workspace_id),
            project_id=str(ctx.project_id),
            node_id=ctx.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        request = ModelChatRequest(
            model=kwargs.get("model") or self._default_model,
            messages=(
                [{"role": "user", "content": messages}]
                if isinstance(messages, str)
                else [dict(message) for message in messages]
            ),
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()[:16]
        result = await self._egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=f"evolve.model:{ctx.node_id}:{sequence}:{digest}",
            request=request,
            actor_id=str(ctx.user_id),
        )
        choices = result.body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("evolve: governed gateway returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RuntimeError("evolve: governed gateway returned no content")
        return content


def _default_chat_model() -> str:
    """The deployment's default chat model alias, or "" (router selects).

    The raw egress read ``settings.chat_default_model``; the governed path
    keeps the same default so cutover does not change which model Evolve
    selects — only whose authority the call crosses.
    """
    try:
        from config import get_settings

        return str(get_settings().chat_default_model or "")
    except Exception:
        return ""


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


def select_domain_store() -> Any | None:
    """Pick the durable Evolve domain store this deployment can honestly back (#1064).

    PostgreSQL when the canonical engine's container carries an asyncpg pool
    (``pg_pool`` — the container keeps its SQLite connection, when any, in a
    separate ``db_pool``); sqlite when the canonical spine itself is a sqlite
    file; ``None`` when the
    deployment is memory-backed — where every canonical Run is memory-backed
    too, so a cross-process durable domain ledger would silently pretend a
    durability the spine doesn't have. The recovery contract stays honest:
    a restart of a memory-backed deployment refuses recovery exactly as
    before, via ``EvolveRecoveryBlocked``.
    """
    from services.evolution_graph import CanonicalExecutionUnavailable, canonical_execution_owner

    try:
        owner = canonical_execution_owner()
    except CanonicalExecutionUnavailable:
        return None
    # PostgreSQL is selected only from the asyncpg pool: a SQLite-backed
    # container's ``db_pool`` is a sqlite3 connection (no ``acquire()``), so
    # branching on it would hand the SQLite deployment a Pg store whose
    # ``ensure_schema`` and every later cycle publication fail (Codex review).
    pool = getattr(owner, "pg_pool", None)
    if pool is not None:
        from services.evolve_domain_store import PgEvolveDomainStore

        return PgEvolveDomainStore(pool)
    # Owner doubles in tests (and owners of degraded engines) may carry no
    # config at all; a missing config is just not-sqlite-backed, not an error.
    config = getattr(owner, "config", None)
    database_url = str(getattr(config, "database_url", "") or "") if config else ""
    if database_url.startswith("sqlite:"):
        path = database_url.removeprefix("sqlite:///").removeprefix("sqlite://") or ""
        if path and path != ":memory:":
            from services.evolve_domain_store import SqliteEvolveDomainStore

            return SqliteEvolveDomainStore(path)
    return None


async def start_evolution() -> None:
    global _service
    _service = _EvolutionService()
    # Durable domain first (#1064): attach the store this deployment can
    # honestly back, then restore-or-initialize through it. A deployment with
    # durable state reconstructs the exact population/tournament a stranded
    # Run was admitted against; a memory-backed one keeps the historical
    # fresh init (and its honest recovery refusal).
    _service.attach_domain_store(select_domain_store())
    await _service.restore_or_initialize_domain_state()
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
        self._archive: Any = None
        # Durable Evolve domain store (#1064): the snapshot + publication
        # ledger that lets a genuinely new process reconstruct the exact
        # population/tournament this Run was admitted against. ``None`` keeps
        # the historical process-local behavior for deployments without a
        # durable backend; ``attach_domain_store``/``select_domain_store``
        # wire the production store before the first cycle.
        self._domain_store: Any = None
        self._domain_restore: dict[str, Any] | None = None
        # Fail-closed latch for a failed durable restore (Codex review): while
        # set, the fresh population stays inspectable but execution and
        # publication stay blocked. Admitting a cycle over fabricated state
        # would publish it as the newest admission snapshot and advance the
        # journal watermark past durable battles a later restore must replay.
        self._restore_failed_reason: str | None = None
        # Run ids whose finalize NodeRun carries a durably committed
        # publication marker (#1064). Seeded at restore and refreshed at the
        # start of every recovery tick: the recovery resolver reads this set
        # synchronously (resolver construction has no await point) to tell
        # "the restored population IS this Run's committed post-finalize
        # domain" apart from foreign drift. Sound against staleness because
        # lease fencing hides a live worker's commit from recovery until its
        # lease lapses — and a later tick re-reads the ledger before then.
        self._committed_finalize_runs: set[str] = set()
        # Manual requests and the cadence task share one admission lock. This
        # serializes cycle planning/finalization without making the population
        # store a second execution authority.
        self._cycle_lock = asyncio.Lock()
        self._execution_available = False
        self._availability = "unavailable"
        self._availability_reason: str | None = "canonical engine execution has not been checked"
        self._refresh_execution_availability()

    @property
    def domain_store(self) -> Any:
        """The durable domain snapshot/publication store, or ``None`` (#1064)."""
        # Conservative default for instances built without __init__ (tests,
        # module reloads): no store means the durable choreography is off.
        return getattr(self, "_domain_store", None)

    @property
    def domain_restore(self) -> dict[str, Any] | None:
        """What the last durable domain restore reconstructed, or ``None`` (#1064).

        Honest restart observability: ``/evolution/status`` reports which
        snapshot a restarted process restored (run_id, kind, counts) instead
        of silently presenting a rebuilt population as if it were fresh.
        """
        return getattr(self, "_domain_restore", None)

    @property
    def committed_finalize_run_ids(self) -> set[str]:
        """Run ids with a durably committed finalize publication (#1064)."""
        # Conservative default for instances built without __init__ (tests,
        # module reloads): no committed evidence means the membership checks
        # refuse, never widen.
        return set(getattr(self, "_committed_finalize_runs", None) or ())

    async def refresh_committed_finalize_evidence(self) -> None:
        """Re-read committed finalize markers from the durable ledger (#1064).

        Called at restore time and at the start of every recovery tick so the
        synchronous membership checks in ``_recovery_resolver`` see durable
        committed-finalize evidence for Runs whose publishing process died
        between ``_publish_finalize_committed`` and its Attempt terminal.
        """
        store = self.domain_store
        workspace = self.workspace_id
        if store is None or not workspace:
            return
        list_markers = getattr(store, "list_finalize_markers", None)
        if list_markers is None:
            return
        committed: set[str] = set()
        try:
            for marker in await list_markers(workspace):
                if str(marker.payload.get("status")) == "committed" and marker.run_id:
                    committed.add(str(marker.run_id))
        except Exception as exc:
            # A broken ledger must not silently widen or narrow the refusal:
            # keep the previous evidence (an empty set refuses conservatively).
            logger.warning(
                "Evolve committed-finalize evidence refresh failed: %s", exc, exc_info=True
            )
            return
        self._committed_finalize_runs = committed

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
            logger.warning("Evolution execution unavailable: %s", exc, exc_info=True)
            self._availability_reason = _public_failure(exc)
            return
        # A failed durable restore is a hard stop, not a fallback (Codex
        # review): the fresh population built by the fallback is
        # inspection-only. Only a successful restore re-opens execution.
        if getattr(self, "_restore_failed_reason", None):
            self._execution_available = False
            self._availability = "unavailable"
            self._availability_reason = self._restore_failed_reason
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
            from maistro_evolve.archive import CandidateArchive
            from maistro_evolve.population import PopulationStore
            from maistro_evolve.tournament import EloTournament

            self._population = PopulationStore()
            self._tournament = EloTournament()
            # M4-A6: the candidate archive is Evolve domain state alongside the
            # population/tournament — immutable candidate lineage snapshots,
            # surviving cull/retirement for provenance, branching, and
            # retention evaluation.
            self._archive = CandidateArchive()
        except Exception as exc:
            logger.warning("Evolution population init failed: %s", exc, exc_info=True)
            self._last_cycle_error = _public_failure(exc)
        self._refresh_execution_availability()

    async def restore_or_initialize_domain_state(self) -> bool:
        """Reconstruct the exact domain from the durable store, or fabricate fresh (#1064).

        This is the seam that makes Evolve recovery honest across a genuine
        process restart: a restarted process must not present a fabricated
        fresh population as the domain a stranded Run was admitted against.
        When a durable snapshot exists, this restores the exact serialized
        population/tournament/markers and replays the battle journal rows
        published after that snapshot (deterministic Elo math, so replay is
        exact); the committed finalize markers come back with the snapshot so
        a recovered finalize returns idempotently and a faulted one fails
        closed across the restart. ``False`` means no durable state was
        found (or no store is attached) and the historical fresh-init path
        ran instead.
        """
        if self._population is not None and self._tournament is not None:
            # Already restored or initialized this process; never rebuild a
            # live domain out from under the cycle lock holder.
            return self._domain_restore is not None
        store = self._domain_store
        if store is None:
            # No durable backend this deployment can honestly back: the
            # historical fresh init, recovery refusing as it always has.
            self.initialize_domain_state()
            return False
        workspace_id = self.workspace_id
        if not workspace_id:
            # No durable ledger key: same honest fallback.
            self.initialize_domain_state()
            return False
        try:
            await store.ensure_schema()
            # Restore the newest publication boundary, not "any committed
            # snapshot if one exists". A later cycle's admission snapshot is
            # the compensation base for that cycle and may contain legitimate
            # member changes absent from the previous cycle's committed view.
            snapshot = await store.latest_snapshot(workspace_id)
            snapshot_kind = snapshot.kind if snapshot is not None else "admission"
        except Exception as exc:
            # A broken durable store must not silently downgrade to a fresh
            # fabricated population that anything downstream would trust:
            # recovery membership verification already refuses it, and the
            # fail-closed latch now keeps manual/cadence admission from
            # publishing that fabricated domain as the newest snapshot or
            # advancing the journal watermark past durable battles (Codex
            # review). Fresh init remains for inspection only; only a
            # successful restore re-opens execution/publication.
            logger.warning("Evolve durable domain restore failed: %s", exc, exc_info=True)
            self._restore_failed_reason = (
                "durable domain restore failed; execution blocked until restore succeeds: "
                + _public_failure(exc)
            )
            self._last_cycle_error = _public_failure(exc)
            self.initialize_domain_state()
            return False
        if snapshot is None:
            self.initialize_domain_state()
            return False
        from maistro_evolve.population import PopulationStore
        from maistro_evolve.tournament import EloTournament

        population = PopulationStore()
        tournament = EloTournament()
        (
            replayed_battles,
            replayed_evaluations,
            committed_finalize_runs,
        ) = await self._replay_domain_journal(
            store=store,
            workspace_id=workspace_id,
            snapshot=snapshot,
            population=population,
            tournament=tournament,
        )
        self._population = population
        self._tournament = tournament
        self._cycle_count = snapshot.completed_cycles
        self._committed_finalize_runs = committed_finalize_runs
        self._domain_restore = {
            "run_id": snapshot.run_id,
            "kind": snapshot_kind,
            "population_size": len(population.list_all()),
            "total_battles": tournament.get_stats().get("total_battles", 0),
            "replayed_battles": replayed_battles,
            "replayed_evaluations": replayed_evaluations,
            "completed_cycles": snapshot.completed_cycles,
        }
        self._restore_failed_reason = None
        logger.info(
            "evolve_domain_restored store=%s run=%s kind=%s population=%d battles=%d "
            "replayed=%d evaluations=%d",
            store.backend,
            snapshot.run_id,
            snapshot_kind,
            len(population.list_all()),
            tournament.get_stats().get("total_battles", 0),
            replayed_battles,
            replayed_evaluations,
        )
        self._refresh_execution_availability()
        return True

    async def _replay_domain_journal(
        self,
        *,
        store: Any,
        workspace_id: str,
        snapshot: Any,
        population: Any,
        tournament: Any,
    ) -> tuple[int, int, set[str]]:
        """Fold the durable journal into a freshly restored domain (#1064).

        Evaluation receipts first (they carry the winning publisher's folded
        scores), then battle rows (deterministic Elo math, so replay is
        exact), then the finalize markers (a faulted finalize has no committed
        snapshot, so the admission snapshot's markers predate the fault and
        the fail-closed disposition must survive the restart). Returns
        ``(replayed_battles, replayed_evaluations, committed_finalize_run_ids)``
        with the last feeding the recovery resolver's membership decision.
        """
        from maistro_evolve.durable_snapshot import EvolveDomainExport, restore_domain_state

        restore_domain_state(
            population,
            tournament,
            EvolveDomainExport(
                genomes=snapshot.genomes,
                tournament_state=snapshot.tournament,
                cycle_markers=snapshot.cycle_markers,
            ),
        )
        # Replay exactly the evaluation publications published after this
        # snapshot (#1064). The admission snapshot is pre-cycle: the genomes
        # are unscored, and every evaluation NodeRun the dead process
        # completed has a durable receipt row carrying its folded scores —
        # replaying them reconstructs scored genomes instead of resuming
        # against the unscored admission state. Re-applying is a SET of the
        # receipt's values (the winner's fold, durably recorded), so it is
        # idempotent even when the snapshot already carries them (a committed
        # snapshot pins the journal head past its own cycle's rows).
        from services.evolution_graph import _apply_evaluation_receipt

        replayed_evaluations = 0
        for publication in await store.list_evaluation_publications(
            workspace_id, after_seq=snapshot.last_battle_seq
        ):
            payload = publication.payload
            genome_id = str(payload.get("genome_id", ""))
            genome = population.get(genome_id)
            if genome is None:
                # Culled by a later committed cycle this snapshot already
                # supersedes; its scores have no live genome to land on.
                continue
            population.add(_apply_evaluation_receipt(genome, payload))
            replayed_evaluations += 1
        # Replay exactly the battles published after this snapshot. The
        # journal rows carry their (NodeRun, benchmark) identity, so the
        # rebuilt tournament's publication index answers the idempotency
        # question for a recovered battle Attempt without a second battle.
        replayed_battles = 0
        for publication in await store.list_battle_publications(
            workspace_id, after_seq=snapshot.last_battle_seq
        ):
            payload = publication.payload
            tournament.record_battle(
                benchmark=publication.benchmark,
                genome_a_id=str(payload.get("genome_a_id", "")),
                genome_b_id=str(payload.get("genome_b_id", "")),
                score_a=float(payload.get("score_a", 0.0)),
                score_b=float(payload.get("score_b", 0.0)),
                node_run_id=publication.node_run_id,
                attempt_id=publication.attempt_id,
            )
            replayed_battles += 1
        committed_finalize_runs: set[str] = set()
        for marker in await store.list_finalize_markers(workspace_id):
            population.record_cycle_marker(f"finalize:{marker.node_run_id}", dict(marker.payload))
            if str(marker.payload.get("status")) == "committed" and marker.run_id:
                committed_finalize_runs.add(str(marker.run_id))
        return replayed_battles, replayed_evaluations, committed_finalize_runs

    @property
    def workspace_id(self) -> str | None:
        """The canonical workspace this service's domain state belongs to."""
        from services.evolution_graph import (
            CanonicalExecutionUnavailable,
            canonical_execution_owner,
        )

        try:
            owner = canonical_execution_owner()
        except CanonicalExecutionUnavailable:
            return None
        # Owner doubles may carry no config; an unresolvable workspace simply
        # means no durable ledger key, which callers handle by not restoring.
        owner_config = getattr(owner, "config", None)
        return (
            str(getattr(owner_config, "workspace_id", "") or "") or None if owner_config else None
        )

    def attach_domain_store(self, store: Any) -> None:
        """Attach the durable domain store before the first domain init (#1064).

        Called once at startup, before ``restore_or_initialize_domain_state``.
        Attaching after population/tournament exist would let the durable
        truth and the live memory drift apart, so this refuses instead.
        """
        if self._domain_store is not None:
            return
        if self._population is not None or self._tournament is not None:
            raise RuntimeError(
                "the Evolve domain store must be attached before initialize_domain_state"
            )
        self._domain_store = store

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
    def archive(self) -> Any:
        """The candidate archive (M4-A6) — may be ``None`` before init, like
        ``population``/``tournament``."""
        return self._archive

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
        await self.restore_or_initialize_domain_state()
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
                logger.warning("Evolution cycle failed: %s", exc, exc_info=True)
                self._last_cycle_error = _public_failure(exc)

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
            logger.warning("Evolution cycle refused: %s", exc, exc_info=True)
            self._availability_reason = _public_failure(exc)
            raise EvolutionUnavailableError(
                self._availability_reason,
                availability=self._availability,
            ) from exc
        restore_failed = getattr(self, "_restore_failed_reason", None)
        if restore_failed:
            # The manual admission boundary for the same latch `/status` and
            # the cadence honor: publication must not run over the fabricated
            # fallback domain (Codex review).
            self._execution_available = False
            self._availability = "unavailable"
            self._availability_reason = restore_failed
            raise EvolutionUnavailableError(restore_failed, availability=self._availability)
        if self._population is None or self._tournament is None:
            # Same answer `/status` gives: unavailable, with the reason, as a
            # 503 rather than a bare 500 from a RuntimeError. Checked before
            # importing maistro_evolve so a failed domain init (broken package
            # import) still becomes EvolutionUnavailableError, not ImportError.
            self._execution_available = False
            self._availability = "unavailable"
            self._availability_reason = self._domain_state_reason()
            raise EvolutionUnavailableError(
                self._availability_reason, availability=self._availability
            )
        self._execution_available = True
        self._availability = "executable"
        self._availability_reason = None

        from maistro_evolve.cycle import EvolutionConfig
        from maistro_evolve.harness import EvalHarness

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
            archive=self._archive,
            domain_store=self._domain_store,
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

    def build_llm_call(self) -> _GovernedModelCall:
        """Public accessor so a restart-recovery resolver can reconstruct the
        same llm_call this service would have built for a live cycle (#1064).
        """
        return self._build_llm_call()

    def _governed_llm_seam(self) -> tuple[Any, Any] | None:
        """Use the existing engine model egress and its Container-owned Bindings."""
        try:
            from services.engine import get_engine

            engine = get_engine()
        except RuntimeError:
            return None
        port = getattr(engine, "agent_port", None) or getattr(engine, "_agent_port", None)
        egress = getattr(port, "governed_egress", None)
        container = getattr(port, "container", None)
        if egress is None or getattr(container, "capability_effects", None) is None:
            return None
        return egress, container

    def _build_llm_call(self) -> _GovernedModelCall:
        seam = self._governed_llm_seam()
        if seam is None:
            raise EvolutionUnavailableError(
                "Evolve requires the canonical model egress; raw model fallback is disabled",
                availability="unavailable",
            )
        egress, container = seam
        return _GovernedModelCall(
            egress=egress,
            bindings=container.capability_effects.bindings,
            declarations=tuple(container.config.model_bindings),
            workspace_id=str(container.config.workspace_id),
            default_model=_default_chat_model(),
        )

    def status(self) -> dict[str, Any]:
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
            "archive_size": len(self._archive) if self._archive is not None else 0,
            "last_error": self._last_cycle_error,
            "last_run_id": self._last_run_id,
            "last_run_status": self._last_run_status.value if self._last_run_status else None,
            "tournament": tournament_stats,
            # Honest restart observability (#1064): what durable backend backs
            # the domain (``None`` = process-local only) and, after a
            # restart, exactly which snapshot was restored. A rebuilt
            # population is never presented as a fresh one. getattr, not the
            # attribute: service doubles (and instances built before this
            # change) carry neither field, which reports honestly as
            # process-local/no restore.
            "domain_store_backend": (
                getattr(self._domain_store, "backend", None)
                if getattr(self, "_domain_store", None)
                else None
            ),
            "domain_restore": getattr(self, "_domain_restore", None),
            "restore_failed": getattr(self, "_restore_failed_reason", None),
        }

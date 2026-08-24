"""DI container: wires protocols to implementations.

The Container holds all wired dependencies and provides the main
request entry point via ``route_request()``.

The Conduit pipeline handles the actual request flow:
  classify → route → agent.handle → response
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit, urlunsplit

from maistro.agents.context_builder import ContextBuilder
from maistro.agents.intents import IntentRegistry, build_intent_registry
from maistro.archive.wiring import build_archive_store
from maistro.classifier.engine import ClassifierEngine
from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
from maistro.graph.templates import GraphTemplateStore
from maistro.memory.context_assembly import DefaultContextAssemblyPolicy
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.learnings.extractor import ToolCorrectionExtractor
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.projects.scope_store import ProjectScopeStore
from maistro.projects.store import InMemoryProjectStore
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog, get_default_usage_log
from maistro.router.selector import RouterEngine
from maistro.runs.chat_admission import ChatRunAdmitter, chat_turn_outcome
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import RunStore
from maistro.runs.wiring import wire_chat_admission, wire_execution_spine
from maistro.security.gate import Gate
from maistro.security.outbound import configure_outbound_policy, configured_endpoints
from maistro.security.warden.detector import Warden
from maistro.sessions.store import InMemorySessionStore
from maistro.tasks.admission import WorkspaceRoutingAdmitter
from maistro.types.config import AgentConfig
from maistro.types.errors import AgentError, ConfigError

if TYPE_CHECKING:
    import httpx

    from maistro.a2a.broker import A2ABroker
    from maistro.agents.base import Agent
    from maistro.auth.oauth import (
        IdentityLinker,
        OAuth2Client,
        OAuthProviderConfig,
        SecretResolver,
        StateStore,
    )
    from maistro.capabilities.registry import CapabilityRegistry
    from maistro.events.bus import EventBus
    from maistro.events.durable_log import EventLogStore
    from maistro.events.invocations import InvocationStore
    from maistro.events.processing import HandlerCaller
    from maistro.events.trigger_store import TriggerDefinition, TriggerStore
    from maistro.graph.harness import HarnessAdapter
    from maistro.identity.lifecycle import (
        AgentIdentity as LifecycleIdentity,
    )
    from maistro.identity.lifecycle import (
        CapabilityToken,
        IdentityStore,
        SecretStore,
        TokenStore,
    )
    from maistro.observability.replay import RecordStore, ReplaySession
    from maistro.observability.tiers import PIIDetector
    from maistro.orchestrator.hierarchy import HarnessRegistry, HierarchicalOrchestrator
    from maistro.personas.golden import GoldenRecordStore
    from maistro.projects.store import ProjectStore
    from maistro.protocols.memory import (
        ContextAssemblyPolicy,
        EpisodicStore,
        LearningStore,
        OutcomeStore,
        SessionStore,
    )
    from maistro.protocols.quota import QuotaTracker
    from maistro.protocols.scorer import Scorer
    from maistro.protocols.strikes import StrikeTracker
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter
    from maistro.resilience.p1 import ResiliencePolicyStore
    from maistro.runs.store import RunStore
    from maistro.security._types import AuditLog
    from maistro.security.sentinel.elevation import ElevationStore
    from maistro.security.sentinel.policy import Sentinel
    from maistro.skills.import_pipeline import (
        PolicyAttachmentStore,
        SkillImportRequest,
        SkillImportVerdict,
    )
    from maistro.skills.registry import InMemorySkillRegistry
    from maistro.types.agent import AgentIdentity
    from maistro.types.skill import SkillDefinition

logger = logging.getLogger("maistro.container")


@dataclass
class Container:
    """Holds all wired dependencies."""

    config: AgentConfig
    router: RouterEngine
    classifier: ClassifierEngine
    quota_tracker: QuotaTracker
    learning_store: LearningStore
    learning_extractor: ToolCorrectionExtractor
    outcome_store: OutcomeStore
    session_store: SessionStore
    warden: Warden
    gate: Gate
    sentinel: Sentinel
    context_builder: ContextBuilder
    intent_registry: IntentRegistry
    capabilities: CapabilityRegistry = None  # type: ignore[assignment]  # wired in create_container
    episodic_store: EpisodicStore = None  # type: ignore[assignment]  # wired in create_container
    project_store: ProjectStore = None  # type: ignore[assignment]  # wired in create_container
    # Canonical execution spine (#41): the Project scope tree work is filed in,
    # the Run store that holds its execution identity, and the seam that turns a
    # directly-submitted task into a Run over a one-node Graph.
    project_scope_store: ProjectScopeStore = None  # type: ignore[assignment]
    run_store: RunStore = None  # type: ignore[assignment]
    # Routing rather than bound: one Conductor process serves every Workspace
    # its users belong to, so the Workspace is chosen per submission (#158).
    # `config.workspace_id` remains the default for a submission that names none.
    task_admitter: WorkspaceRoutingAdmitter = None  # type: ignore[assignment]
    #: The seam a chat turn is admitted through (#131). Separate from the task
    #: admitter because the two have different retention: a task's Run is kept
    #: as long as its receipt, a chat turn's is swept behind a small window.
    chat_admitter: ChatRunAdmitter = None  # type: ignore[assignment]
    #: Where a Graph definition comes from when a Run is not trivial work — a
    #: schedule firing, or anything else that instantiates a drawn topology
    #: rather than a one-node stand-in (#132). Optional in the same way the rest
    #: of the spine is: a Container built directly, without `create_container`,
    #: still routes requests — it just cannot resolve a template.
    template_store: GraphTemplateStore | None = None
    context_assembly_policy: ContextAssemblyPolicy = None  # type: ignore[assignment]
    agents: dict[str, Agent] = field(default_factory=dict)
    audit_log: AuditLog | None = None
    conduit: Any = None
    #: The SQLite connection, when that backend is selected.
    db_pool: Any = None
    #: Cold storage for archived records (ADR-082226-f436), or None when the
    #: deployment configured no archive tier. None is the default and an
    #: ordinary answer, not a degraded mode.
    archive_store: Any = None
    #: The asyncpg pool, when PostgreSQL is selected. Separate from `db_pool`
    #: because the two are different objects with different APIs, and code that
    #: branches on "is a database configured" needs to know which.
    pg_pool: Any = None
    # Agent-harness DAG node adapters (dispatch/poll/cancel), keyed by
    # harness_type (e.g. "rsi_cycle"). Empty by default -- see
    # _wire_harness_adapters for why this container never auto-populates
    # "rsi_cycle" itself.
    harness_adapters: dict[str, HarnessAdapter] = field(default_factory=dict)
    spawn_harness_node: AgentSpawnHarnessNode = None  # type: ignore[assignment]
    # Shared quota usage log for any node/hook that needs one (e.g.
    # RsiQuotaPaceTriggerNode via build_node_resolver). Defaults to the
    # process-wide singleton (quota/usage_log.py) so this container and any
    # caller using build_node_resolver's standalone default share state.
    usage_log: InMemoryUsageLog = field(default_factory=get_default_usage_log)
    # Wired in create_container (P1 resilience, ADR-066).
    resilience_policies: ResiliencePolicyStore = None  # type: ignore[assignment]
    # Durable events (ADR-086): bus bridge + log/trigger/invocation stores.
    event_bus: EventBus = None  # type: ignore[assignment]
    durable_event_log: EventLogStore = None  # type: ignore[assignment]
    trigger_store: TriggerStore = None  # type: ignore[assignment]
    invocation_store: InvocationStore = None  # type: ignore[assignment]
    handler_caller: HandlerCaller = None  # type: ignore[assignment]
    # LLM provider registry + cost-aware router (SPEC-070226-cb8d).
    provider_registry: LLMProviderRegistry = None  # type: ignore[assignment]
    llm_router: LLMRouter = None  # type: ignore[assignment]
    # Observability record/replay + PII tier routing (ADR-055).
    record_store: RecordStore = None  # type: ignore[assignment]
    pii_detector: PIIDetector = None  # type: ignore[assignment]
    # Identity lifecycle (ADR-084).
    identity_store: IdentityStore = None  # type: ignore[assignment]
    token_store: TokenStore = None  # type: ignore[assignment]
    secret_store: SecretStore = None  # type: ignore[assignment]
    # A2A delegation broker (ADR-058).
    a2a_broker: A2ABroker = None  # type: ignore[assignment]
    # Hierarchical orchestration across foreign harnesses (ADR-101).
    harness_registry: HarnessRegistry = None  # type: ignore[assignment]
    hierarchy: HierarchicalOrchestrator = None  # type: ignore[assignment]
    # Personas golden records (SPEC-192).
    golden_record_store: GoldenRecordStore = None  # type: ignore[assignment]
    # Skill import pipeline (ADR-083).
    skill_registry: InMemorySkillRegistry = None  # type: ignore[assignment]
    policy_attachment_store: PolicyAttachmentStore = None  # type: ignore[assignment]
    # OAuth (ADR-059): state + identity-link stores; clients via oauth_client().
    oauth_state_store: StateStore = None  # type: ignore[assignment]
    identity_linker: IdentityLinker = None  # type: ignore[assignment]
    # Elevation grants (SPEC-247 / ADR-068 §D). Held here as well as inside
    # Sentinel so a future request/confirm surface has somewhere to persist a
    # cleared grant; Sentinel reads the same instance.
    elevation_store: ElevationStore = None  # type: ignore[assignment]
    # Strike ladder (SPEC-012 / security/gate.py). None unless
    # config.security.strike_tracking_enabled -- see create_container.
    strike_tracker: StrikeTracker | None = None
    durable_event_cursor: int = 0

    def __post_init__(self) -> None:
        if self.conduit is None:
            from maistro.conduit import Conduit as ConduitPipeline

            self.conduit = ConduitPipeline(self)
        if self.capabilities is None:
            from maistro.capabilities.bootstrap import default_capability_registry

            self.capabilities = default_capability_registry()

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        # An armed security control that cannot run is worse than an unarmed
        # one: the operator believes it is enforcing. Both controls this
        # container can arm are keyed on the caller's identity --
        # Gate.process_input derives user_id from auth and skips every strike
        # path when it is empty (security/gate.py:62,64,102), and the ReAct and
        # Artificer strategies guard Sentinel.pre_call with `auth is not None`
        # (agents/strategies/react.py:252). So with auth=None an armed
        # permission table authorizes everything and an armed strike tracker
        # records nothing, silently.
        #
        # Refusing here costs nothing at the shipped defaults (empty table, no
        # tracker -> this never fires) and converts a silent no-op into an
        # unmissable error for anyone who opts in. That is the same defect
        # class this container's permission table was fixed for; it should not
        # reappear one level up.
        if auth is None and (self.sentinel._permission_table or self.strike_tracker):
            armed = []
            if self.sentinel._permission_table:
                armed.append("sentinel permission table")
            if self.strike_tracker:
                armed.append("strike tracking")
            msg = (
                f"route_request() called without auth while {' and '.join(armed)} "
                f"{'are' if len(armed) > 1 else 'is'} armed. These controls key on "
                "the caller identity, so they would silently enforce nothing. "
                "Pass an AuthContext, or disable them in config.security."
            )
            raise AgentError(msg)

        run = await self._admit_chat_turn(
            messages,
            auth=auth,
            session_id=session_id,
            intent_hint=intent_hint,
        )
        try:
            result: dict[str, Any] = await self.conduit.route_request(
                messages,
                auth=auth,
                session_id=session_id,
                intent_hint=intent_hint,
            )
        except BaseException as exc:
            await self._close_chat_run(run, error=str(exc))
            raise
        await self._close_chat_run(run, result=chat_turn_outcome(result))
        if run is not None:
            # Additive. The OpenAI-compatible shape a caller parses is
            # untouched; `run_id` is the handle for anyone who wants to follow
            # the turn through the canonical spine, and is simply absent for a
            # container with no chat admitter wired.
            result["run_id"] = run.run_id
        return result

    async def _admit_chat_turn(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> Run | None:
        """Admit this turn as a canonical Run, or None when none is wired.

        A turn is never refused for want of a Run. The chat path has no receipt
        to fall back on — refusing here would turn "this process cannot record
        the turn" into "this process cannot answer", which is a worse failure
        than an unrecorded answer and not the one #41 asked for.
        """
        if self.chat_admitter is None:
            return None
        try:
            run = await self.chat_admitter.admit(
                messages,
                session_id=session_id,
                intent_hint=intent_hint,
                known_task_types=self.config.task_types,
                actor_principal_id=getattr(auth, "user_id", None) or None,
            )
            # Two hops: a Run is born CREATED and the lifecycle has no edge
            # from there to RUNNING. Queued is momentarily true here — the turn
            # is admitted and about to be dispatched — rather than a fiction
            # invented to satisfy the table.
            await self.run_store.transition_run(run.run_id, RunStatus.QUEUED)
            return await self.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        except Exception:
            logger.warning("chat turn could not be admitted as a Run", exc_info=True)
            return None

    async def _close_chat_run(
        self,
        run: Run | None,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Terminalize a chat turn's Run, whichever way the turn ended.

        A Run left RUNNING is what recovery scans read as a process that died,
        so the one thing this must not do is leave the turn open — including
        when the turn ended by raising, and including when the request itself
        is cancelled. The write is shielded for that last case: `CancelledError`
        is not an `Exception`, so without the shield a client disconnecting
        during this await would abort the transition and leave behind exactly
        the false "died here" signal the shield exists to prevent.
        """
        if run is None:
            return
        target = RunStatus.FAILED if error is not None else RunStatus.COMPLETED
        try:
            await asyncio.shield(
                self.run_store.transition_run(run.run_id, target, result=result, error=error)
            )
        except Exception:
            logger.warning("chat Run %s could not be terminalized", run.run_id, exc_info=True)

    async def process_durable_events(self, *, limit: int = 100) -> int:
        """Tick the durable-event loop (ADR-086): log -> triggers -> handlers.

        Advances and persists the container's replay cursor; safe to call
        repeatedly (idempotent invocations dedupe redelivery).
        """
        from maistro.events.processing import process_events

        self.durable_event_cursor = await process_events(
            self.durable_event_log,
            self.trigger_store,
            self.invocation_store,
            self.handler_caller,
            after_id=self.durable_event_cursor,
            limit=limit,
        )
        return self.durable_event_cursor

    async def list_durable_triggers(self) -> list[TriggerDefinition]:
        """List the durable trigger definitions backing the reactor loop."""
        return await self.trigger_store.list_triggers()

    async def set_durable_trigger_enabled(self, trigger_id: str, enabled: bool) -> None:
        """Enable/disable one durable trigger without removing it."""
        await self.trigger_store.set_enabled(trigger_id, enabled)

    async def durable_invocations_for(self, event_id: int) -> list[Any]:
        """Handler invocations recorded for one durable event (delivery audit)."""
        return list(await self.invocation_store.list_for_event(event_id))

    async def select_model(self, task: Any, budget: Any = None) -> Any:
        """Budget-constrained model selection via the wired cost-aware router."""
        return await self.llm_router.select(task, budget)

    async def select_embedding_model(self, input_size_tokens: int) -> Any:
        """Cheapest available embedding model that fits the input size."""
        return await self.llm_router.select_embedding(input_size_tokens)

    async def get_embedding_model(self, name: str) -> Any:
        """Look up one embedding model in the wired provider registry."""
        return await self.provider_registry.get_embedding_model(name)

    def replay_session(self, trace_id: str, *, accessor: str = "replay") -> ReplaySession:
        """Create a ReplaySession over the wired record store (ADR-055)."""
        from maistro.observability.replay import ReplaySession as _ReplaySession

        return _ReplaySession(self.record_store, trace_id, accessor=accessor)

    async def create_agent_identity(
        self, agent_id: str, *, seed: bytes | str | list[str] | None = None
    ) -> LifecycleIdentity:
        """Bootstrap a did:key identity for an agent (ADR-084)."""
        from maistro.identity.lifecycle import create_agent_identity

        return await create_agent_identity(
            agent_id,
            identity_store=self.identity_store,
            secret_store=self.secret_store,
            seed=seed,
        )

    async def issue_capability_token(
        self,
        agent_id: str,
        target_agent_id: str,
        capability: str,
        ttl_seconds: int = 3600,
    ) -> CapabilityToken:
        """Issue a signed, expiring capability token via the wired stores."""
        from maistro.identity.lifecycle import issue_capability_token

        return await issue_capability_token(
            agent_id,
            target_agent_id,
            capability,
            ttl_seconds,
            identity_store=self.identity_store,
            token_store=self.token_store,
            secret_store=self.secret_store,
        )

    async def verify_capability_token(self, token: CapabilityToken) -> bool:
        """Verify signature, expiry, and revocation against the wired store."""
        from maistro.identity.lifecycle import verify_capability_token

        return await verify_capability_token(token, token_store=self.token_store)

    async def import_skill(self, request: SkillImportRequest, **kwargs: Any) -> SkillImportVerdict:
        """Run the fail-closed skill import pipeline against the wired stores."""
        from maistro.skills.import_pipeline import import_skill

        kwargs.setdefault("warden_scan", self.warden.scan)
        return await import_skill(
            request,
            registry=self.skill_registry,
            policy_store=self.policy_attachment_store,
            **kwargs,
        )

    def verify_skill_payload(self, skill_name: str, payload: str) -> tuple[bool, tuple[str, ...]]:
        """Per-use re-scan + content-hash check for an imported skill."""
        from maistro.skills.import_pipeline import verify_skill_payload

        return verify_skill_payload(skill_name, payload, policy_store=self.policy_attachment_store)

    def persona_scorer(
        self,
        template_path: str,
        eval_index: int = 0,
        *,
        criteria: str = "",
        judge_model: Any = None,
        threshold: float = 0.5,
    ) -> Scorer:
        """Build a persona scorer: LLM judge when available, rubric otherwise.

        Loads the template's Nth eval as the deterministic RubricScorer
        fallback and upgrades to a DeepEval judge only when ``judge_model``
        is supplied and deepeval is importable (SPEC-192 graceful fallback).
        """
        from maistro.personas.scorer import RubricScorer, create_judge_scorer

        fallback = RubricScorer.from_yaml(template_path, eval_index)
        return create_judge_scorer(
            fallback.eval_name,
            criteria or fallback.eval_name,
            fallback=fallback,
            model=judge_model,
            threshold=threshold,
        )

    def oauth_client(
        self,
        providers: dict[str, OAuthProviderConfig],
        http: httpx.AsyncClient,
        secret_resolver: SecretResolver,
    ) -> OAuth2Client:
        """Build an OAuth2 (Auth Code + PKCE) client over the wired stores."""
        from maistro.auth.oauth import OAuth2Client, default_id_token_verifier

        return OAuth2Client(
            providers,
            self.oauth_state_store,
            http,
            secret_resolver,
            id_token_verifier=default_id_token_verifier(),
        )


async def create_container(
    config: AgentConfig,
    *,
    harness_adapters: dict[str, HarnessAdapter] | None = None,
    pg_pool: Any = None,
) -> Container:
    """Wire all dependencies and create the container.

    `harness_adapters`, if given, is passed straight through to
    `_wire_harness_adapters` -- see that function for why this container
    cannot construct a real `RsiCycleHarnessAdapter` (`"rsi_cycle"`) on its
    own and instead leaves the map for the caller to populate.

    `pg_pool`, if given, is a live `asyncpg.Pool` and selects the PostgreSQL
    stores — durable events included (#135). When it is not given and
    `config.database_url` names PostgreSQL, this container opens one itself
    (#122).

    Both paths exist, and the parameter is not vestigial now that the URL path
    works. #135 landed first and could only offer the parameter, because
    deciding which backend a URL names and owning the pool's lifetime was
    #122's work and this container still refused `postgresql://` outright. #122
    closed that. What the parameter still buys is a caller that already holds a
    pool — a test with a fixture, an embedding application that opened its own
    — being able to hand it over rather than have a second one opened against
    the same server.

    A supplied pool wins over the URL. The caller naming a concrete pool is
    more specific than a string saying which server to reach, and silently
    opening a second pool while the given one sat unused is the shape of bug
    that reads as "PostgreSQL is configured and nothing is durable".
    """
    if not config.router_api_key:
        msg = "ROUTER_API_KEY is required."
        raise ConfigError(msg)

    # The outbound guard is on for every request this process makes (#155), so
    # the endpoints it is *supposed* to reach have to be named before the first
    # one. Seeded from configuration rather than a list kept here, so moving a
    # gateway moves its allowance with it.
    from maistro.config.settings import get_settings

    configure_outbound_policy(
        *configured_endpoints(config),
        *configured_endpoints(get_settings()),
    )

    warden = Warden()
    learning_extractor = ToolCorrectionExtractor()
    # Two different handles, deliberately not one. `db_pool` is the SQLite
    # connection the durable-event stores are written against; `pg_pool` is an
    # asyncpg pool. Collapsing them into one `Any` was how the durable-event
    # wiring below came to assume "a database is configured" means "SQLite".
    db_pool: Any = None
    # Held aside before the URL branch runs, because that branch rebinds
    # `pg_pool`. Rebinding it unconditionally — which is what merging #122 into
    # #135 first did — drops the parameter on the floor, and a caller-supplied
    # pool silently becomes in-memory durable events: the exact failure #135
    # exists to have fixed, reintroduced by the change that generalised it.
    supplied_pg_pool = pg_pool
    pg_pool = None
    if config.database_url.startswith("sqlite:"):
        (
            db_pool,
            quota_tracker,
            learning_store,
            outcome_store,
            session_store,
        ) = await _wire_sqlite_backend(config.database_url)
    elif config.database_url.startswith(POSTGRES_SCHEMES):
        (
            pg_pool,
            quota_tracker,
            learning_store,
            outcome_store,
            session_store,
        ) = await _wire_postgres_backend(config.database_url)
    else:
        _require_ephemeral_is_deliberate(config.database_url)
        quota_tracker = InMemoryQuotaTracker()
        learning_store = InMemoryLearningStore()
        outcome_store = InMemoryOutcomeStore()
        session_store = InMemorySessionStore()
    pg_pool = _resolve_pg_pool(supplied=supplied_pg_pool, from_url=pg_pool)
    episodic_store = InMemoryEpisodicStore()
    project_store = InMemoryProjectStore()
    archive_store = build_archive_store(config.archive_url)
    # Built here rather than below, because the admission seam routes on it: a
    # separately-constructed default registry would disagree with the one the
    # rest of the container uses (POC mode, or any custom table).
    intent_registry = build_intent_registry()
    (
        project_scope_store,
        run_store,
        task_admitter,
        graph_template_store,
    ) = await wire_execution_spine(
        db_pool,
        workspace_id=config.workspace_id,
        intents=intent_registry,
        pg_pool=pg_pool,
    )
    chat_admitter = wire_chat_admission(
        run_store,
        project_scope_store,
        workspace_id=config.workspace_id,
        intents=intent_registry,
    )
    context_assembly_policy = DefaultContextAssemblyPolicy(
        episodic_store=episodic_store,
        outcome_store=outcome_store,
        project_store=project_store,
    )

    router = RouterEngine(quota_tracker)
    classifier = ClassifierEngine()
    context_builder = ContextBuilder()

    strike_tracker = _wire_strike_tracker(
        enabled=config.security.strike_tracking_enabled, pg_pool=pg_pool
    )

    gate = Gate(warden=warden, strike_tracker=strike_tracker)

    from maistro.security.permission_policy import (
        build_permission_table,
        describe_permission_table,
    )
    from maistro.security.sentinel.elevation import InMemoryElevationStore
    from maistro.security.sentinel.policy import Sentinel

    audit_log = _wire_audit_log(pg_pool)
    permission_table = build_permission_table(
        preset=config.security.permission_preset,
        permissions=config.security.permissions,
    )
    logger.info("Sentinel permission table: %s", describe_permission_table(permission_table))
    # SPEC-247 / ADR-068 §D. Without this, Sentinel._check_elevation_grant is a
    # permanent no-op, so a grant a human/owner already cleared could never be
    # honoured. Starts empty, and is only consulted AFTER the capability check,
    # the budget check and the BLOCKED check have all already passed -- a grant
    # can therefore never flip authorized False -> True, only needs
    # "self_elevation"/"scoped_2fa" -> "none".
    elevation_store = InMemoryElevationStore()
    sentinel = Sentinel(
        warden=warden,
        permission_table=permission_table,
        audit_log=audit_log,
        elevation_store=elevation_store,
    )

    from maistro.capabilities.bootstrap import default_capability_registry

    capabilities = default_capability_registry()

    # --- P1 resilience policies (ADR-066) --------------------------------
    from maistro.resilience.p1 import InMemoryResiliencePolicyStore, default_policies

    resilience_policies = InMemoryResiliencePolicyStore(default_policies(), include_defaults=False)

    # --- Durable events (ADR-086) ----------------------------------------
    from maistro.events.bus import EventBus
    from maistro.events.durable_log import InMemoryEventLog, append_from_bus_event
    from maistro.events.invocations import InMemoryInvocationStore
    from maistro.events.processing import HTTPHandlerCaller
    from maistro.events.trigger_store import InMemoryTriggerStore

    durable_event_log: EventLogStore
    trigger_store: TriggerStore
    invocation_store: InvocationStore
    # PostgreSQL first: a caller who supplied a pool asked for the durable
    # backend, and `db_pool` (SQLite) may be set at the same time because the
    # two cover different stores. Silently preferring SQLite here would give
    # that caller in-memory-shaped durability on the one backend that can
    # actually be shared between workers.
    if pg_pool is not None:
        (
            durable_event_log,
            trigger_store,
            invocation_store,
        ) = await _wire_pg_durable_events(pg_pool)
    elif db_pool is not None:
        (
            durable_event_log,
            trigger_store,
            invocation_store,
        ) = await _wire_sqlite_durable_events(db_pool)
    else:
        durable_event_log = InMemoryEventLog()
        trigger_store = InMemoryTriggerStore()
        invocation_store = InMemoryInvocationStore()
        if pg_pool is not None:
            # The durable-event stores (ADR-086) have a SQLite implementation
            # and no PostgreSQL one, so a PostgreSQL deployment gets in-memory
            # here even though it configured a durable database. Saying so is
            # the whole point of #122: the operator learns it now rather than
            # after a restart drops the event log, triggers and invocations.
            logger.warning(
                "Durable events are in-memory despite a PostgreSQL backend: the event log, "
                "triggers and invocations are lost on restart. No PostgreSQL implementation "
                "exists yet (#135)."
            )
    handler_caller = HTTPHandlerCaller()

    event_bus = EventBus()

    async def _persist_bus_event(event: Any) -> None:
        # Bridge: every in-memory bus event is appended to the durable log.
        await durable_event_log.append(**append_from_bus_event(event))

    event_bus.subscribe(_persist_bus_event)

    # --- LLM provider registry + cost-aware router (SPEC-070226-cb8d) ----
    from maistro.providers.config import load_provider_registry
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter

    provider_registry = (
        load_provider_registry(config.provider_config_path)
        if config.provider_config_path
        else InMemoryProviderRegistry()
    )
    llm_router = CostAwareRouter(provider_registry)

    # --- Observability record/replay + PII tiers (ADR-055) ---------------
    from maistro.observability.replay import InMemoryRecordStore
    from maistro.observability.tiers import PIIDetector

    record_store = InMemoryRecordStore()
    pii_detector = PIIDetector(mode="prod")

    # --- Identity lifecycle (ADR-084) -------------------------------------
    from maistro.identity.lifecycle import (
        InMemoryIdentityStore,
        InMemorySecretStore,
        InMemoryTokenStore,
    )

    identity_store = InMemoryIdentityStore()
    token_store = InMemoryTokenStore()
    secret_store = InMemorySecretStore()

    # --- Skill registry + import pipeline (ADR-083) ----------------------
    from maistro.skills.import_pipeline import InMemoryPolicyAttachmentStore
    from maistro.skills.registry import InMemorySkillRegistry

    skill_registry = InMemorySkillRegistry()
    policy_attachment_store = InMemoryPolicyAttachmentStore()

    # --- A2A delegation broker (ADR-058) ----------------------------------
    agents: dict[str, Agent] = {}
    a2a_broker = _wire_a2a_broker(agents)

    # --- Hierarchical orchestration (ADR-101) ------------------------------
    harness_registry, hierarchy = _wire_hierarchy(agents, skill_registry)

    # --- Agent-harness DAG node adapters (ADR-062 spawn_harness) -----------
    wired_harness_adapters = _wire_harness_adapters(harness_adapters)
    spawn_harness_node = AgentSpawnHarnessNode(adapters=wired_harness_adapters)

    # --- Personas golden records (SPEC-192) --------------------------------
    from maistro.personas.golden import InMemoryGoldenRecordStore

    golden_record_store = InMemoryGoldenRecordStore()

    # --- OAuth (ADR-059) ----------------------------------------------------
    from maistro.auth.oauth import IdentityLinker, InMemoryIdentityLinkStore, InMemoryStateStore

    oauth_state_store = InMemoryStateStore()
    identity_linker = IdentityLinker(store=InMemoryIdentityLinkStore())

    container = Container(
        config=config,
        router=router,
        classifier=classifier,
        quota_tracker=quota_tracker,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        warden=warden,
        gate=gate,
        strike_tracker=strike_tracker,
        sentinel=sentinel,
        elevation_store=elevation_store,
        context_builder=context_builder,
        intent_registry=intent_registry,
        capabilities=capabilities,
        episodic_store=episodic_store,
        project_store=project_store,
        project_scope_store=project_scope_store,
        run_store=run_store,
        task_admitter=task_admitter,
        chat_admitter=chat_admitter,
        template_store=graph_template_store,
        context_assembly_policy=context_assembly_policy,
        agents=agents,
        audit_log=audit_log,
        archive_store=archive_store,
        db_pool=db_pool,
        pg_pool=pg_pool,
        resilience_policies=resilience_policies,
        event_bus=event_bus,
        durable_event_log=durable_event_log,
        trigger_store=trigger_store,
        invocation_store=invocation_store,
        handler_caller=handler_caller,
        provider_registry=provider_registry,
        llm_router=llm_router,
        record_store=record_store,
        pii_detector=pii_detector,
        identity_store=identity_store,
        token_store=token_store,
        secret_store=secret_store,
        a2a_broker=a2a_broker,
        harness_registry=harness_registry,
        hierarchy=hierarchy,
        harness_adapters=wired_harness_adapters,
        spawn_harness_node=spawn_harness_node,
        golden_record_store=golden_record_store,
        skill_registry=skill_registry,
        policy_attachment_store=policy_attachment_store,
        oauth_state_store=oauth_state_store,
        identity_linker=identity_linker,
    )

    # One word again, and only because this change is what makes it true.
    #
    # #135 had to report the stores and the durable events separately, because
    # `pg_pool` reached the events and not the stores: saying "PostgreSQL" for
    # both would have described a deployment whose learnings and outcomes were
    # still in memory. That is #122's gap, and this branch closes it — a pool
    # now selects PostgreSQL for the learnings, outcome, session and quota
    # stores as well as for the event log, so the two words would always be the
    # same word.
    #
    # The lesson survives the collapse: the line reports what is *wired*, not
    # what was configured. If a future change makes one of these durable
    # without the other, this splits again rather than rounding up.
    if pg_pool is not None:
        backend = "PostgreSQL"
    elif db_pool is not None:
        backend = "SQLite"
    else:
        backend = "InMemory"
    logger.info("Container wired (%s stores)", backend)
    return container


def _wire_audit_log(pg_pool: Any) -> Any:
    """Durable audit log on PostgreSQL, in-memory otherwise.

    The audit log is the one store where losing history on restart is not an
    inconvenience but a hole in the record the log exists to keep. `PgAuditLog`
    is a true drop-in: same `log`/`get_entries` signatures, same `AuditEntry`
    return type — checked, not assumed.
    """
    from maistro.security.sentinel.audit import InMemoryAuditLog

    if pg_pool is None:
        return InMemoryAuditLog()
    from maistro.persistence.pg_audit import PgAuditLog

    return PgAuditLog(pg_pool)


def _wire_strike_tracker(*, enabled: bool, pg_pool: Any) -> StrikeTracker | None:
    """The strike ladder, which stays in-memory even on PostgreSQL — loudly.

    `security.pg_strikes.PgStrikeTracker` looks like a drop-in and is not. Its
    `get()` returns a dict where `Gate` does attribute access on a
    `StrikeRecord`, and its `record_violation()` returns only
    user_id/strike_count/escalated where `Gate` reads scrutiny_level,
    locked_until and disabled as well. Wiring it would raise AttributeError on
    the first security violation — the worst possible place to find out. Making
    it usable needs an adapter, which is #134; until then the operator is told
    that lockout state does not survive a restart rather than left to assume a
    configured database means it does.
    """
    if not enabled:
        return None
    from maistro.security.strikes import InMemoryStrikeTracker

    tracker = InMemoryStrikeTracker()
    logger.info("Strike ladder armed (3-strike escalation via InMemoryStrikeTracker).")
    if pg_pool is not None:
        logger.warning(
            "Strike ladder is in-memory despite a PostgreSQL backend: lockout state "
            "resets on restart. PgStrikeTracker is not yet Gate-compatible (#134)."
        )
    return tracker


#: URL schemes that select the PostgreSQL backend. `postgres://` is the legacy
#: spelling libpq still accepts and operators still write; `+asyncpg` is what
#: SQLAlchemy-shaped configuration produces; `+psycopg` is what
#: `DatabaseSettings.sync_url` produces, and therefore what a `DB_*`-only
#: deployment resolves to. Omitting that last one would send exactly the
#: docker-compose case — five variables, no `DATABASE_URL` — to the in-memory
#: branch, which is the defect #187 exists to have fixed.
POSTGRES_SCHEMES: Final = (
    "postgresql://",
    "postgres://",
    "postgresql+asyncpg://",
    "postgresql+psycopg://",
)

#: Oldest PostgreSQL this engine supports. 17 is the floor because it is the
#: oldest release still receiving fixes for the whole of this project's support
#: window, and because `docker-compose.yml` has always run `pgvector:pg17`.
#: 18 is the recommended version; 19 is expected to work and is where
#: ADR-082226-5104's SQL/PGQ interest points.
MIN_POSTGRES_VERSION: Final = 17

#: Tables the PostgreSQL stores read and write. Checked at startup rather than
#: discovered on the first request — see `_require_postgres_schema`.
_REQUIRED_PG_TABLES: Final = (
    "learnings",
    "outcomes",
    "quota_usage",
    "sessions",
)


def _asyncpg_dsn(database_url: str) -> str:
    """asyncpg speaks libpq DSNs, not SQLAlchemy's `+driver` spelling.

    Delegates to `config.database.to_asyncpg_dsn` rather than restating the
    rewrite: `to_sync_url` and this are the same question asked of two drivers,
    and two copies of the scheme table drift (#187).
    """
    from maistro.config.database import to_asyncpg_dsn

    return to_asyncpg_dsn(database_url)


async def _require_supported_postgres(conn: Any) -> None:
    """Refuse a server too old for the SQL these stores rely on.

    A version check at startup rather than a failure mid-request. The stores use
    `ON CONFLICT ... DO UPDATE` with composite targets, partial unique indexes
    and `JSONB` throughout — nothing exotic, but a server old enough to lack any
    of it should say so once, at the point the operator can act on it.
    """
    version_num = int(await conn.fetchval("SHOW server_version_num"))
    major = version_num // 10_000
    if major < MIN_POSTGRES_VERSION:
        version = await conn.fetchval("SHOW server_version")
        msg = (
            f"PostgreSQL {version} is older than the minimum supported major "
            f"version {MIN_POSTGRES_VERSION}. Supported: {MIN_POSTGRES_VERSION}-19 "
            f"(18 recommended)."
        )
        raise ConfigError(msg)


async def _require_postgres_schema(conn: Any) -> None:
    """Refuse a database that has not been migrated.

    Without this the first request to touch a store raises `UndefinedTableError`
    from somewhere deep in a handler, and the operator sees a 500 rather than
    the one instruction that fixes it. The check is cheap and runs once.
    """
    missing = [
        table
        for table in _REQUIRED_PG_TABLES
        if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if missing:
        msg = (
            f"PostgreSQL is missing {len(missing)} table(s) the engine requires: "
            f"{', '.join(missing)}. Run `alembic upgrade head` against this database."
        )
        raise ConfigError(msg)


def _resolve_pg_pool(*, supplied: Any, from_url: Any) -> Any:
    """Which asyncpg pool the PostgreSQL-backed subsystems should use.

    A supplied pool wins over whatever the URL produced. The caller naming a
    concrete pool is more specific than a string naming a server, and opening a
    second pool against the same database while the given one sits unused is
    how "PostgreSQL is configured and nothing is durable" happens.

    It replaces the pool only. The learnings, outcome, session and quota stores
    are already built by the time this is called and keep whatever the URL
    selected — that split is #122's contract, and #135's is that a caller
    holding a pool can reach the durable-event stores with it.
    """
    return supplied if supplied is not None else from_url


async def _wire_postgres_backend(
    database_url: str,
) -> tuple[
    Any,
    QuotaTracker,
    LearningStore,
    OutcomeStore,
    SessionStore,
]:
    """Open an asyncpg pool and wire the durable PostgreSQL stores (#122).

    ADR-082226-5104 makes PostgreSQL the durable system of record. Until this
    existed, a `postgresql://` URL took the in-memory branch — learnings,
    outcomes, sessions and quota all vanished on restart with nothing said.

    Both preflight checks run against a real connection before any store is
    built, because both failures are configuration errors an operator can fix in
    a minute and neither is diagnosable from the exception it would otherwise
    raise on some later request.
    """
    from maistro.persistence import get_pool
    from maistro.persistence.pg_learnings import PgLearningStore
    from maistro.persistence.pg_outcomes import PgOutcomeStore
    from maistro.persistence.pg_quota import PgQuotaTracker
    from maistro.persistence.pg_sessions import PgSessionStore

    pool = await get_pool(_asyncpg_dsn(database_url))
    try:
        async with pool.acquire() as conn:
            await _require_supported_postgres(conn)
            await _require_postgres_schema(conn)
    except BaseException:
        # A failed preflight means no container, so the pool it opened has no
        # owner. Leaving it holding connections to a database the operator is
        # about to fix is how a retry finds the server still busy.
        from maistro.persistence import close_pool

        await close_pool()
        raise

    pg_learning_store = PgLearningStore(pool)
    # The one store with an ensure_schema: an idempotent ALTER that adds the
    # scope column its queries name. Harmless once the migration has run.
    await pg_learning_store.ensure_schema()

    quota_tracker: QuotaTracker = PgQuotaTracker(pool)
    learning_store: LearningStore = pg_learning_store
    outcome_store: OutcomeStore = PgOutcomeStore(pool)
    session_store: SessionStore = PgSessionStore(pool)

    return pool, quota_tracker, learning_store, outcome_store, session_store


#: Schemes that deliberately select ephemeral in-memory stores.
_EPHEMERAL_SCHEMES: Final = ("memory://",)


def _redact_url(database_url: str) -> str:
    """Drop userinfo from a URL before it goes anywhere it might be read.

    A rejected `database_url` lands in an uncaught startup `ConfigError`, which
    means process logs and whatever collects them. PostgreSQL URLs carry
    `user:password@` as a matter of course, so interpolating the raw value put
    credentials in the logs of every deployment that hit this error — while
    fixing a different silent-failure bug.

    Scheme, host, port and path survive, because those are what makes the error
    diagnosable. An unparseable value is reported as its scheme alone rather than
    echoed: a string urlsplit cannot read is a string this cannot promise to
    redact.
    """
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return f"{database_url.split(':', 1)[0]}:<unparseable>"
    if not parts.netloc:
        return database_url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = "***:***@" if (parts.username or parts.password) else ""
    return urlunsplit((parts.scheme, f"{userinfo}{host}", parts.path, "", ""))


def _require_ephemeral_is_deliberate(database_url: str) -> None:
    """Refuse a configured database this container cannot actually wire (#122).

    Reached only after the durable schemes have been tried: ``sqlite:`` and the
    PostgreSQL schemes each have a backend above, so anything arriving here named
    a database with no wiring behind it. Before #122 such a value fell through to
    in-memory stores, so a deployment set to ``postgres:/typo`` got learnings,
    outcomes, sessions and quota that vanish on restart — with no error, no
    warning, and nothing in the log saying the configured database had been
    ignored. A misconfigured model gives visibly wrong answers; a misconfigured
    database gives correct answers that quietly disappear, which is the worse
    failure and the one `graph_runner.StubLLMNotAllowedError` exists to prevent
    elsewhere.

    Three cases, deliberately distinguished:

    - **unset** — no database was asked for, so in-memory is the honest answer.
      Logged at warning so an operator who *meant* to configure one can see it.
    - **``memory://``** — ephemeral on purpose. Silent, because it was chosen.
    - **anything else** — a database was configured and cannot be honoured.
      That is a configuration error, not a degraded mode to paper over.
    """
    if not database_url.strip():
        logger.warning(
            "No database_url configured; using in-memory stores. Learnings, outcomes, "
            "sessions and quota will not survive a restart. Set database_url to a "
            "postgresql:// or sqlite:///path/to/file.db URL for durability, or "
            "memory:// to select this deliberately."
        )
        return
    if database_url.startswith(_EPHEMERAL_SCHEMES):
        return
    msg = (
        f"database_url {_redact_url(database_url)!r} names a backend this build "
        "cannot wire. Supported: postgresql://user@host/db (durable), "
        "sqlite:///path/to/file.db (durable), sqlite:// (in-memory) and "
        "memory:// (explicitly ephemeral). Falling back to in-memory would "
        "discard the data you configured a database to keep -- see issue #122."
    )
    raise ConfigError(msg)


async def _wire_sqlite_backend(
    database_url: str,
) -> tuple[
    Any,
    QuotaTracker,
    LearningStore,
    OutcomeStore,
    SessionStore,
]:
    """Open a SQLite connection and wire the homelab/single-instance stores.

    ``database_url`` of the form ``sqlite:///path/to/file.db`` (or
    ``sqlite://`` for an in-memory DB) selects this backend instead of the
    default in-memory stores — no Postgres server required.
    """
    import aiosqlite

    from maistro.persistence.sqlite_learnings import SqliteLearningStore
    from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore
    from maistro.persistence.sqlite_quota import SqliteQuotaTracker
    from maistro.persistence.sqlite_sessions import SqliteSessionStore

    path = database_url.removeprefix("sqlite:///").removeprefix("sqlite://") or ":memory:"
    if path == ":memory:":
        # A pathless `sqlite://` is a real SQLite backend and a legitimate dev
        # choice, so it is allowed — but warned, unlike `memory://`. `memory://`
        # is silent because its name announces what it does; this one announces
        # the opposite, and an operator reading "sqlite" reasonably expects a
        # file. The warning lives here rather than in the scheme guard because
        # this line is what makes it true.
        logger.warning(
            "database_url %r has no file path, so SQLite runs in-memory: learnings, "
            "outcomes, sessions and quota will not survive a restart. Use "
            "sqlite:///path/to/file.db for durability, or memory:// to select "
            "ephemeral storage deliberately.",
            database_url,
        )
    conn = await aiosqlite.connect(path)

    sqlite_quota_tracker = SqliteQuotaTracker(conn)
    sqlite_learning_store = SqliteLearningStore(conn)
    sqlite_outcome_store = SqliteOutcomeStore(conn)
    sqlite_session_store = SqliteSessionStore(conn)
    await sqlite_quota_tracker.ensure_schema()
    await sqlite_learning_store.ensure_schema()
    await sqlite_outcome_store.ensure_schema()
    await sqlite_session_store.ensure_schema()

    quota_tracker: QuotaTracker = sqlite_quota_tracker
    learning_store: LearningStore = sqlite_learning_store
    outcome_store: OutcomeStore = sqlite_outcome_store
    session_store: SessionStore = sqlite_session_store

    return conn, quota_tracker, learning_store, outcome_store, session_store


async def _wire_sqlite_durable_events(
    conn: Any,
) -> tuple[EventLogStore, TriggerStore, InvocationStore]:
    """Wire the durable-event stores onto the already-open SQLite connection."""
    from maistro.events.durable_log import SqliteEventLog
    from maistro.events.invocations import SqliteInvocationStore
    from maistro.events.trigger_store import SqliteTriggerStore

    sqlite_event_log = SqliteEventLog(conn)
    sqlite_trigger_store = SqliteTriggerStore(conn)
    sqlite_invocation_store = SqliteInvocationStore(conn)
    await sqlite_event_log.ensure_schema()
    await sqlite_trigger_store.ensure_schema()
    await sqlite_invocation_store.ensure_schema()
    return sqlite_event_log, sqlite_trigger_store, sqlite_invocation_store


async def _wire_pg_durable_events(
    pool: Any,
) -> tuple[EventLogStore, TriggerStore, InvocationStore]:
    """Wire the durable-event stores onto a caller-supplied `asyncpg.Pool` (#135).

    All three share one pool rather than opening their own, matching
    `persistence/pg_*` and leaving connection lifetime with the caller — which
    also means a single `ensure_event_schema` covers all three tables, instead
    of three `ensure_schema()` calls racing `CREATE TABLE IF NOT EXISTS` across
    pool connections the way the SQLite twin's serial calls cannot.
    """
    from maistro.events.pg_stores import (
        PgEventLog,
        PgInvocationStore,
        PgTriggerStore,
        ensure_event_schema,
    )

    await ensure_event_schema(pool)
    return PgEventLog(pool), PgTriggerStore(pool), PgInvocationStore(pool)


def _wire_a2a_broker(agents: dict[str, Agent]) -> A2ABroker:
    """Wire the A2A broker over the container's live agent map.

    The resolver and invoker are small adapter closures over ``agents`` —
    the broker itself stays DI-clean (it never sees the container).
    """
    from maistro.a2a.broker import A2ABroker, A2AError, DelegationBudget, LocalTransport
    from maistro.a2a.delegate import A2ATask
    from maistro.agents.catalog import AgentCard

    class _AgentMapCardResolver:
        def resolve(self, agent_id: str, user_id: str = "") -> AgentCard | None:
            agent = agents.get(agent_id)
            if agent is None:
                return None
            return AgentCard.from_identity(agent.identity, user_id=user_id)

    async def _invoke(task: A2ATask, budget: DelegationBudget) -> str:
        agent = agents.get(task.to_agent)
        if agent is None:
            raise A2AError(f"unknown local agent '{task.to_agent}'")
        response = await agent.handle(
            [{"role": "user", "content": task.task}],
            auth=None,
            session_id=budget.trace_id,
        )
        # LocalTransport maps "no exception" to TaskStatus.COMPLETED, so a
        # failed run has to be re-raised here or a delegation that never ran
        # would be recorded as a success carrying an apology string.
        if response.failed:
            raise A2AError(f"local agent '{task.to_agent}' failed: {response.error}")
        if response.blocked:
            raise A2AError(f"local agent '{task.to_agent}' blocked: {response.block_reason}")
        return response.content

    return A2ABroker(resolver=_AgentMapCardResolver(), local=LocalTransport(_invoke))


def _wire_hierarchy(
    agents: dict[str, Agent],
    skill_registry: InMemorySkillRegistry,
) -> tuple[HarnessRegistry, HierarchicalOrchestrator]:
    """Wire hierarchical orchestration with a loopback transport.

    The AgentSource adapter resolves an agent name from the container's live
    agent map and its skill names from the wired skill registry; connecting
    real foreign harnesses is a deployment concern (register advertisements
    on the returned registry and connect transport handlers).
    """
    from maistro.orchestrator.hierarchy import (
        HierarchicalOrchestrator,
        HierarchyError,
        InMemoryHarnessRegistry,
        LoopbackHarnessTransport,
    )

    class _AgentMapSource:
        async def resolve(self, agent_name: str) -> tuple[AgentIdentity, list[SkillDefinition]]:
            agent = agents.get(agent_name)
            if agent is None:
                raise HierarchyError(f"unknown local agent '{agent_name}'")
            skills = [
                skill
                for name in agent.identity.skills
                if (skill := skill_registry.get(name)) is not None
            ]
            return agent.identity, skills

    registry = InMemoryHarnessRegistry()
    orchestrator = HierarchicalOrchestrator(
        registry=registry,
        transport=LoopbackHarnessTransport(),
        agent_source=_AgentMapSource(),
    )
    return registry, orchestrator


def _wire_harness_adapters(
    overrides: dict[str, HarnessAdapter] | None,
) -> dict[str, HarnessAdapter]:
    """Wire the `agent.spawn_harness` node's adapter map.

    Unlike `_wire_a2a_broker`/`_wire_hierarchy`, this has no default
    population of its own. `RsiCycleHarnessAdapter` (`maistro-rsi`, a
    downstream package this one cannot depend on -- `maistro-core` is the
    shared library `maistro-rsi` imports, never the reverse) wraps `RsiCycle`,
    whose `RsiCycleConfig` requires a real `repo_url` + `test_command`: exactly
    the deployment-specific information a generic, `AgentConfig`-driven
    container has no way to source safely. Fabricating placeholder values
    would risk running RSI's self-modifying git operations against a wrong or
    fake repo, so this stays an empty seam by default. Callers that do have
    real RSI deployment config construct their own `RsiCycleHarnessAdapter`
    and pass it via `create_container(config, harness_adapters={"rsi_cycle": ...})`.
    """
    return dict(overrides or {})


def build_node_resolver(
    *,
    harness_adapters: dict[str, HarnessAdapter] | None = None,
    usage_log: InMemoryUsageLog | None = None,
    a2a_delegator: Any = None,
    guest_peers: Any = None,
    run_store: RunStore | None = None,
) -> Callable[[str, Any], Any]:
    """Build the production durable-executor node resolver.

    Canonical durable execution supplies a ``Graph``. Raw DAG dictionaries
    remain accepted only as a definition-layer compatibility seam while
    DagRegistry callers are projected onto canonical Graph at their product
    boundary. Dependency-injected node kinds and plain registry nodes share
    the same resolution path in either representation.

    ``run_store`` is the **canonical** `maistro.runs.store.RunStore`
    (``get_run``/``create_run``/``transition_run``), not the durable executor's
    `DurableRunStore` (``get``/``create``/``update``). The two names are close
    enough to swap by accident, they share no method, and the parameter was
    typed ``Any``: passing the executor's `InMemoryDurableRunStore` type-checked
    and then raised `AttributeError` on the first accepted delegation, after the
    work had already been dispatched. The annotation is the fix -- there is no
    adapter here, because a `DurableRunRecord` is a checkpoint of one graph
    execution and a `Run` is the execution's canonical identity, and pretending
    either can stand in for the other is what produced the confusion.
    """
    from maistro.graph.definitions import Graph
    from maistro.graph.nodes import get_node
    from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
    from maistro.graph.nodes.rsi_quota_pace_trigger import RsiQuotaPaceTriggerNode

    resolved_adapters = harness_adapters if harness_adapters is not None else {}
    resolved_usage_log = usage_log if usage_log is not None else get_default_usage_log()

    def _resolver(node_id: str, graph: Any) -> Any:
        kind = ""
        if isinstance(graph, Graph):
            spec = next((node for node in graph.nodes if node.node_id == node_id), None)
            if spec is None:
                raise KeyError(node_id)
            kind = spec.node_type
        elif isinstance(graph, dict):
            for raw in graph.get("nodes", []):
                if str(raw.get("id")) == node_id:
                    kind = str(raw.get("kind", ""))
                    break
            else:
                raise KeyError(node_id)
        else:
            raise TypeError("node resolver requires canonical Graph or raw DAG snapshot")

        if kind == "agent.spawn_harness":
            return AgentSpawnHarnessNode(adapters=resolved_adapters)
        if kind == "rsi.quota_pace_trigger":
            return RsiQuotaPaceTriggerNode(resolved_usage_log)
        if kind == "agent.delegate_remote":
            # Previously fell through to `get_node(kind)()`, which constructs
            # the node with `a2a_delegator=None` and `guest_peers=None` -- so in
            # the only resolver production uses, every delegation returned
            # `status="failed"` with "no a2a_delegator configured". A returned
            # failure reads like the target agent declining, so nothing
            # surfaced it (#147). `run_store` is what lets the node file the
            # delegated work as a canonical child Run.
            return AgentDelegateRemoteNode(
                a2a_delegator=a2a_delegator,
                guest_peers=guest_peers,
                run_store=run_store,
            )
        return get_node(kind)()

    return _resolver

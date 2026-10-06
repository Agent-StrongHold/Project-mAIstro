"""Explicit Vulture references for framework/public surfaces in maistro-core.

This module is quality-scanner input only. ``maistro-core`` packages only
``src/maistro``, so this file is not shipped in the wheel. Vulture scans the
whole ``src`` directory and therefore sees these references to symbols whose
usage is implicit through Pydantic or intentionally external through the public
Invocation execution API.
"""

from maistro import identity as identity_package
from maistro.a2a.external import ExternalAgentRegistry
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.cli._extensions import extensions_history, extensions_show
from maistro.container import Container
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import (
    ExtensionInstallStore,
    InMemoryExtensionInstallStore,
)
from maistro.extensions.ui import (
    GovernedActionCall,
    RenderedComponent,
    SandboxPolicy,
    UiProjectionService,
)
from maistro.governance.promotion import PromotionContract, PromotionLedger
from maistro.graph.harness_targets import HarnessEvolutionProposal, HarnessTargetKind
from maistro.identity import __getattr__ as identity_getattr
from maistro.identity._crypto import ConductorSeed, DerivedKey
from maistro.identity.principal import Principal
from maistro.memory.learnings.approval import LearningApprovalGate
from maistro.memory.learnings.lifecycle import InMemoryLearningLifecycle
from maistro.memory.working.protocol import WorkingMemoryStats
from maistro.ontology.rubric import (
    PassFailScale,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
    RubricSemantic,
)
from maistro.projects.rubric_store import RubricStore
from maistro.runs.model import EvalJudge, EvalMethod, RunEvalScore
from maistro.runs.pg_store import PgRunStore
from maistro.runs.scoped_reads import ScopedRunReader
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore, RunStore
from maistro.state import PersistedStore
from maistro.workspaces.campaigns.model import (
    Actor,
    AreaRef,
    BacklogItemView,
    CampaignDefinition,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
    ParkUnpark,
)
from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore
from maistro.workspaces.campaigns.store import CampaignSelector

# OpenTelemetry API keywords mirrored by the Protocol signature in
# maistro.observability.telemetry_safety.TelemetryTracer. The keywords are
# the API contract callers pass (``record_exception=False`` disables vendor
# exception export), so the parameters are referenced here rather than
# renamed or dropped.
record_exception = "record_exception"
set_status_on_exception = "set_status_on_exception"

_VULTURE_REFERENCES = (record_exception, set_status_on_exception)

# EvalSummary's projection field (#792). A frozen-dataclass instance attribute:
# a class-object reference would not typecheck, so the whitelist below names it
# through this module variable instead. The name is distinctive enough to be
# safe at name level.
latest_by_dimension = "latest_by_dimension"

_VULTURE_WHITELIST = (
    # P0.1 identity split (#53): Principal is always importable; crypto and lifecycle
    # symbols load through __getattr__ and ConductorSeed's public API.
    identity_getattr,
    Principal.from_legacy_dict,
    Principal.to_legacy_dict,
    ConductorSeed.from_mnemonic,
    ConductorSeed.derive_named,
    ConductorSeed.did_key,
    ConductorSeed.mnemonic_words,
    ConductorSeed.zero,
    DerivedKey.curve,
    Binding._validate_binding,
    ResolvedBinding._validate_resolved,
    ResolvedBinding.provider_trust_tier,
    ResolvedBinding.resolved_at,
    Invocation._validate_invocation,
    InvocationExecutionService.invoke,
    # PersistedStore's atomic username-claim transactions (#1061). The durable
    # backend is reached from packages/hive-conductor's username_registry via
    # getattr(backend, ...) duck-typing, so no scanned call site names these
    # methods; they are the production allocation/rollback boundary, not dead
    # code.
    PersistedStore.delete_raw_with_unique_claims,
    PersistedStore.put_raw_with_unique_claims,
    # The scoped canonical Run read seam (#1152) is consumed by Hive's
    # backend (services/engine.py, services/dag_run_inspection.py), which
    # this `packages/*/src` scan does not walk.
    Container.run_reader,
    ScopedRunReader.get_runs,
    # Workspace work campaigns (#103, SPEC-092626-1831). Pydantic invokes the
    # validators; the Actor-valued fields are serialization surface written
    # through model_dump_json and read by consumers outside this scan (the
    # HTTP API responses and the importing product's UI).
    Actor._require_identity,
    AreaRef._require_value,
    BacklogItemView._require_identity,
    CampaignDefinition._require_campaign_text,
    ControlRecord._scope_matches_kind,
    ParkEvidence._require_reason,
    CampaignDefinition.created_by,
    ControlRecord.set_by,
    ControlRecord.cleared_by,
    ItemPolicyRecord.updated_by,
    ParkRecord.parked_by,
    ParkUnpark.unparked_by,
    # The retention deletion path is resolved dynamically by
    # scripts/check-durable-table-inventory.py from
    # quality/durable-table-retention.json; no scanned call site names it.
    SqliteCampaignStore.delete_campaign,
    # The selection entrypoint is the contract's public face (#804 persistent
    # Workspace Agent now, #50 RSI later). Consumers live outside this scan
    # until those issues land; the contract ships first by design.
    CampaignSelector.eligible_items,
    CampaignSelector.select_next,
    # Conductor identity extras (ADR-021): the package-level lazy loader is
    # part of the recoverability contract of the optional `identity` extra.
    # The loader is exercised by every `maistro.identity.ConductorSeed`-style
    # access those consumers make; it is referenced in both import spellings
    # (`identity_getattr` above and the package-qualified form here) so the
    # scanner sees the symbol whichever way a consumer reaches it.
    identity_package.__getattr__,
    # Working-memory observability snapshot (#301, ADR-082226-5104 §5): the
    # frozen stats surface is read by operators and the conformance suite
    # (stats.degraded_reason is the honest "what is not serving" field); no
    # scanned src path reads every field. The references are static scanner
    # input (this module never executes), so instance-only dataclass fields
    # are fine to name directly.
    WorkingMemoryStats.index_terms,  # type: ignore[misc]
    WorkingMemoryStats.embedded_records,  # type: ignore[misc]
    WorkingMemoryStats.degraded_reason,  # type: ignore[misc]
    # EPIC M4-E (#25): the closed evolvable-harness-component vocabulary and
    # the proposal's Pydantic model validators. Members are the serialized
    # values an optimizer's proposal carries (the same posture as the ledger's
    # schema-enum-member rule: enum members are serialized values that need
    # not appear as direct reads in package-local static analysis); the
    # validators run at proposal construction. Their in-tree consumers are the
    # #783/#822 child streams, outside this scan until those issues land.
    HarnessTargetKind.PROMPT,
    HarnessTargetKind.TOOL_SELECTION,
    HarnessTargetKind.SKILLS,
    HarnessTargetKind.MEMORY_RETRIEVAL_POLICY,
    HarnessTargetKind.PLANNING_STRATEGY,
    HarnessTargetKind.SUBAGENT_DEFINITIONS,
    HarnessTargetKind.GRAPH_TOPOLOGY,
    HarnessTargetKind.AUTHORIZED_CODE,
    HarnessEvolutionProposal._identifier_fields_are_not_blank,
    HarnessEvolutionProposal._candidate_edges_reference_candidate_nodes,
    # Eval scores as Run evidence on the canonical spine (M7-A3, #792).
    # The store write/read seam is reached by the scoring caller inside the
    # producing execution and by the #779 family-consistency reader, both
    # outside this `packages/*/src` scan; the contract ships first by design,
    # like CampaignSelector above. The Pydantic validators are invoked
    # implicitly; the enum members and fields are serialization surface
    # written through model_dump_json — `HUMAN` waits on the HITL fence
    # (M7-A5) and `MODEL_JUDGE` rides Capability → Provider → Binding.
    RunStore.record_eval_score,
    RunStore.get_eval_score,
    InMemoryRunStore.record_eval_score,
    InMemoryRunStore.get_eval_score,
    SqliteRunStore.record_eval_score,
    SqliteRunStore.get_eval_score,
    PgRunStore.record_eval_score,
    PgRunStore.get_eval_score,
    EvalMethod.MODEL_JUDGE,
    EvalMethod.HUMAN,
    EvalJudge._validate_judge,
    RunEvalScore._validate_eval_score,
    RunEvalScore.raw_score,
    RunEvalScore.evidence_pointers,
    # A frozen-dataclass instance attribute (#792): named via the module
    # variable above rather than a class-object reference, which would not
    # typecheck.
    latest_by_dimension,
    # Learning promotion approval gate (ported from Stronghold). The promoter's
    # gated flow (LearningPromoter._check_with_gate) queues approvals and
    # consumes get_approved_ids()/mark_promoted; the admin verbs themselves are
    # the review surface for the humans approving those queued promotions —
    # exercised by tests/memory/learnings/test_approval.py and consumed by the
    # Stronghold port, both outside this packages/*/src scan. `reject`,
    # `get_pending` and `get_all` are banked in quality/vulture-baseline.json;
    # `approve` rode along unflagged only because the RSI CLI happened to bind
    # a local named `approve` to its argparse subparser (name-level matching),
    # and #110's review-verb refactor replaced that binding — so name it here,
    # explicitly, for the same reason as its siblings.
    LearningApprovalGate.approve,
    # Learning lifecycle (M4-B4, #120, SPEC-282). The revisable-learning
    # contract ships first: its in-tree consumers are its tests, and the
    # durable ledger twins plus the orchestrator/retrieval wiring that calls
    # these follow, as they did for the episodic store's dynamics. Same
    # "contract ships first by design" posture as CampaignSelector and the
    # eval-score seam above.
    InMemoryLearningLifecycle.weaken,
    InMemoryLearningLifecycle.record_contradiction,
    InMemoryLearningLifecycle.resolve_conflict,
    InMemoryLearningLifecycle.supersede,
    InMemoryLearningLifecycle.retire,
    InMemoryLearningLifecycle.evidence_for,
    InMemoryLearningLifecycle.revisions_for,
    # Goal `Rubric` as a first-class ontology kind (M7-A2, #791). The issue
    # ships persistence + ontology only — its stop condition ("Do not score
    # anything in this PR") defers the consumers to later M7 work, so the
    # store methods' callers (eval scoring, the acceptance fence) are outside
    # this `packages/*/src` scan; the contract ships first by design, like
    # CampaignSelector above. The Pydantic validators are invoked implicitly
    # at validation time; the fields are contract vocabulary (id, name,
    # weight, scale, method, evidence_required; pass/fail gate; authorship
    # provenance) serialized through model_dump_json and read by those
    # deferred consumers.
    RubricScale._at_least_one,
    RubricProvenance._pack_shape,
    RubricSemantic._dimension_consistency,
    PassFailScale.pass_value,
    PassFailScale.fail_value,
    RubricDimension.evidence_required,
    RubricGate.pass_threshold,
    RubricProvenance.authored_by,
    RubricStore.update_dimensions,
    RubricStore.instantiate_from_catalog,
    RubricStore.record_run_binding,
    RubricStore.binding_for_run,
    # The one governed promotion contract (M4-A9, #116; ADR/SPEC-100126-a9c4).
    # The contract ships first by design, the same posture as
    # CampaignSelector and the learning lifecycle above: its in-tree consumers
    # are its tests (tests/governance/test_promotion_contract.py), and each
    # family's store minting PromotionRecords is the spec's recorded follow-up
    # (family-mapping table, "Record adoption: follow-up"; Non-goals:
    # "migration of existing stores to the ledger"). `promote` is the only
    # sanctioned append path; `attach_effect` and `mark_reversed` are the
    # AC-6 effect-traceability and reversal surfaces those adoptions will call.
    PromotionContract.promote,
    PromotionLedger.attach_effect,
    PromotionLedger.mark_reversed,
    # Governed extension registry persistence (M9-B1, #952). The write side of
    # the contract ships first by design: the inspect→authorize→install flow
    # that calls `register_publisher`/`record_install` is #953 and the
    # pin/upgrade/rollback lifecycle is #954, so until those land the write
    # methods' in-tree consumers are the conformance suite
    # (packages/maistro-core/tests/extensions/). `ensure_schema` is the
    # initialization step a store consumer runs on open, reached dynamically
    # from wiring and the conformance fixture rather than a scanned call site.
    # The `maistro extensions` read commands are invoked through typer
    # dispatch, the same surface the ledger's maistro-cli-command-surface rule
    # classifies.
    ExtensionInstallStore.register_publisher,
    ExtensionInstallStore.record_install,
    InMemoryExtensionInstallStore.register_publisher,
    InMemoryExtensionInstallStore.record_install,
    SqliteExtensionInstallStore.register_publisher,
    SqliteExtensionInstallStore.record_install,
    SqliteExtensionInstallStore.ensure_schema,
    # The exact-identity read seam of the same contract: the #953 install
    # flow and the pin/upgrade/rollback lifecycle (#954) look records up by
    # full identity, while the CLI read commands filter history by name and
    # version; until those consumers land, the method's callers are the
    # conformance suite. Same contract-ships-first posture as the write
    # methods above.
    ExtensionInstallStore.get_install,
    InMemoryExtensionInstallStore.get_install,
    SqliteExtensionInstallStore.get_install,
    extensions_history,
    extensions_show,
    # External Agent discovery (M9-D1, #958). The registry's lifecycle API
    # ships first by design, the same contract-first posture as the M9-B1
    # store seams above: its in-tree consumers are the conformance suite
    # (packages/maistro-core/tests/a2a/test_external_agents.py), and the
    # caller that binds external delegation to canonical Runs is M9-D2
    # (#959). `refresh` is the only mutation path for changed descriptor
    # bytes (policy-evaluated broadening, `refresh_descriptor`); `report_availability` records
    # health-probe evidence; `eligible_specialists` is the read the
    # delegation binder will filter through. Until #959 lands, no scanned
    # production call site names them — by construction, since discovery is
    # deliberately decoupled from invocation.
    ExternalAgentRegistry.refresh_descriptor,
    ExternalAgentRegistry.report_availability,
    ExternalAgentRegistry.eligible_specialists,
    # Governed UI/A2UI extension components (M9-F2, #967). The projection
    # contract ships first by design, the same contract-first posture as the
    # M9-B1 store seams and the M9-D1 registry above. `render_component` is
    # the single-component read the HTTP/UI seam calls (the multi-component
    # `render` already has its in-tree caller shape); its consumers are the
    # host's surface layer, outside this packages/*/src scan until the UI
    # packs land (#968). The SandboxPolicy directive fields are read through
    # the closed directive table (`to_csp` walks them via getattr), and
    # `sandbox_csp`/`permissions_required` are serialized projection surface
    # consumed by the rendering client and the host's seam executor — the
    # same posture as the ledger's schema-field rule: contract vocabulary
    # need not appear as direct scans in package-local analysis.
    SandboxPolicy.script_src,  # type: ignore[misc]
    SandboxPolicy.style_src,
    SandboxPolicy.img_src,
    RenderedComponent.sandbox_csp,  # type: ignore[misc]
    GovernedActionCall.permissions_required,  # type: ignore[misc]
    UiProjectionService.render_component,
)

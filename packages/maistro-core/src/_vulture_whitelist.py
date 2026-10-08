"""Explicit Vulture references for framework/public surfaces in maistro-core.

This module is quality-scanner input only. ``maistro-core`` packages only
``src/maistro``, so this file is not shipped in the wheel. Vulture scans the
whole ``src`` directory and therefore sees these references to symbols whose
usage is implicit through Pydantic or intentionally external through the public
Invocation execution API.
"""

from maistro import identity as identity_package
from maistro.a2a.external import ExternalAgentRegistry
from maistro.backlog.markdown_io import ParsedItem
from maistro.backlog.model import (
    BacklogClaim,
    BacklogClosure,
    BacklogEvent,
    BacklogItem,
    BacklogOrigin,
)
from maistro.backlog.pg_store import PgBacklogStore
from maistro.backlog.sqlite_store import SqliteBacklogStore
from maistro.backlog.store import BacklogStore, InMemoryBacklogStore
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.cli._backlog import RoleChoice
from maistro.cli._backlog import cutover as backlog_cutover_command
from maistro.cli._backlog import import_cmd as backlog_import_command
from maistro.cli._backlog import revert as backlog_revert_command
from maistro.cli._connectors import connectors_describe, connectors_verify
from maistro.cli._extensions import (
    extensions_compat,
    extensions_contract,
    extensions_explain,
    extensions_history,
    extensions_lock,
    extensions_preflight,
    extensions_show,
)
from maistro.container import Container
from maistro.extensions.compat import (
    FEATURE_DEPRECATED,
    FEATURE_REMOVED,
    CompatError,
    ContractRange,
    ContractVersion,
    FeatureStatus,
    IncompatibleContract,
    ensure_compatible,
    parse_contract_range,
    parse_contract_version,
    parse_feature_status,
)
from maistro.extensions.context import ExtensionCancellation, ExtensionConfigView, ExtensionContext
from maistro.extensions.effective_authority import EffectiveAuthority
from maistro.extensions.host import ExtensionHost
from maistro.extensions.isolation import SandboxViolationLog
from maistro.extensions.metering import (
    ExtensionMeter,
    ExtensionQuotaLedger,
    ExtensionUsageEvent,
)
from maistro.extensions.resolution import LockState
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import (
    ExtensionInstallStore,
    InMemoryExtensionInstallStore,
)
from maistro.extensions.tool_skill.registration import ExtensionToolCatalog
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
from maistro.memory.learnings.gauntlet import ChainedGauntlet, IndependentTrialsGauntlet
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
    # --- #102 backlog work-source (maistro.backlog) -----------------------
    # Pydantic invokes these field/model validators at runtime; static import
    # scanning cannot see decorator-based dispatch (same shape as
    # Binding._validate_binding above).
    BacklogClosure._require_non_blank_summary,
    BacklogClosure._require_resolvable_refs,
    BacklogClosure._normalize_closed_at,
    BacklogOrigin._require_non_blank,
    BacklogItem._require_non_blank,
    BacklogItem._status_is_a_defined_value,
    BacklogItem._clean_tags,
    BacklogItem._clean_dependencies,
    BacklogItem._require_positive_revision,
    BacklogItem._enforce_consistency,
    BacklogClaim._require_non_blank_identity,
    BacklogClaim._normalize_timestamps,
    BacklogEvent._require_non_blank_identity,
    BacklogEvent._normalize_at,
    # Declarative model field on BacklogItem: written by every store
    # (created_by=actor), validated at the boundary and serialized into the
    # item/event tables; vulture cannot count model_dump/INSERT serialization
    # as a read (same shape as ResolvedBinding.provider_trust_tier above).
    BacklogItem.created_by,
    # BacklogStore.extend_claim is the port's lease-extension operation,
    # conformance-pinned across all three backends
    # (packages/maistro-core/tests/backlog/test_backlog_store_conformance.py
    # :: expired-lease reclaim and claim exclusivity). Its production
    # consumers are the downstream agent/RSI loops the surface exists for;
    # within this repository no process entry point extends a lease yet.
    BacklogStore.extend_claim,
    InMemoryBacklogStore.extend_claim,
    SqliteBacklogStore.extend_claim,
    PgBacklogStore.extend_claim,
    # ParsedItem.written_block is the parse-record accessor the migration
    # round-trip suite asserts verbatim reconstruction with
    # (test_markdown_migration.py); it is the import-side twin of the
    # exporter's _render_header and is consumed outside the scanned tree by
    # the migration test suite and downstream import tooling.
    ParsedItem.written_block,
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
    # Extension metering/quota public surface (#977, M9-I2). The ledger is
    # consumed at the extension seam by hosts and the test suite; no in-tree
    # src caller exists until extension identity propagation (#976) wires
    # invocation attribution, so the settlement surface
    # (register_policy/release/correct), the read/aggregation surface
    # (totals/breakdown/lineage/policy_balance) and the deployment-step
    # ensure_schema
    # are referenced as the reviewed public API they are. extension_version is
    # attribution payload validated and persisted with every usage row
    # (class-object reference mirrors the WorkingMemoryStats entries below).
    ExtensionMeter.ensure_schema,
    ExtensionMeter.totals,
    ExtensionMeter.breakdown,
    ExtensionMeter.lineage,
    ExtensionQuotaLedger.ensure_schema,
    ExtensionQuotaLedger.register_policy,
    ExtensionQuotaLedger.policy_balance,
    ExtensionQuotaLedger.release,
    ExtensionQuotaLedger.correct,
    ExtensionUsageEvent.extension_version,  # type: ignore[misc]
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
    # The Gauntlet seam (M4-B2, #118): IndependentTrialsGauntlet and
    # ChainedGauntlet are constructed by the embedding host (or tests) and
    # injected into LearningPromoter(gauntlet=...); no scanned call site in
    # `packages/*/src` instantiates them, the same intentionally-external
    # posture as CampaignSelector above. TrialSpec's type vocabulary lives on
    # TrialResult, which the evaluator protocol returns.
    IndependentTrialsGauntlet,
    ChainedGauntlet,
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
    # Canonical public extension contract (M9-A2, #950). The context/lifecycle
    # SDK ships as the extension front door: its callers are external
    # extensions and the conformance suites that pin the contract, both
    # outside this `packages/*/src` scan — the same "contract ships first by
    # design" posture as CampaignSelector and the learning lifecycle above.
    # The runtime wiring that drives extensions from graph execution follows
    # in later M9 work (#950 scope is the contract, not its graph integration).
    ExtensionConfigView.as_dict,
    ExtensionCancellation.from_predicate,
    ExtensionCancellation.wait,
    ExtensionContext.service,
    ExtensionContext.invoke_effect,
    ExtensionContext.report_progress,
    ExtensionHost.activation_context,
    ExtensionHost.invocation_context,
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
    extensions_contract,
    # The lock-state read seam (#957): the upgrade preflight consumes the
    # whole installed set, not one extension's history. The CLI preflight
    # command is its in-tree caller (typer dispatch, same posture as the
    # other `maistro extensions` read commands); the library-level caller is
    # the #957 test suite.
    ExtensionInstallStore.all_installs,
    InMemoryExtensionInstallStore.all_installs,
    SqliteExtensionInstallStore.all_installs,
    extensions_history,
    extensions_preflight,
    extensions_show,
    # The `maistro backlog` cutover lifecycle commands are invoked through
    # typer dispatch (#102), the same surface the ledger's
    # maistro-cli-command-surface rule classifies; the StrEnum members are
    # typer's --role choices, consumed by option parsing.
    backlog_import_command,
    backlog_cutover_command,
    backlog_revert_command,
    RoleChoice.viewer,
    RoleChoice.editor,
    RoleChoice.owner,
    # Deterministic extension dependency resolution (M9-C2, #956). The two
    # `maistro extensions` lock commands are typer-dispatched like the read
    # commands above. `identity_keys` is the restart-equality seam the #953
    # install flow asserts against (lock identity set == installed record
    # set); until that flow lands its callers are the resolution suites in
    # packages/maistro-core/tests/extensions/ — the same
    # contract-ships-first posture as the store seams above.
    extensions_lock,
    extensions_explain,
    LockState.identity_keys,
    # Third-party tool/Skill contracts (M9-E3, #964): the host catalog's
    # exposure and Binding seams are consumed by the products that embed
    # maistro-core (model-facing tool surface, workspace binding flows), not
    # by maistro-core itself; the maistro-core test suite is their caller in
    # this tree. Framework surface, not dead code.
    ExtensionToolCatalog.exposed_tools,
    ExtensionToolCatalog.tool_binding,
    extensions_compat,
    # Extension contract compatibility policy (M9-C1, #955). The negotiation
    # core (`negotiate`, `parse_compat_metadata`, `HostContractMetadata`,
    # `CompatibilityReport.to_dict`) is referenced by the `maistro extensions
    # compat` preflight command, so only the fail-fast form and the
    # low-level parse/version surfaces lack an in-tree caller: they are the
    # API an activating host (#953/#954) and the ext-sdk host binding
    # (#956/#957 preflight/migration reporting) call.
    ensure_compatible,
    parse_contract_range,
    parse_contract_version,
    ContractRange.parse,
    ContractVersion.__str__,
    # The closed feature-lifecycle vocabulary: the `supported` singleton is
    # exercised by HOST_FEATURES; the deprecated/removed states have no live
    # row by design (nothing is deprecated today — the first real
    # deprecation adds a table row, not new code) and are reached by tests
    # plus future policy edits. The parser is the only string→status path.
    FEATURE_DEPRECATED,
    FEATURE_REMOVED,
    parse_feature_status,
    FeatureStatus.__str__,
    CompatError,
    IncompatibleContract,
    # Connector/source SDK (M9-E2, #963). The Typer callbacks are dispatched
    # by registration, and the protocol members below are the public SDK
    # surface out-of-tree connectors implement and call — the same
    # consumed-outside-this-scan posture the core-public-api-surface ledger
    # rule records. SyncEngine.query_items routing keeps query_items called in
    # src; the rest of the SDK surface (dataclass fields, store/protocol
    # members) is exercised by the engine and the shared conformance suite.
    connectors_verify,
    connectors_describe,
    # External Agent discovery (M9-D1, #958). The registry's lifecycle API
    # ships first by design, the same contract-first posture as the M9-B1
    # store seams above: its in-tree consumers are the conformance suite
    # (packages/maistro-core/tests/a2a/test_external_agents.py), and the
    # caller that binds external delegation to canonical Runs is M9-D2
    # (#959). `refresh` is the only mutation path for changed descriptor
    # bytes (policy-evaluated broadening, `refresh_descriptor`);
    # `report_availability` records health-probe evidence;
    # `eligible_specialists` is the read the delegation binder will filter
    # through. Until #959 lands, no scanned production call site names them
    # — by construction, since discovery is deliberately decoupled from
    # invocation.
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
    # Extension sandbox boundary evidence (M9-G2, #970). The bounded,
    # per-identity query is the operational half of "violations are
    # attributable and visible": the M9-G4 disable/quarantine flow consumes
    # it, and until that flow lands its in-tree callers are the runner and
    # conformance suites in packages/maistro-core/tests/extensions/ — the
    # same contract-ships-first posture as the M9-B1 store seams above.
    SandboxViolationLog.violations_for,
    # Effective-authority evidence linkage (M9-G1, #969). `with_execution_context`
    # pins a computed intersection to canonical Run evidence (run/node-run/attempt
    # ids) without mutating the digest-anchored result; its consumers are the
    # Invocation/Run wiring that lands with the M9-G2/G3 enforcement and policy
    # issues. Until then its callers are the conformance suite
    # (packages/maistro-core/tests/extensions/test_effective_authority.py) — the
    # same contract-ships-first posture as the seams above.
    EffectiveAuthority.with_execution_context,
)

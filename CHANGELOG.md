# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions are **lockstep across the monorepo**: every published package carries
the same version as the root `VERSION` file.

**What requires an Unreleased entry (#385).** Any change a user, operator, or
security reviewer can observe from outside the code — API surface or behavior,
CLI, configuration, database schema, dependencies, security posture, and
anything an operator must do differently. Each entry names its category
(`Added`/`Changed`/`Deprecated`/`Removed`/`Fixed`/`Security`, plus
`Dependencies` for upgrades) and links the issue or PR it belongs to
(`(#1234)`); a change with no tracked issue carries `(no linked issue:
<reason>)`. Generated churn (formatting, lockfile regeneration, baseline
re-basing) and purely internal refactors with no observable effect are
excluded by policy and need no entry. The release-consistency gate checks
entry shape, not heading presence; at tag time it refuses to publish an empty
or placeholder-only section.

## [Unreleased]

### Added

- **Named `cross-product-parity` CI job and M1 closeout strict mode
  (#459, partial).** The #459 cross-product parity suite
  (`tests/cross_product_parity`) now runs as its own required `ci.yml` job
  instead of being folded, unnamed, into the general `test` job. A new
  `workflow_dispatch`-only workflow, `cross-product-parity-strict.yml`, runs
  the same suite with `MAISTRO_PARITY_STRICT=1` (M1 closeout mode): under
  that flag, `dependency_assessment` raises `DependencyUnavailable` instead
  of returning a named blocker, so a scenario that only proves its
  dependency missing fails the suite rather than passing it. It is not part
  of the PR check contract — it fails today on the CONDUCTOR_INSPECTION
  blocker until #1036 lands. Four scenarios (Builders/schedule/Evolve
  activation against Conductor, and the #463 golden-fixture check) also gain
  their own permanently-evidenced blockers so a landed product dependency
  alone cannot read as closure evidence while the scenario itself still only
  checks import/source tokens, or — for the golden fixture — feeds the
  fixture's own example back at itself instead of a real product
  observation.

- **Third-party provider adapter SDK with canonical routing and usage semantics (#961).**
  An out-of-tree provider package implements the `ProviderAdapter` normalization
  protocol over a declarative `ProviderAdapterSpec` and registers through
  `maistro.capabilities.provider_adapters.register_adapter_models` — the whole
  integration: declared models join the canonical ADR-079 registry and the
  cost-aware router selects them under unchanged policy, with no core routing
  edit. Adapters hold no HTTP client: the approved model-egress module
  transports them over its one governed POST, injecting the scoped credential
  per the adapter's declared auth style (bearer/header/query); the spec refuses
  secret-shaped fields and userinfo-bearing base URLs, so secrets resolve only
  through the canonical credential authority. Usage, errors (the taxonomy is
  pinned to canonical classification: auth statuses → auth, 429 →
  rate-limited, 5xx → retryable, every other 4xx → permanent),
  and streaming declarations map to canonical interfaces; undeclared
  capabilities (tools, structured output) refuse explicitly before any HTTP;
  health probes feed canonical selection instead of a second circuit breaker.
  Registration runs a shared conformance suite (every declared model, under
  the transport's strict JSON encoder) that both the built-in
  reference adapter and external adapters must pass; a pre-effect
  normalization refusal records as not-applied, never UNKNOWN. Operators wire
  adapters via `AgentConfig.provider_adapters` — one `model.chat` Binding per
  entry with `node_id`/`policy_refs` scoping, the entry's endpoint seeded
  into the outbound policy, boot probes per entry, the reference adapter
  honoring `litellm_url`, and `create_container` accepting a host-registered
  catalog through `provider_adapter_catalog`; configuring an adapter
  authorizes nothing by itself). See ADR-105.

- **The out-of-tree reference extension repository ships four extension families with a shared publish/sign/catalog workflow (#980).**
  `extensions/reference-gallery/` is a third-party-shaped, multi-package
  repository: a `tool`-family connector, a `skill` (with an extension-level
  dependency the catalog resolves), a `capability-provider` model adapter
  written against the ADR-104 provider-adapter SDK contract, and a
  `renderer-plugin` UI pack. `tools/publish.py` builds every package, binds
  each manifest to its wheel's digest, signs the canonical install payload
  with the publisher's Ed25519 key, and emits a deterministic catalog
  snapshot that `resolve_lock`/`materialize_lock` and the governed
  inspect → authorize → install lifecycle consume — wheels, never editable
  source paths. The same reusable extension gates run in CI against the
  gallery's own namespace policy via `--policy`, and the four packages'
  suites are inventoried and collected like the first-party reference
  extension's.

- **The extension SDK boundary is enforced and a reference extension ships outside the
  core tree (#951).** `extensions/namespace-policy.json` declares the public
  package namespace policy — the public SDK root (`maistro_ext_sdk`) versus the
  product-private roots — and `scripts/check-extension-imports.py` enforces it
  statically against every extension package: product-private imports, repo-relative
  imports, `sys.path` repair, undeclared third-party dependencies, and
  underscore-private modules under a public root all fail. The reference extension
  (`extensions/reference-greeter/`) is a buildable out-of-tree package, and
  `scripts/check-reference-extension.py` builds it, installs it into a fresh venv,
  proves the product's own modules are unimportable there, and runs its tests with
  that interpreter. Authoring guide, manifest reference, lifecycle, and capability
  docs live under `docs/extensions/`.

- **API-wide HTTP content negotiation (ADR-076) is implemented (#96).**
  `maistro-server` and hive-conductor now run the shared
  `maistro.api_versioning.VersionNegotiationMiddleware` from `maistro-core`.
  A request selects an API version via `Accept: application/vnd.maistro.vN`,
  an `api_version` query parameter, or an `api_version` JSON body field (in
  that precedence order); every response advertises `Maistro-API-Version`
  and `Maistro-API-Default`; an unsupported selector is answered `406` and a
  malformed one `400` before any route handler runs. A plain-JSON response to
  an Accept-negotiated request is returned as
  `application/vnd.maistro.vN+json`; other media types (including the
  canvas-local `application/vnd.canvas+json;version=2`) are never rewritten.
  Deprecation signalling (`Deprecation`/`Sunset`/`Link`) is wired behind the
  version table; nothing is deprecated. Requests without a selector behave
  exactly as before, plus the two advertisement headers. Health, metrics,
  OpenAPI/docs, and A2A paths do not negotiate. Business routes stay on their
  stable `/v1` mounts; no `/vN` path duplication exists.

### Changed

- **Quality and SAST checks can be retried independently (#1357).** Each Quality
  obligation and SAST scanner has its own job. The existing required check names
  now reject incomplete or unsuccessful dependency results, preserving branch
  protection and merge-queue enforcement. One duplicate credential-authority
  invocation is removed; scanner scopes and proof profiles stay unchanged.

- **Evolve model effects require declared, execution-scoped authority (#1087).**
  Manual/request-scoped Evolve work now resolves an operator-declared `model.chat`
  Binding in its canonical Run's Workspace/Project/Node scope and records the real
  Run, NodeRun, Attempt and admitted actor on each Invocation. Configure a model
  Binding for that Project; missing/ambiguous/disabled authority fails closed.
  The synthetic cycle identities, `agent-runtime` scope and raw HTTP fallback are
  removed. Recovered Attempts reuse completed paid effects without duplicate
  quota, while ambiguous or failed model work cannot publish accepted scores.
  Existing replay-safe population/archive/finalize recovery behavior is retained.
  Unattended cadence actor/readiness remains the separate owner-decision hold
  (#1867); this change does not select a service actor or enable cadence.

- **Advisory DAG-shape proportionality judge failures are explicit, not silent allows (#1191).**
  `LLMProportionalityJudge` no longer collapses a timeout, provider error, malformed response
  envelope, or malformed judgment into `justified=True`. `ProportionalityVerdict` now carries a
  `disposition` (`allow`/`deny`/`unavailable`): every failure path yields `unavailable` with
  `justified=False`, so it can never read as affirmative approval evidence. `evaluate_dag_shape`
  records the degraded policy as a distinct `approved_degraded` `DagShapeVerdict` status (logged,
  counted in the new `maistro_security_advisory_degraded_total` metric,
  `proportionality_disposition="unavailable"`; `can_execute` still true — the critic stays
  advisory and is not an availability dependency). `agent.synth_dag` threads the disposition into
  the child Run's provenance. Hard Warden/Sentinel gates are unchanged and remain authoritative.

- **v1.0 release contract consolidated into canonical planning docs (no linked issue:
  governance realignment).** Stakeholder decisions from the 2026-10-01 architecture
  review now live in [`ROADMAP.md`](ROADMAP.md) (release contract section),
  [`BACKLOG.md`](BACKLOG.md) (`[conductor-402]`–`[conductor-413]`,
  `[engine-112]`–`[engine-115]`), and
  [`docs/architecture/WORKSPACE-CUTOVER-PLAN.md`](docs/architecture/WORKSPACE-CUTOVER-PLAN.md)
  (§9 v1.0 amendments). Workspaces replaces the legacy Conductor page tree; M1
  RunStore unification ([#251](https://github.com/Agent-StrongHold/Project-mAIstro/issues/251))
  gates UI cutover; Evolution UI hidden until v1.2; Stronghold deferred to engine v1.5.

- **Documentation folder realignment (no linked issue: docs hygiene).** Added
  [`docs/README.md`](docs/README.md) navigation map; updated
  [`docs/product/TERMINOLOGY.md`](docs/product/TERMINOLOGY.md),
  [`docs/WAYS-OF-WORKING.md`](docs/WAYS-OF-WORKING.md), and deployment/shipped-surface
  docs for Workspaces naming; marked [`docs/adr/DECISION-BACKLOG.md`](docs/adr/DECISION-BACKLOG.md)
  as a 2026-05 snapshot; completed [`docs/adr/ADR-INDEX.md`](docs/adr/ADR-INDEX.md)
  for all ADRs (`[engine-113]`); fixed stale `docs/analysis/` citations; superseded
  duplicate [ADR-061526-f383](docs/adr/ADR-061526-f383-foreign-harness-adapters-and-portability.md)
  in favor of ADR-101; added AC Defined spec index to [`docs/specs/README.md`](docs/specs/README.md).

### Fixed

- **Hive Graph execution refuses missing canonical authority (#1113).**
  Registered and stored DAGs now require the Container's RunStore and Graph
  continuation owner before admission or execution. Stub/degraded mode reports
  Graph execution unavailability instead of creating process-local Runs.
  Definition/resolver helpers and existing read-only legacy archives remain usable.

- **Prevent competing Graph recovery ticks from stealing a persisted claim (#837).**
  Claim ownership is fenced before orphaned-attempt reconciliation, including
  the WAITING-to-RUNNING activation window. Losing readers leave the owner's
  lifecycle and physical work unchanged; ordinary timer parks release the
  marker and expired claims remain recoverable without redispatch.

- **Rubrics instantiated from pack assets now pin the exact source snapshot
  (#966).** `RubricProvenance` recorded only `pack_id`, so rubrics minted from
  different versions of the same pack were provenance-indistinguishable.
  `RubricProvenance` gained optional `publisher`, `pack_version`,
  `manifest_sha256`, `asset_id`, and `asset_version` fields, and pack rubric
  instantiation populates them from the installed manifest snapshot; catalog
  adoption — which carries no manifest — still records `pack_id` only.

- **Pending HITL discovery is fair instead of filtering after a bounded PAUSED
  prefix (#1109).** `GET /v1/hitl/pending` used to page the generic PAUSED
  listing and filter each page in memory, so `limit` bounded a PAUSED *prefix*
  rather than human work: a run of machine-only pauses longer than one
  request's inspection ceiling hid the human pause behind it from every
  request, each one rereading the same prefix and returning the same empty
  answer. The canonical continuation now carries a pause-kind projection
  (`has_hitl_pause`, maintained beside the deadline projection #1056 uses) on
  every backend — in-memory, SQLite, PostgreSQL (migration 059) — and the
  door pages `list_hitl_paused`, which reads it: human eligibility is decided
  by the store before any page is cut, so no prefix, however long, can stand
  between a person and their work. The projection is an index, not a second
  HITL queue: the durable pause entry stays the source of truth and every
  disclosed record is revalidated against it, with Workspace and Project
  scope still applied from canonical state before disclosure. Deadline-less
  human pauses — invisible to the deadline index — are discoverable, answered
  work leaves the projection on the next read, and repeated requests (and
  restarts) cannot make a pending item vanish by consuming a scan position.
  The Workspace Attention projection, which had duplicated the same
  filter-after-prefix walk against the route's private constants, now walks
  the same canonical `pending_hitl_records` contract. Workspace-wide
  discovery (no Project named) also survives a multi-tenant projection:
  `list_hitl_paused` reports its progress through the projection separately
  from the eligible items it returns (a `ScanPage`, as the due-index scan
  has done since #1098), so a page that assembles to nothing this caller can
  see — another tenant's rows, or a stale projected row — advances the walk
  past itself instead of reading as the end of human work, and a bounded
  walk that stops at its inspection ceiling reports capped, never exhausted.
- **A full Recent Runs page no longer waits on one serialized canonical Run
  read per row (#1333).** Conductor's Recent Runs list overlays canonical
  lifecycle truth through one batched, Workspace-scoped reader call, but the
  reader resolved the page's per-Run lookups with a sequential `await` per id:
  at the supported page cap of 100 and a durable PostgreSQL/SQLite store, one
  dashboard request still serialized up to 100 `get_run` round trips on an
  endpoint built to be polled. `ScopedRunReader.get_runs` now overlaps the
  page's independent lookups (bounded, 16 in flight) while keeping the scoped
  decisions exactly once per Workspace/Project, so the visible-Runs answer and
  its refusal semantics are unchanged; a page resolves in a few overlapping
  waves instead of one wait per row.
- **Chat admission compensation is conditional on the unchanged, unstarted Run (#338).**
  A QUEUED or RUNNING write that commits but loses its response is compensated
  before the existing retryable refusal, without dispatching the turn. The
  stranded-chat sweep now compares the Run snapshot and checks NodeRun absence
  atomically; a concurrent node creation defeats cancellation. SQLite guards
  the physical cancel, node insertion and lifecycle writes against the exact
  persisted parent snapshot, including when a sibling store commits on its
  shared connection. Validation refusals preserve sibling writes. This does not change
  admission liveness policy or recover historical NodeRuns with no Attempt.

- **Cancelling admitted work under a legacy two-method `TaskAdmitter` no longer
  crashes, and no longer lies (#1338).** #1320 grew the protocol with
  `cancel_run`, and `TaskQueue.cancel` called it unconditionally, so a
  downstream adapter compiled against the earlier `admit`/`record_transition`
  shape raised `AttributeError` on the first cancelled task. The queue now
  probes the capability (`getattr`) — the Protocol is structural, so absence
  is invisible to `isinstance`. An adapter without `cancel_run` keeps its
  admitted work's receipt open and the refusal is logged as
  `task_cancel_unsupported_by_admitter`: physical cancellation is genuinely
  unavailable, and terminalizing the receipt CANCELLED over a Run nothing
  signalled would make "stopped" mean "locally forgotten" (#1242). Work with
  no canonical identity behind it (no admitter wired, no `run_id`) keeps its
  documented receipt-only cancellation, visibly distinct from stopped physical
  execution. Capable adapters still route cancellation through the canonical
  Run/Attempt service unchanged.

- **Governed harness waits can re-enter on the existing recovery timer (#1192).**
  New `agent.spawn_harness` waits persist the original dispatch receipt,
  fixed deadline and canonical poll observation identity before their first
  read. Recovery can consume a completion without redispatching, and local
  expiry preserves uncertain remote outcomes. Registered-DAG recovery receives
  the Container's configured harness adapters. Approval answers cannot become
  fabricated harness completions, and compatibility terminal answers no longer
  authorize ungoverned provider polling. Historical waits without a resume
  instant, the production approval/expiry bridge, and adapter-specific restart
  readiness remain separately gated; this does not close #1192.

- **The installer now honors `docker-compose.override.yml` (#405).** `install.sh`
  always invokes Compose with explicit `-f` files, which disables Compose's own
  automatic override loading, so an override copied into the checkout was
  silently ignored on installer runs while the docs claimed it was picked up.
  A repo-root `docker-compose.override.yml` is now included explicitly — last,
  so operator intent outranks the base file and the wizard's plan override —
  in both delivery modes, and only when the invoking user owns it and it is
  not group/world-writable (an override can remap ports, disable sandbox
  flags, or mount the host Docker socket; anything else aborts the install
  with remediation). The installer prints the effective Compose files and
  validates the merged render before startup (`MAISTRO_PRINT_COMPOSE_CONFIG=1`
  additionally prints the rendered config, credentials included), and
  `MAISTRO_COMPOSE_PROFILES` activates profiles an override assigns.

### Security

- **Protected-branch secret scans recognize two historical soak false positives (#860).**
  Preserve full-history scanning and the default rules while carrying over the
  exact commit/path/rule/line fingerprints for a synthetic local-stack fixture
  and a recorded task-deduplication ID already documented on the soak lane.

- **Boot Agent model tools retain governed admission and logical identity** (#1954 follow-up; [review finding](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1954#discussion_r4189499393)).
  Clarification and model-fallback search use the persisted Run actor/scope and
  configured model Binding through the existing Provider/Invocation boundary.
  Agent, delegation, response-round and ToolCall identity distinguish intentional
  calls while preserving replay. Ambiguous outcomes stop the strategy. The tool
  deadline also bounds third-party adapters, without replacing their catalog or
  retry authority. Hive's configured API prefix and omitted sampling are retained.

- **Hive DAG model-backed tools use governed model egress (#1085, #1370).**
  `clarify` and the model fallback of `web_search` require a configured
  `model.chat` Binding referenced by the DAG node's `model_binding_id`
  (top-level or under `config`). Provider selection, scoped credentials,
  actor/execution correlation, quota and usage use the existing canonical
  effect authority. Missing authority and malformed model answers fail the
  node instead of dispatching with ambient credentials or inventing answers.
  The generic tool Invocation remains in place. Ordinary legacy model and
  sandbox callers and Agent tool composition remain separate convergence work.

- **Unknown model Binding pins refuse before gateway setup or dispatch (#56).**
  Pinned models must have metadata in the configured ProviderRegistry before
  use; registered-but-unavailable pins continue to refuse without fallback.
  Unregistered request aliases retain gateway passthrough with absent cost
  metadata. Hive activation now reports the registration prerequisite clearly:
  supply trusted model metadata through `provider_config_path` before activating
  a pinned health model; LiteLLM `/model/new` registration alone is insufficient.
  Unavailable request-alias diagnostics no longer describe aliases as pins.


- **PostgreSQL quota JSON writes are independent of asyncpg JSON codecs
  (#1362).** Serialized budget definitions, reservation identities, and usage
  evidence are bound as text before PostgreSQL parses JSONB, preventing a
  configured JSON encoder from double-encoding them. Immutable budget checks
  and idempotent evidence comparisons retain their existing semantics. This
  repairs new writes only: existing double-encoded JSONB evidence is not
  migrated and its replay limitation remains. This does not supply missing
  provider-enforced numeric usage bounds (#1196).

- **Default Invocation quota wiring refuses unknown token and monetary bounds
  before provider dispatch (#1362).** Character-count guesses omit byte-level
  tokenization, full message fields, tool and response schemas, and multimodal
  billing; absent output limits cannot be priced as zero. The gateway currently
  has no proven complete-request bound, so default token/micro-USD budgets now
  fail closed even for priced models with `max_tokens`. Request-count policies,
  unconfigured quota admission, and explicitly injected adapter-backed quota
  contexts are unchanged. Numeric-budget usability remains incomplete until an
  adapter enforces a full physical-request bound (#1196).

- **Project wisdom respects GLOBAL organization boundaries (#1247).**
  Project-only `list_by_scope` refuses organization-bound GLOBAL rows without
  caller organization context. Layer 3
  keeps existing project-only AGENT/USER/TEAM changelog rows while including
  only public or same-organization GLOBAL memories. Missing organization context
  cannot expose organization-bound wisdom; authorized same-organization recall
  remains available across the in-memory, SQLite and PostgreSQL store paths.

- **Every base/tool image in every Dockerfile is pinned by immutable digest
  (#349).** Build stages no longer float on mutable tags and the uv installer
  is no longer copied from a `:latest` image, so a registry tag move cannot
  change the code that installs every dependency without a repository diff.
  Each reference is pinned `name:tag@sha256:<digest>` — the digest is the
  resolution authority (a manifest-list index digest, so a fixed target
  platform always resolves the same per-arch artifact), the tag the
  human-readable version annotation. All nine pins are registered in
  `quality/image-pins.json`; the new `check-image-pins` gate (quality.yml)
  rejects `:latest` anywhere and fails any unregistered digest or unpinned
  base without an owned, issue-numbered exemption, so base updates land only
  as reviewable registry-plus-Dockerfile changes — refreshed automatically by
  Dependabot's docker ecosystem, whose PRs carry the changelog, scan, rebuild
  and smoke evidence of the ordinary PR gates. Release images publish with
  SLSA provenance in mode=max and release.yml refuses a release whose
  provenance attestation does not name every pinned base digest.

- **Memory write authority (ADR-057) is enforced at every memory store
  boundary (#390, partial).** Every production memory store — learnings
  (in-memory, SQLite, PostgreSQL and the hybrid-search wrapper's inner store),
  episodic, outcomes and skill mutations — now calls the exposure-mode gate as
  the first statement of each mutating method. A store constructed without a
  declared `MemoryExposureMode` refuses to mutate at all
  (`MemoryUndeclaredModeError`, fail-closed; SPEC-062126-6a31's no-implicit-
  default rule), an agent-actor write or promotion under `system_managed`
  raises `MemoryWriteDenied` before any state changes (denied writes leave no
  partial durable state), and a system actor writes under every mode. The
  decision reads only the declared mode, the actor and the per-block tag —
  never model or persona content. The container declares the deployment's
  posture from the new `AgentConfig.memory.exposure_mode` setting
  (`agent_managed` default — the engine's existing behavior, now explicit;
  set `system_managed` for curated-context deployments). The M4-B lifecycle
  mutations added by the develop sync — `supersede`, `consolidate` and the
  store-level `advance_stage` on all three learning-store backends — are
  gated by the same decision as first statements, behind an explicit ADR-057
  principal kept distinct from the ADR-103 attribution string, so a denied
  supersede retires nothing and stores nothing. Not yet wired, and
  disclosed in KNOWN-GAPS until then: per-call read gating, `hybrid` per-block
  tags (agent writes fail closed under `hybrid`), `memory.write.denied` event
  emission, and a product-reachable E2E proving a denied write.
- **Active root Runs are capped per principal and per Workspace (#1182,
  partial).** Every `RunStore.create_run` (in-memory, SQLite, PostgreSQL) now
  refuses a new root Run with `RunConcurrencyExceeded` once 8 are active for
  its actor principal (across Workspaces) or 32 for its Workspace. "Active"
  means CREATED, QUEUED or RUNNING. Child Runs, parked WAITING/PAUSED Runs and
  terminal Runs hold no slot, and a parked Run resuming is not a new admission.
  A duplicate schedule occurrence is still refused as a duplicate. PostgreSQL
  serializes the insert and the count with transaction-scoped advisory locks,
  so the ceiling holds across replicas. SQLite relies on the store's write
  lock, since that tier is a single process. A SQLite refusal rolls back to a
  savepoint, so a sibling store's open transaction on the shared connection
  is neither committed nor ended. Partial indexes serve both SQLite counts.
  - A chat turn that meets a full ceiling first reclaims slots held by dead
    turns, then asks once more. `recover_stranded_chat_admissions` now also
    cancels chat Runs stranded in CREATED or QUEUED.
  - The ceilings are governed floors in `quality/security-resource-floors.json`
    (`MAX_ACTIVE_ROOT_RUNS_PER_PRINCIPAL`, `MAX_ACTIVE_ROOT_RUNS_PER_WORKSPACE`).
    Operators may lower them, but raising either requires
    `ALLOW_UNSAFE_RESOURCE_OVERRIDES`.
  - Both values appear in maistro-server's `/health` `effective_resource_policy`.
  - maistro-server `/v1/chat/completions` answers a refused turn with 429 and
    `Retry-After`. `Container` chat admission re-raises the refusal instead of
    answering unrecorded.
  - The server's `HTTPException` handler now keeps the raiser's headers.
  - The scheduler already keeps a refused occurrence owed and retries it on a
    later tick.
  - Not yet done: the other HTTP/WebSocket submit surfaces still need to map
    the refusal to 429.

- **Canonical Run reads have a Workspace-membership-scoped seam (#1152,
  partial).** `maistro.runs.scoped_reads.ScopedRunReader`, wired as
  `Container.run_reader` over the Container's own Run, Workspace and Project
  scope stores, reads a Run, its NodeRuns and its Attempts only for a member
  of the Run's Workspace whose Project belongs to it. The initiating
  principal is provenance, not a gate. Missing and foreign ids, a blank
  principal, and a NodeRun or Attempt id from another Run all raise the same
  `RunNotVisible`, and membership is resolved before the Run lookup. Hive's
  DAG-run inspection now reads its canonical lifecycle overlay through this
  reader, so a projection row naming another Workspace's Run no longer
  borrows that Run's status, result or error; the list path batches those
  reads through `ScopedRunReader.get_runs`. maistro-server `/v1/runs`, Hive
  Canvas eval, Hive DAG-run cancel (which still acts on the unscoped
  `run_store`), `actor_principal_id` validation, accounting identity and
  delegation identity are still open.

- **Tool calls fail closed when Sentinel or caller auth is missing (#1165).**
  An `Agent` built without a Sentinel, or handed a turn with no `auth`, used
  to execute tool calls unauthorized; it now returns `Error: Permission denied
  for tool …` and logs why. The standalone ReAct and Artificer strategy paths
  apply the same rule. Callers that construct Agents directly must wire a
  Sentinel whose permission table grants the tools they need.
- **Layer-1 episodic recall is scoped to the current Project (#1047,
  partial).** `DefaultContextAssemblyPolicy.layer1` filtered by `agent_id`
  only, so an agent id used in two Projects/Workspaces recalled Project A's
  AGENT-scope memories inside Project B. `layer1` (and the
  `ContextAssemblyPolicy` protocol) now take a keyword-only `project_id`,
  which `assemble` passes through to the working-memory hot projection and
  both ranked and unranked durable fallback reads; a memory with no project
  is not guessed into one. An empty `project_id` keeps the agent-wide recall;
  nonempty values, including whitespace, remain exact filters.

- **Retired the process-local Home Assistant confirmation store and
  `/v1/confirms` (#48, partial).** `GET /v1/confirms`, `GET
  /v1/confirms/pending` and `POST /v1/confirms/{id}/respond` are no longer
  mounted: the GETs answer 404, and the POST answers 405 wherever the SPA is
  served (its GET-only catch-all owns every path), 404 otherwise. The respond
  route needed only authentication and wrote Home Assistant state; its
  in-memory store (`_PENDING_CONFIRMS`) had no production producer, so it
  could never hold a real confirmation. Nothing in production imported
  `services/ha_tools.py` either (its `ha_confirm`/`ha_control` tool
  definitions were never offered to a model), so the module is deleted with
  `send_confirm` and the store. Human approval has one model: a waiting human
  NodeRun answered through `/v1/hitl`; any future HA push confirmation must be
  a notification transport for that NodeRun.
- **Tool-result governance is pinned across real Agent strategies (#1202,
  partial).** A regression suite drives the shipped ReAct, Artificer and
  BuildersLearning strategies through `Agent.handle` with a real Warden and
  Sentinel (BuildersLearning delegates to ReAct on that path). It checks that
  a PII-bearing or prompt-injection tool result reaches the model as the same
  redacted text or Sentinel refusal, and never raw, for each of them.
  Direct and PlanExecute are not covered yet. Test-only; no runtime behavior
  changes.

- **Hive schedules are bound to their owner's Workspace (#1201, partial).**
  `POST /v1/schedules` now requires a `workspace_id` selection (optional
  `project_id`), admits it through the same canonical Workspace/Project
  authorization as `POST /v1/dags/{id}/run` (403 when absent or not a
  membership), and stamps `user_id`, `workspace_id` and `project_id` from the
  authenticated session; a client-sent `user_id` is ignored and `PUT` cannot
  change owner or scope. List returns only schedules in the caller's
  Workspaces, and get/update/delete/manual run answer the same 404 for a
  missing, foreign, or ownerless (pre-existing) schedule. Only a Workspace
  owner or editor may create, change, delete or manually run a schedule
  (viewers read); an archived Workspace refuses edits and manual runs.
  Removing a member removes their API access; it does not yet stop automatic
  fires of schedules that member owns (tracked in #1201).
  With a configured Container, fires of a bound schedule create their Run in
  the bound Workspace/Project instead of the configured default. Operators:
  schedules created before this change (including the seeded `sch-1`) have no
  Workspace, are no longer visible over the API, and still fire automatically
  in the default Workspace until the automatic-fire half of #1201 lands;
  remove them from the schedule store directly before recreating them from a
  Workspace, or both copies will fire.

- **Canvas visual evaluation no longer reveals whether a Run id exists (#1152,
  partial).** `POST /v1/canvas/eval` now authorizes the selected canonical Run
  against the caller's canonical Workspace universe, the same one DAG-run
  inspection uses, resolved before the Run lookup so a missing and a foreign
  id do the same work. Any member of the Run's Workspace may evaluate it, including a Run another
  member started. A Run in a Workspace the caller does not belong to, a Run with
  no execution principal and a missing Run all get the same 503
  `visual quality evaluation is unavailable`. Previously a foreign Run returned
  403 `Canvas Run is not owned by this principal`. The admin bypass is removed:
  an admin who is not a member of the Run's Workspace is refused like anyone
  else. Hive still has no Project-level check on this route.

- **Workspace access decisions now live in one core seam (#1150, partial).**
  `maistro.workspaces.WorkspaceAuthorizer` answers "may this principal VIEW or
  ADMINISTER this Workspace?" from the Workspace store, with one
  `WorkspaceAuthorizationDenied` for a missing Workspace, a foreign Workspace
  and a blank principal. maistro-server's `require_workspace_membership` and
  `require_workspace_owner` now delegate to it. Unknown actions and non-string
  principals are denied. Responses are unchanged: a denial is 404
  `Workspace not found`, and a member who is not an owner still gets 403.
  Project-level actions and the hive-conductor membership checks do not use
  the seam yet.

- **Design trust review records no longer recommend upgrading content the engine
  blocks (#817, partial).** `scan_and_record` now runs the shared Design
  `scan_blocking_patterns` over the content it records, instead of assigning
  empty flags. Script/iframe/`javascript:` markup, prompt-injection phrasing,
  base64 blobs and hidden Unicode are now recorded as SKULL with explicit flags
  and a `banish` recommendation. `upgrade` is recommended only when the scanner
  the output scan uses finds nothing. The engine's accept/reject outcome is
  unchanged, because the output scan already rejected this content.

- **Concurrent registrations can no longer publish two identities under the
  same username (#1248).** The register route's availability check and the
  UUID-keyed write were separate steps, so the store's key (a fresh UUID, not
  the username) never enforced uniqueness — two requests racing the same
  username could both pass the check and both write, leaving two identities
  answering to one username. The check, invitation spend, and write are now
  one critical section (an in-process lock) backed by a durable claim:
  `ModelStore.put_if_unique` and `PersistedStore.put_model_if_unique` make the
  username claim and the row's insert one SQLite transaction, so the
  uniqueness boundary survives across independent application processes, not
  just within one. `test_concurrent_open_registration_claims_username_once`
  drives eight threads at the same username through the real route (one 200,
  seven 409, one stored identity); `test_independent_process_writers_publish_one_username`
  proves the same claim holds across two separate `multiprocessing` writers
  sharing one SQLite file.

- **pydantic-ai-slim removed from the API and research images, clearing
  CVE-2026-25580 (HIGH) (#1515).** ADR-094 already cut pydantic-ai from the codebase
  (zero `pydantic_ai` imports remain), but both Dockerfiles still installed
  `"pydantic-ai-slim[openai]>=0.1"`, whose unbounded floor resolved to the
  CVE'd 1.30.1 (dragging anyio 4.13.0 into the image with it). The fix line
  (`>=1.56.0`) requires `openai>=2` and cannot co-install with the images'
  `openai<2` pin, so the vestigial install lines are removed outright rather
  than bumped; anyio then resolves to 4.15.1 via starlette/httpx (caught by the
  required Supply chain (pip-audit) check; same reactive class as the anyio
  entry below).

- **anyio bumped 4.13.0 → 4.14.2 (and the 4.15.1 leg some members resolve
  separately), clearing CVE-2026-63374 and CVE-2026-64847 that fail every
  fresh `pip-audit` run (no linked issue: caught by the required Supply
  chain (pip-audit) check on #1502, the same class of reactive advisory fix
  as the gitpython bump above).** Lockfile-only change; no API or behavior
  delta.
- **Due-recovery failures never persist or log credential text (#1143).** A
  node-resolver factory that fails while a due Run is being resumed now
  terminalizes the Run with a stable `NodeResolverUnavailable` message (Run id
  and exception type only) instead of the factory's raw error, and the
  recovery log sanitizer also redacts quoted keys (`{'api_key': ...}`),
  `Authorization`/`Bearer` headers, and provider-style key literals
  (`sk-…`, `ghp_…`, `xox…`, `AKIA…`).
- **gitpython bumped 3.1.59 → 3.1.62, clearing five untriaged advisories that
  fail every fresh `pip-audit` run (#1493).** The lockfile carried
  `gitpython 3.1.59` (transitive via `cosmic-ray`), which `pip-audit --strict`
  now flags with PYSEC-2026-3982/-3983/-3984 and two companions, fix 3.1.60.
  `Supply chain (pip-audit)` is a required check on every PR, so every
  candidate entering the merge queue failed group validation within ~90
  seconds of enqueueing. Lockfile-only change; no API or behavior delta.
- **Canonical Event payloads are scrubbed of credential material before any
  backend can persist them (#1164).** `EventEnvelope` now redacts `payload`
  and `provenance` in its constructor — the one seam the memory, SQLite,
  PostgreSQL and outbox paths all already go through for their size bound — so
  a token pasted into an event can no longer reach durable storage, a replay,
  or an operator's inspection of the event log. Both halves of #1159's policy
  apply: a field whose *name* classifies as credential material
  (`api_key`, `private_key`, `ssh_key`, a bare `key`, …) loses its value, and
  every surviving string is scanned for secret *shapes* (Slack and AWS
  credentials, bearer assignments, PEM blocks, high-entropy runs). Identifiers
  are preserved — `key_arn`, `token_id`, digests, uuid4 ids and ordinary prose
  survive untouched — and the scrub is idempotent, so re-validating a staged
  envelope does not rewrite already-recorded evidence. Rows written before this
  change are read back exactly as they were recorded rather than re-scrubbed on
  read. Mapping *keys* are scanned too, so a token-indexed object cannot carry
  the credential past the scrub in its key, with two keys that redact to the
  same label kept distinct rather than collapsed. A `key` that names what it
  identifies (`effect_key`, `idempotency_key`, `partition_key`, `parent_key`,
  …) now classifies as an identifier in `maistro.security.secret_policy`, so
  the canonical capability events keep the `effect_key` that audit and replay
  consumers join on. The byte ceiling is re-checked after the scrub, because
  redaction can grow a field that passed the ceiling as submitted.
- **An identity-free chat turn is routed as the anonymous principal again
  (#1165 regression, introduced by #1288).** `Container.route_request` had
  stopped substituting `ANONYMOUS_AUTH` for `auth=None`, so a turn that
  carried no identity reached the strategies with `auth=None` — and they
  consult Sentinel only when `auth is not None`, which let an unauthenticated
  turn walk past the fail-closed permission table. The armed-controls refusal
  survived; only the substitution was lost. Both halves are restored through
  one `_resolve_chat_auth`, and the existing regression test for #1165 passes
  again.
- **DevSkim scans the shipped surface instead of everything (no linked issue:
  scanner configuration).** The action ran unconfigured, so the test and
  vendored trees were scanned alongside the shipped ones and supplied 619 of
  its 912 `http://`/`localhost` findings — fixtures that assert an insecure
  URL is refused, loopback addresses in test servers, vendored benchmark
  corpora. A scanner two-thirds noise is one nobody reads. `ignore-globs` now
  names those trees, and only trees: every entry ends in a directory segment,
  because a filename shape reaches across the repository and silently drops
  shipped code (`**/test_*.py` did exactly that in the CodeQL config, where it
  also matched `maistro_rsi/test_inventory.py`). `docs/**` is deliberately not
  excluded, and no rule is suppressed repo-wide. What DevSkim reports about
  shipped code is unchanged; only the noise around it is gone.

- **CodeQL code-scanning alerts cleared across the runtime, gate scripts, and
  frontends (no linked issue: CodeQL code-scanning alerts).** Hive-conductor
  no longer echoes raw exception text to clients from the run-DAG, widget, and
  RSI-run paths (the exception class plus a fixed message is returned; detail
  stays in server logs), the missing-secret log line no longer names the
  secret, and the credential-store warning no longer prints the vault path.
  Path-taking surfaces (demo dashboard ids, SPA fallback, RSI execution
  policy, sandbox workspace, Lulu preflight uploads) now resolve symlinks
  first and decide containment on the resolved path, so a link planted inside
  an allowed directory cannot point out of it, and a configured root that is
  itself a symlink still accepts its own contents rather than refusing every
  legitimate request. Rovo MCP detection matches the URL hostname rather than
  a substring, and Airtable cache fingerprints use a salted PBKDF2 digest. The
  canvas book-maker Express server rate-limits `/api`
  (`API_RATE_LIMIT_PER_MINUTE`, default 600; a non-numeric, zero, or negative
  value is refused with a warning and the default used, rather than becoming
  the NaN limit that removes the cap) and validates print-order ids; the
  bundled hive page keeps its API key in memory instead of `sessionStorage`;
  chat/deck ids come from `crypto.randomUUID()`; export format and quality are
  allowlisted; and book-plan patches refuse prototype keys. Gate scripts
  rename identifiers CodeQL's secret heuristic flagged.
  `.github/codeql/codeql-config.yml` excludes the test and vendored trees from
  scanning; every entry names a location rather than a filename shape, so an
  exclusion cannot reach into `packages/` and quietly drop a shipped module
  from the analysis.

- **Sentinel's permission table is fail-closed, and the production paths can
  both feel it and configure it (#1165).** An empty or omitted deployment
  table now denies every tool instead of authorizing all of them. A chat turn
  that carries no identity is evaluated as the role-less anonymous principal
  rather than walking past the table (the strategies only consult Sentinel
  when an identity is present), so an auth-less request can no longer execute
  tools the table denies; a configured table or strike tracking still refuses
  to run without a real identity. Operators state grants in `maistro.yaml`
  (`security.permission_preset`, `security.permissions`, unknown presets
  refused at load) and Hive reads `MAISTRO_PERMISSION_PRESET` /
  `MAISTRO_PERMISSIONS`; both reach the config the Container is built from.
  Hive's bridge and engine accept the caller's principal on `route`.
- **Frontend transitive advisories closed (no linked issue: Dependabot
  security alerts, no tracked issue).** `packages/hive-conductor/frontend`
  regenerates its lockfile so the transitive `brace-expansion`
  (GHSA-rgw5-rvv9-x895, unbounded intermediate arrays) and `nanoid`
  (GHSA-2v37-7h3g-55p8, zero-size custom generator loop) resolve to patched
  releases; no direct dependency changes. `npm audit` reports zero findings.
  The canvas frontend's own `@vitest/mocker` advisory (GHSA-82fw-gwwq-j7x9,
  path traversal via the redirect mock) is closed on `develop` by #1212's
  move to `vitest` 5, which this branch now takes rather than the 4.x pin it
  originally carried.
- **Python dependency floors raised past their advisories (no linked issue:
  Dependabot security alerts, no tracked issue).** Every `pyproject.toml` in
  the workspace and both backend `requirements.txt` files declared version
  ranges whose lower bound was a release with open advisories, which is what
  Dependabot alerts on for a range: `pydantic` (>=2.4.0, GHSA-mr82-8j83-vxmv),
  `python-multipart` (>=0.0.31, eight advisories through GHSA-v9pg-7xvm-68hf),
  `pyjwt` (>=2.13.0, seven through GHSA-xgmm-8j9v-c9wx), `pytest` (>=9.0.3,
  GHSA-6w46-j5rx-g56g), `pillow` (>=12.3.0, seventeen through
  GHSA-xj96-63gp-2gmr), `fastmcp` (>=3.2.0, eight through
  GHSA-vv7q-7jx5-f767), `pynacl` (>=1.6.2, GHSA-mrfv-m5wm-5w6w), `starlette`
  (>=1.3.1, seven through GHSA-82w8-qh3p-5jfq), `nltk` (>=3.10.3; three
  advisories have no fixed release and remain), and the dev-tools-only
  `guarddog` (>=2.7.1; two have no fixed release and remain). `uv.lock`
  already resolved every one of these at or above the new floor, so no
  installed version changes; the lock's recorded specifiers are refreshed.
- **Bootstrap credential staging is now private, atomic, and never follows a
  link (#809).** `write_bootstrap_credentials` writes secrets to a fresh 0600
  temp file in the same directory and promotes it with `os.replace`, so secret
  bytes never land in a pre-existing permissive inode, a planted symlink at
  the final path is refused rather than followed, and an interruption can no
  longer leave truncated JSON at the staged path. A pre-existing file is
  reused only after parse-validation — existence alone is no longer treated
  as staged input by the CLI's "already staged" skip either.

- **Canonical `EventEnvelope` payloads are now structurally bounded (#1164).**
  `payload`/`provenance` are checked for serialized byte size (256 KiB) and
  container nesting depth (32 levels) in the envelope's own constructor, so
  every backend (in-memory, SQLite, PostgreSQL, outbox) rejects an oversize or
  pathologically nested event before it is ever materialized in persistence,
  rather than each needing its own copy of the check. A non-JSON-encodable
  field is rejected the same way. Violations raise the new, typed
  `EventPayloadTooLarge` rather than failing later inside a store's own
  serialization call. Current emitters are all well under the ceiling, so this
  changes no observed behavior today; it bounds a future caller that isn't
  written yet. A row persisted before this ceiling existed stays readable —
  `SqliteEventStore`/`PgEventStore` reconstruct stored rows without
  re-imposing the new size/depth bound, so upgrading does not turn a
  previously valid event into a read-time crash. Routing an oversize artifact
  through the canonical object store by reference, and scrubbing secrets from
  payloads before persistence (#1159), remain open follow-up work this issue
  explicitly does not claim.

### Added

- **Workspace BacklogItem history service (#101).**
  `maistro.workspaces.backlog_history` records each BacklogItem's life as an
  append-only journal: field and priority edits as before/after pairs, BACKLOG.md
  status moves, claims (#100's reserved fields), blockers and their clearing,
  partial progress that implies no status, decomposition receipts that snapshot
  the parent's acceptance criteria, discovered prerequisites/defects pinned to
  a PROPOSED initial status, exact Goal identity/revision links (#458),
  reconciliation decision references, and Run/evaluation evidence. Closure is
  refused without evidence refs — a completed Run alone is never closure — and
  reopening requires a reason. An in-memory reference store and a SQLite store
  (writing inside the paired Project store's transaction, assigning a
  per-item sequence) share one store contract; the Container wires it on the
  Project store's backend and maistro-server serves member-only reads at
  `GET /v1/workspaces/{workspace_id}/backlog/{item_id}/history`.
- **Governed `image.generate` Capability for Canvas/Design Studio generation
  (#286, partial).** `maistro.capabilities.ImageGenerationEgress.generate`
  runs one image generation through the canonical Binding → policy →
  Binding-scoped credential → Invocation path, via the approved
  `LlmGatewayImageProvider` (`POST {gateway}/v1/images/generations`,
  `response_format=b64_json`, same LiteLLM gateway and credential pool as
  `model.chat`). The Invocation carries Run/NodeRun/Attempt correlation and
  returns decoded image bytes, with usage recorded in `images`; a replayed
  effect key returns the recorded result without a second call. The Binding
  must match its registered record, so a caller-built or altered Binding is
  refused before any HTTP. A gateway error, an empty `data[]`, or a payload
  that is not base64 PNG/JPEG/GIF/WebP is a `FAILED` Invocation plus
  `ImageGenerationError`, never an empty success, and a later Attempt may
  retry it. Generated bytes never enter the Invocation row: the egress writes
  each image to an `ImageBlobStore` port and records only a reference, its
  SHA-256 and its size, because `capability_invocations` has no deletion path
  (`quality/durable-table-retention.json`) and a result carrying the images
  would grow the database, its WAL and every backup by megabytes per call.
  Replay reads the bytes back by reference and checks them against the
  recorded digest; a blob the store no longer holds, or bytes that no longer
  match, raise `ImageBlobUnavailable` rather than regenerating under a
  `COMPLETED` effect key. A store that cannot keep an image raises
  `ImageStorageError` (an `EffectNotApplied`), so the Invocation terminalizes
  `FAILED` and may be retried. `InMemoryImageBlobStore` is the content-addressed
  reference implementation; the durable home, `canvas_blobs`, belongs to
  maistro-canvas, which depends on core, so the store is a port rather than a
  table here. Nothing ships a caller yet: the hive `ImageGenClient` adapter and
  the book-maker POC convergence (#52) will be its consumers.

- **Proposed spec for Workspace work campaigns (#103, partial).**
  SPEC-092626-1831 (Proposed), with its boundary decision ADR-092626-c1e7
  (Proposed), records the campaign contract before any code: a
  campaign is operator policy that narrows eligible BacklogItems and linked
  Goals, with four autonomy modes, durable pin-next/pause/exclude/human-only
  controls, human priority kept separate from the system selection score, and
  audit keyed to actor and policy version. It grants no permissions and owns no
  Goals. The priority combination rule and default mode stay open questions.
  Documentation only: no store, route or runtime behaviour changes yet.

- **The Canvas store's tables are in the root alembic chain (#286, partial).**
  Migration 044 creates `canvases`, `layers`, `generation_jobs` (with the
  SPEC-203 lease columns and the partial pending-claim index),
  `composite_records` and `canvas_blobs`, which `PgCanvasStore` reads and
  writes but no migration here ever created. It adopts rather than assumes an
  empty database: `CREATE TABLE IF NOT EXISTS` plus `ADD COLUMN IF NOT EXISTS`
  for every column, so a deployment whose tables were created outside the
  repository gains any missing columns and keeps its rows. On tables 044
  creates, the `(canvas_id, z_index)` uniqueness is deferred to commit, so
  layer reorder and removal no longer collide on intermediate states; an
  adopted table keeps its own constraints and foreign keys as they were. The five tables move
  from `created_outside_this_repo` into the durable-table retention inventory.
  Operators: `alembic upgrade head` now touches these tables, and `downgrade`
  past 044 drops them, including rows an adopted table held before.

- **Durable user model: `UserModelFact` and self-consented promotion
  (#1047, partial).** New `maistro.memory.user_model` package: a frozen,
  revisioned `UserModelFact` owned by the canonical user id (evidence refs,
  confidence, `active`/`under_review`/`superseded`/`tombstoned` state,
  validity window, sensitivity, reusable flag, correction provenance, persona
  hints), a `UserModelStore` protocol, and an in-memory store.
  `promote_evidence` is the only write path from episodic memory: it
  promotes only the acting user's own memory (cross-user still needs SPEC-242
  consent), audits every attempt, refuses to recreate a tombstoned lineage or
  revive a corrected statement, and puts contradicted facts under review with
  a new revision instead of overwriting them. `correct_fact` and
  `forget_fact` are the owner's explicit revise/delete paths. The decision
  is recorded in ADR-092526-4391 (Proposed). Durable SQLite/PostgreSQL
  stores, the migration, and recall follow in later PRs.

- **`GET /health/ready` reports the serving container's cgroup ceilings
  (#75, partial).** A new `container_limits` field reads cgroup v2
  `memory.max`, `pids.max` and `cpu.max` at the hierarchy root, which under
  a private cgroup namespace is the container's own cgroup. It reports
  `memory_max_bytes`, `pids_max` and `cpu_max_cores`. Each value is a
  number, `"unbounded"` when no limit is set at that level (an enclosing
  cgroup may still impose one), or `"unknown"` when nothing readable is
  there: cgroup v1, a host-root view, or unparseable content. Because the
  `/health` prefix is public and rate-limit exempt, the field is `null`
  unless the caller presents an admin bearer token (or API auth is
  disabled). It never changes readiness status. Compose profiles still
  declare no ceilings (#862).

- **Proposed ADR for the durable cross-Workspace user model (#1047, partial).**
  ADR-092526-4391 (Proposed) records the owner's decisions on #1047. The user model is a
  separate `UserModelFact` record that does not decay. It has revision lineage,
  sensitivity and shareability, a validity window, and tombstones that block
  re-promotion. Promoting a Workspace-, Project- or Agent-scoped fact into the
  same user's model is automatic self-consent with an audit entry, and the ADR
  proposes that amendment to SPEC-242; cross-user and team/org/global widening still need a `ConsentTask`.
  Decision only: no store, migration or runtime behaviour changes yet.

- **Workspace Attention read: `GET /v1/workspaces/{workspace_id}/attention`
  (#1049, partial).** Computes the Workspace's Attention items on every read
  from canonical sources — human-paused NodeRuns in the durable run store and
  failed Runs behind the scoped Run-inspection door — and persists nothing.
  Each item carries its source id, class, rank, a human-readable reason, the
  evidence behind it, and the existing HITL answer route. A persisted HITL
  deadline within 24 hours makes an item `time_sensitive`; every other human
  pause and failed Run is `queued`, and age alone never raises a class. A
  pause whose deadline has already passed stays `queued` without an answer
  link, since the store refuses late answers. A summary (`counts_by_class`,
  `highest_class`, `rising`, `truncated`) lets a UI show what is waiting
  without inventing importance. Items are capped at 200 after ordering. Failed
  Runs come from the bounded Recent Runs projection window. Non-members get the same 404 a missing
  Workspace gets; reading requires `dags.write`, the scope `/v1/hitl/pending`
  takes, since items carry the paused node's question.

- **Every parked Graph pause reason must name a reachable production waker
  (#1192, partial).** A new architecture test maps each
  `PAUSE_RESUME_CONDITIONS` reason to its production waker or to a known-gap
  ledger. For each waker it checks that the entrypoint exists, has a non-test
  production caller (called or handed off by name, one hop), calls the
  canonical API it names, and that the API accepts the status the reason
  actually parks in. It also checks that whatever runs the Run again can
  select a Run holding the reason: a tick filtered to one admission source owns
  only the node kinds that source builds, and one of them must emit the reason.
  A reason parked beside a human pause parks PAUSED with it, so the pair must
  still be released. Every declared accepted status is pinned by equality
  against the shipped API. The human reasons are woken by the Hive HITL answer
  and cancel routes, and the two elapsed-timer reasons by #837's
  registered-DAG due tick. The legacy-DAG and Evolve ticks are shown not to
  qualify, because their Runs never pause. `awaiting_remote_delegation` and
  `awaiting_harness` park WAITING while the only answer path accepts PAUSED,
  so they are ledgered against #1192. HITL deadline expiry is not counted as
  a waker, because only a manual `POST /v1/hitl/expire` triggers it.

- **Every durable table declares its retention, and CI checks it against the
  schema (#325).** `quality/durable-table-retention.json` lists all 63 tables
  in the schema built by Alembic and `.sql` migrations (later drops applied),
  runtime `CREATE TABLE` or ORM `__tablename__`, with backend, owner, data
  class, retention and deletion path. Six tables
  whose DDL lives outside this repository are listed separately.
  `scripts/check-durable-table-inventory.py` fails CI when a table has no
  entry, an entry names a table nothing creates, a deletion path does not
  import, or `security_violations` or `usage_events` is dropped. A table with
  no production-driven purge is recorded as `undecided` against #325. This
  includes `security_violations`, `usage_events`, `task_idempotency` and
  `security_rate_limits`. Nothing is written down
  as retained forever unless someone decided it.

- **Stable Workspace Agent identity and per-user default Workspace
  ([#1037](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1037),
  ADR-092326-7ed7).** Hive's `services/workspace_agent.py`
  `resolve_workspace_agent()` returns a Workspace's single canonical Agent
  (`workspace-agent:{workspace_id}`). It is materialized once, insert-if-absent,
  through the one roster writer (#840), so concurrent first calls converge even
  across processes, and a Workspace deleted mid-materialization leaves no Agent. Its persona
  template (default `program_manager`) can be swapped without changing the id.
  `services/default_workspace.py` `resolve_default_workspace()` gives each
  caller one owned default Workspace. The default is chosen by a durable
  insert-once claim, so racing first requests yield one Workspace. A deleted,
  revoked or demoted default is replaced and never handed back.
  `POST /v1/workspaces/default` (gated by `workspaces.write`) returns the
  caller's default Workspace with its Workspace Agent id. Chat turns do not
  consume either resolver yet; that is the next #1037 slice.

- **Every maistro-core node kind is proven to get the Container's own
  authorities through `Container.node_resolver()` (#44, #1082).** A new sweep
  resolves each registered core kind that declares an authority through a real
  `create_container()` Container and asserts it receives the exact
  Container-owned harness adapters, usage log, A2A delegator, guest peers,
  canonical and graph Run stores, capability-effect context, provider
  registry, LLM router, and resolver, so the Container dropping one and
  letting `build_node_resolver`'s bare default stand in now fails CI. Test
  only; no wiring gap was found.
- **`GET /v1/runs/{run_id}/node-runs` now lists each NodeRun's Attempts,
  including the agent a chat turn dispatched to (#223).** Every NodeRun carries
  an additive `attempts` array of `attempt_id`, `ordinal`, `status`,
  `executor_id`, `created_at`, `started_at`, `finished_at` and `agent`
  (null where none was recorded, as for tasks). This is the public reader for
  ADR-082526-7f02's "the Attempt answers which agent ran". `Attempt.result`
  and `Attempt.error` are deliberately not exposed, since they can carry raw
  provider or exception text.

- **Governed model egress is wired into production Container composition
  (#1079).** `AgentConfig.model_bindings` declares authorized Workspace/Project
  `model.chat` Bindings; `create_container()` bootstraps them into the exact
  per-Container `CapabilityEffectContext` production effect nodes consume, and
  `execute_admitted_runs`, `resume_parked_runs`, and Hive's `dag_agents` all
  resolve `llm.summarize` through the same canonical Provider/Router
  authorities instead of each constructing its own fallback. The physical
  model call now authenticates from the Binding's own scoped credential
  (`CredentialRouting`, resolved from `AgentConfig.litellm_key` at bootstrap)
  rather than a flat environment-variable key, so a call with no authorized
  Binding, or a Binding whose credential isn't registered in its own
  Workspace/Project scope, refuses with `CredentialScopeError` before any
  request reaches the gateway. `test_model_egress_container_composition.py`
  proves production composition end-to-end (Bindings bootstrap through the
  Container, zero configured Bindings authorizes nothing, a Container-resolved
  `llm.summarize` reads real Provider metadata and executes through governed
  Invocation with Run/NodeRun/Attempt correlation, and incorrect Workspace
  scope is rejected before the physical transport is invoked).

- **Canvas generation jobs converge onto canonical Run/NodeRun/Attempt
  execution (#735).** `maistro_canvas`'s durable generation runner is wired to
  the canonical executor: `canvas/executor.py` and `canvas/store.py` carry
  generation-job progress through real `Run`/`NodeRun`/`Attempt` records
  instead of a Canvas-local job shape, and `protocols.py` gains the store
  surface the canonical path needs. `test_canonical_executor_integration.py`
  and `test_store_scope_conformance.py` cover the wiring; the maistro-core
  side lands alongside durable-runs executor and HITL-settlement hardening
  from the same convergence work (resume-lease and HITL-deadline handling,
  `human_approve_draft`/`human_delegate_to_role`/`human_review_and_edit`
  declaring their authorities, and an accepted-outcome-required check on
  parked Run resume).

- **Hive DAG execution (WebSocket run + optimizer) requires and carries a
  canonical Workspace/Project scope (#766).** `services/dag_execution_scope.py`
  resolves a client-selected `workspace_id` through the canonical
  `WorkspaceStore`/`ProjectScopeStore` — membership and active-presentation
  state, not just existence — and returns a `DagExecutionScope`
  (`workspace_id`, `project_id`, `user_id`) rather than a bare Workspace.
  `GET /v1/ws/dags/{dag_id}/run` now requires an explicit, authorized
  selection end-to-end (the prior transitional omitted-workspace path is
  gone) and passes the resolved scope into `execute_dag`/`execute_dag_streaming`
  so canonical execution carries real Workspace/Project identity instead of
  none. `test_dag_execution_scope.py` covers unknown, non-member, and
  archived-Workspace refusal (one shared close code, `1008`, so the boundary
  stays a non-oracle) and the accepting path reaching the normal
  DAG-not-found response.

- **The Workspace Agent interviews before it commits a Goal or CreativeBrief
  (#774, #804, #53; SPEC-091726-7c2a).** `maistro.agents.brief_interview` is a
  deterministic requirements conversation: one required question at a time in
  plain words, free-text answers matched to options or carried verbatim, answers
  the opening turn or the workspace record already holds never asked, "you
  decide" taking a marked default only where one is defensible, "change *field*"
  re-answering anything, and "never mind" dropping with nothing written.
  `commit_brief` is the gate: it returns the draft a Goal revision and a
  CreativeBrief version are written from, with the source of every field and
  the list of assumed ones, and refuses while any required field is missing.
  The first script is a video brief for creator workspaces. Hive hosts the
  interview beside the onboarding one, at `/v1/program/brief` (`start`,
  `answer`, `draft`, and delete), persisted per (user, workspace), and as
  ordinary chat turns: `POST /v1/chat/stream` and `/complete` take a
  `workspace_id`, and a turn there that asks for work is answered by the
  interview instead of the model, with a `brief` event the Chat page renders
  as the "brief so far" panel. The Warden input boundary still runs first.
- **The Workspace has a first-party design system (#1046, #1048, #65;
  ADR-091626-ba4f).** `maistro-design` now bundles `workspace` as a seventh Tier-1 system —
  the first authored in this repo rather than vendored from open-design. It
  shares the Open Design token schema and adds the Workspace grammar as tokens:
  frosted glass over a persona bloom, a fixed four-colour actor quartet (you /
  agent / gate / system), four honest state faces, three undo outcomes and a
  12px type floor. Three persona templates ship (greenhouse — the default —
  slate, studio) in light and dark; a user-authored theme supplies four values
  and is contrast-gated. `components.html` and `preview/home.html` render the
  kit and Workspace Home without scripts. The as-is Conductor stylesheet is
  measured in `docs/product/CONDUCTOR-DESIGN-SYSTEM-AUDIT.md` (8px labels, four
  accents, 56 `!important`, three hand-maintained theme files) as the baseline
  this replaces. Binding the Conductor's `data-theme` to these tokens is a
  separate Workspace-cutover change.

- **Browser sessions are governed at the Playwright boundary (#855).** Every
  network request a `BrowserClient` browser makes — main-frame navigations,
  redirect hops, subresources, and the destinations the browser-use agent
  invents mid-run — now passes a route handler that applies the same canonical
  outbound destination policy used by ordinary HTTP effects
  (ADR-082326-5386), *before* the network stack connects. WebSockets are denied
  outright (Playwright's route layer cannot govern them), service workers are
  blocked at context creation, and every decision is audited as an origin-only
  `BrowserNetEvent`. Operators can layer browser-specific origins via
  `BROWSER_USE_ALLOWED_ORIGINS`; a browser-use build that cannot be handed a
  guarded context is refused rather than run unguarded.

- **Hive Conductor now propagates one request correlation identity into
  maistro-server task admission (#1063).** Hive Conductor registers
  maistro-core's `RequestIDMiddleware` in its own stack (reused, not
  reimplemented), and `MaistroServerTaskBackend` forwards the bound id as an
  outbound `X-Request-ID` header so maistro-server's own `RequestIDMiddleware`
  adopts the same id instead of allocating an unrelated one for the
  service-to-service hop. `TaskRunAdmitter.admit()` records that id on the
  admitted Run's provenance alongside the existing `task_id`/`session_id`/
  `user_id`. A schedule firing — which has no incoming HTTP request — mints
  its own fresh correlation root inside a detached execution context rather
  than admitting uncorrelated or risking a stray id from an unrelated
  Attempt still bound on the same event loop tick. The id is correlation
  metadata only; unlike the signed Workspace-scope headers, it can never
  assert scope or authorization.
- **Recurring schedule admission has cross-backend parity tests (#46).** One
  scenario runs through `ScheduleRunAdmitter` on the in-memory, SQLite and
  PostgreSQL stores (wired by `wire_execution_spine`): an hourly schedule with
  `max_runs=2` fires, is disabled and re-enabled without losing its
  `runs_so_far`/`last_run_id`, fires its last run and is disabled with
  `next_due_at` cleared in the same write. A schedule whose first occurrence
  has not arrived records its `next_due_at` and leaves `due()`. All three
  backends must leave identical cursor state (`enabled`, `runs_so_far`,
  `last_run_id`'s occurrence, `last_fired_at`, `next_due_at`).

### Changed

- **Evolve proxy fitness no longer credits text narration (#384).** The
  `proxy_gaia` scorer lost its fuzzy fallbacks (0.9 raw-substring, 0.85
  digit-set, 0.7 word-overlap, and the `max(exact, judged)` merge): only a
  normalized/numeric exact match earns unjudged score, everything else is
  verified solely by the LLM judge (fail-closed 0.0 on judge failure), with an
  optional `judge_llm_call` to verify with a different model than the candidate
  answered with. The `proxy_ragas` scorer's word-overlap primary score, its
  `>= 0.6` judge-skip and its `max(static, judged)` merge are gone — the judge
  runs for every sample and is the only credit path; the static overlap is
  reported as an explicitly uncredited diagnostic. `proxy_bfcl` and
  `proxy_tau_bench` (already structured-call-only since #852) and the two fixed
  scorers now record evidence provenance in `EvalResult.metadata["evidence"]`,
  folded into the new `PipelineGenome.eval_evidence` and surfaced by the new
  `PopulationStore.champion_provenance()`. Stored genomes gain an
  `eval_evidence` field (defaults to `{`). New `benchmarks/calibration.py`
  measures each scorer's narration false-positive rate against held-out
  adversarial fixtures (`calibrate_proxy_scorers`). Serialized-genome consumers
  that rejected unknown fields must tolerate the new key. Both acceptance
  surfaces are operator-reachable: `python -m maistro_rsi evolve` prints the
  champion's per-benchmark score→evidence provenance, and a new
  `python -m maistro_rsi calibrate` runs the harness offline against a stored
  genome and reports each scorer's narration false-positive rate (reporting
  only — the fitness hard gates stay the only scoring authority).

- **Terminal BACKLOG.md items must carry closure evidence (#101, partial).**
  `scripts/check-backlog-consistency.py` now fails an `Implemented` item with
  no PR/issue link or existing repo file, a cited repo path that no longer
  exists, and an `Abandoned` item with no reason. The 21 items closed before
  the rule are frozen with their status in a legacy set that can only shrink,
  so a new closure cannot pass without a link or file. The gate checks that
  evidence is present, not that it proves the claim; a reviewer still judges
  that.

- **The Coverage gate's job timeout is 30 minutes instead of 15.**
  (no linked issue: base-branch CI capacity) The timeout change itself landed
  with #1592; this records it. The gate runs its non-publish suites serially
  after the publish-set floor (six when measured, seven since
  maistro-registry joined; the root `tests/` suite alone took 7m49s on
  #1591), so it was finishing at ~14 minutes and being cancelled at 15 on
  some PRs, which blocks the PR without measuring anything. The measured
  suites, `--source` set, the 87% publish-set floor and the 90% line / 80%
  branch diff thresholds are unchanged. Running those suites as parallel
  producers is tracked separately in #1605.

- **A chat turn that cannot get its canonical Run is refused with a retryable
  503 instead of answered ungoverned (#1108, partial).**
  Owner decision 2026-09-23, amending ADR-082326-c126 and superseding #223 AC4.
  `Container.route_request` raises the new `maistro.runs.chat_refusal.ChatTurnRefused`
  when no chat admitter is wired, admission fails (after compensating any Run it
  persisted), there is no Run store, or the spine fails (with any error) before
  the dispatch started — the `except RunIntegrityError: return await dispatch()`
  fallback is gone, and an error the dispatch itself raised is never turned
  into a retryable refusal, so
  nothing reaches the model outside a Run/NodeRun/Attempt. maistro-server
  `/v1/chat/completions` maps it to `503` + `Retry-After` for both
  `stream=false` and `stream=true` (admission is refused before the
  `StreamingResponse` is built; a refusal inside the stream emits an
  `unavailable` SSE error event), the app's `HTTPException` handler now
  keeps route-supplied headers, and CORS exposes `Retry-After` to browser clients. Post-dispatch spine failures still return the
  answer once as `ChatDispatchUnrecorded`. Hive `/chat/complete`,
  `/chat/stream`, `/voice/intent` and Workspace Agent chat are not yet covered.

- **Hive conversation-only chat and voice turns run as canonical chat Runs
  (#1037).**
  `/v1/chat/complete`, `/v1/chat/stream` and `/v1/voice/intent` now admit
  every model-reaching turn as a Run over the one-node chat Graph in the
  turn's Workspace (the named one when the caller can see it, else the
  caller's default Workspace), call the conversation-only model from inside
  that Run's Attempt stamped with the Workspace Agent, and close the Run
  through the Container (FAILED on a model error). Responses carry `run_id`
  and the Workspace Agent id under `agent` additively (`run_id` on the
  stream's `done` event for `/stream`). A turn that cannot be admitted is
  refused with `503` and `Retry-After` before the model is called -- which
  includes a Hive running on the stub engine with no maistro-core runtime
  (`MAISTRO_ROUTER_API_KEY` unset or the bridge failed to start): chat and
  voice now need the runtime. Tools stay disabled; session ids are recorded
  as Run provenance only.

- **Hive and maistro-server now share one durable Workspace owner (#37,
  ADR-092326-97c4).** The shipped `docker-compose.yml` gives `hive-conductor`
  the same `DATABASE_URL`/`DB_*` as `maistro-engine` and starts it only after
  PostgreSQL and the (self-migrating) engine are healthy, so Hive's embedded
  Container uses the `canonical_workspaces` tables maistro-server serves. On
  that durable path Hive's `stores.workspaces` mirror is imported once
  (journal-idempotent, never resurrecting a Workspace or membership deleted or
  revoked canonically) and is no longer written or replayed; a configured
  database whose Container failed to start now fails Workspace authorization
  closed instead of reviving the mirror. The no-database dev path is unchanged.
  Hive's whole embedded Container (Runs, sessions, learnings, schedules) now
  uses that shared database too, not only its Workspace store.
  Hive's `/health/ready` now counts that store: with a database configured
  and no Container it answers 503 with `ready: false`, so Compose stops
  reporting an instance whose Workspace API only fails. The Hive image now
  ships the agent roster (`agents/` → `/app/backend/agents`), which the
  embedded bridge requires to start at all. `create_container()` no longer
  refuses to build when the `identity` extra is missing (the Python 3.14 Hive
  image cannot install it): it leaves the identity lifecycle stores unwired,
  and the Container's identity methods still raise the ImportError that names
  the extra.

- **`sessions` and `session_turns` are recorded as TTL-purged on both
  backends (#325).**
  The retention inventory said PostgreSQL session rows accumulate, but
  `PgSessionStore.append_messages` (the store the PostgreSQL container wires)
  already deletes expired messages and turn markers inside each writing
  append transaction, as `SqliteSessionStore` does after commit. The purge is
  driven by appends, so expired rows persist until the next one. Both entries are now
  `ttl_purge` with the append path as their deletion path, backed by a SQLite
  and PostgreSQL-gated regression that ages real rows past the TTL and proves
  the next append removes them from both tables.

- **A declared correlation field must have a production producer (#63).** A
  fitness test scans production code (`packages/*/src` and the hive, turing
  and canvas backends) for `bind_execution_context(...)` keywords. It fails
  when no production call binds a `FIELD_NAMES` entry into the execution
  context that log lines, spans and events read, so a newly declared field
  cannot ship without a producer. Nothing binds `invocation_id` or
  `session_id` into that context yet. Both sit on a reviewed allowlist that
  names the owning #63 slice. The test also fails once
  an allowlisted field gains a producer, which keeps the allowlist from going
  stale.

- **The Conductor frontend renders on the Workspace design system (#1046,
  #1048, #65; ADR-091626-ba4f).** `frontend/src/themes/workspace-tokens.css`
  is a byte-for-byte copy of the bundled `workspace` tokens, held identical by
  a backend test; a bridge file binds the old Conductor variable names
  (`--paper`, `--ink`, `--pencil`, `--rule`, `--honey`, `--purple`, the shadow
  scale…) to them so every page keeps rendering while it moves over, with one
  accent, no gradient and no hover glow. Light/dark is now `data-scheme` on
  `<html>` (the user's choice or the OS preference) and a workspace's persona
  template is `data-theme`, so a theme never forces a scheme; the hand-written
  `dark` and `fantasia` stylesheets are gone. The theme catalog
  (`GET /v1/workspaces/themes`) offers the design system's templates,
  greenhouse (default), slate and studio; workspaces stored with `default`,
  `dark` or `fantasia` stay valid and render as greenhouse, greenhouse and
  slate. Bricolage Grotesque ships from the app's origin beside JetBrains
  Mono, and every font size below the 12px floor (23 in the stylesheet, 524
  inline) is raised to it.
- **The merge-queue bot quarantines a head that already failed inside the
  queue (#1438 review follow-up).** `scripts/check-enqueue-merge-queue.py`
  re-requested any policy-green PR head on every scan, including one the
  queue had just ejected, so with batched groups a bad head dragged each new
  group through a rebuild every 30 minutes. The controller now reads the
  recent merge-group run history (the workflow gains `actions: read`),
  attributes each failed entry to its own tree or to a failed entry ahead of
  it via the `gh-readonly-queue/develop/pr-N-<sha>` chain, and holds any head
  whose own entry failed after that head's `gates-ran` first went green. A
  new push or a human enqueue lifts the hold; an unreadable history refuses
  every admission. `scripts/check-required-checks.py` additionally pins
  `grouping_strategy=ALLGREEN`, and `measure-merge-latency.py` reports how
  many dequeued candidates were rebuilt behind another PR's failure.

- **HALF_OPEN circuit-breaker success is now caller-bound (#828).** `record_success()`
  closes a HALF_OPEN circuit only when called by the thread or asyncio task
  whose `allow_request()` call acquired the current exclusive probe lease;
  successes from other callers are ignored. A probe owner can call
  `release_probe()` to let another caller claim the probe.

- **Governance gates read content, not tokens (#385, #387, #391).** The
  release-consistency gate now requires meaningful categorized, issue-linked
  `## [Unreleased]` entries and refuses to publish an empty section at tag
  time; a new registry gate fails ADR/spec body status language that
  contradicts front matter (28 legacy body status lines are baselined and
  ratchet down); pytest runs with `--strict-markers` and CONTRIBUTING's
  marker table is validated against `pyproject.toml`. Operators must do the
  same in kind: placeholder-only Unreleased content fails, and unknown
  pytest markers fail collection.

- **Branch guidance is single-sourced and CI-checked (#381, #383).** README
  no longer recommends the gate-missing `feature/*` spelling; the accepted
  topic-branch prefixes live once in `.github/branch-protection.json` and
  the quality/security push triggers cover every documented prefix; the PR
  template names `develop` as the base and a new `pr-base` CI job fails
  mis-based PRs with the correction (`main` requires the `release` label).

- **README claims reconciled with code (#388).** Schedules execute (Partial,
  not TODO — Run admission, `max_runs`, and the #251 convergence limit stated);
  embedding schema (vector(1536) + HNSW) is stated separately from readiness
  (no production embedding client is constructed, so the column stays NULL);
  the matrix no longer claims scoped pgvector recall is live.

- **`derive_run_terminal_status`'s `work_owed` is now a required keyword
  argument (#1188).** The previous `work_owed: bool = False` default let a
  caller that forgot to pass it derive `COMPLETED` from an empty NodeRun
  collection, silently treating "no observations yet" as "there was never any
  work to observe." Both current production callers already passed it
  explicitly and are unaffected; a caller that omits it now gets a
  `TypeError` at the call site instead of a wrong terminal status at runtime.

### Fixed

- **Project membership is one canonical row per `(project, principal)`, and
  is now explicitly revocable (#1148).** `ProjectScopeStore.set_membership`
  used to mint a fresh `membership_id` on every call, so a re-grant, role
  change, or explicit deny accumulated a second, independent row instead of
  replacing the first — `resolve_project_authorization` unions every row it
  finds, so a stale grant a later deny was meant to narrow stayed live
  forever, and there was no way to retract a grant outright. `set_membership`
  now upserts keyed on `(project_id, principal_id)` across all three
  backends, and a new `remove_membership` revokes a membership durably. A
  migration (`033`) deduplicates existing PostgreSQL rows (keeping the most
  recent per pair) before adding the new primary key; a homelab SQLite
  database created by an older release upgrades its
  `canonical_project_memberships` table the same way the first time
  `ensure_schema()` runs against it.
- **A delegated re-grant can no longer silently clear an existing Project
  deny (#1148).** `add_project_membership`'s non-owner path only rejected a
  request that explicitly repeated `denies`, not one that simply omitted
  them — since `set_membership` now replaces the canonical row wholesale
  rather than accumulating a second one, a non-owner's ordinary grant-only
  re-grant would have overwritten an owner-issued deny by omission. The
  route now carries an existing deny forward when the requester cannot
  administer the Workspace.
- **SQLite `move_project` now serializes the cycle check with the reparent
  write (#1147).** PostgreSQL already locked a Workspace's Projects with
  `FOR UPDATE` before checking ancestry; the SQLite twin did a plain
  read-then-write, so two concurrent opposite moves (A under B, B under A)
  could both pass their independent checks and both commit, leaving a cycle
  `lineage()` can never resolve again. `move_project` now takes SQLite's
  write lock (`BEGIN IMMEDIATE`) before reading the tree, matching
  `workspaces.sqlite_store`'s existing pattern; a forced-interleaving
  conformance test (two connections to the same file) proves one of the two
  concurrent moves is refused as a cycle rather than both landing. Every
  other writer on the shared connection (`create`, `update_defaults`,
  `delete`, `put_resource`) now takes the same write-critical section, so an
  unlocked writer left mid-transaction can no longer make a locked writer's
  `BEGIN IMMEDIATE` raise outright.
- **Successful NodeRuns require accepted physical evidence (#1153).** New
  completion transitions reject a missing `AcceptedNodeOutcome`, including for
  no-output work. The historical durable-Graph execution entry points delegate
  to the canonical Attempt executor instead of completing nodes without
  Attempts. Legacy completed records remain readable and may receive matching
  evidence without changing their result or lifecycle timestamps.

- **Naive Workspace timestamps no longer decode to a different instant
  depending on the reading host (#1149).** `Workspace.created_at`/`updated_at`
  and `WorkspaceMembership.added_at` now normalize a naive datetime to UTC
  deterministically, the same convention `maistro.scheduling.model.Schedule`
  already applies to its own timestamps. Previously, SQLite's `_iso()` helper
  called `astimezone(UTC)` on whatever it was given, which for a naive value
  (e.g. a legacy `created_at` supplied to `create(..., created_at=...)` during
  a convergence import) asked the process's local timezone to interpret it —
  the same stored row would decode to a different instant depending on which
  host read it.

- **A resumed scheduled Attempt now carries the same crash-recovery lease as
  its first physical try (#1112, #1124).** `ScheduleAttemptExecutor`'s resume
  path built its `RunExecutionService` without `lease_ttl`, so a fresh Attempt
  created on resume got the default `lease_ttl=None` — no expiry, never
  reclaimable — even though first reach opted into a finite, heartbeat-renewed
  lease. A scheduled Run was therefore crash-recoverable on its first attempt
  and could be stranded `RUNNING` forever after any later timer/HITL pause.
  The resume path now forwards the same `lease_ttl` the executor was
  constructed with.

- **A malformed HITL answer can no longer reset a paused node's durable
  deadline (#1097).** `human.approve_draft`, `human.delegate_to_role`, and
  `human.review_and_edit` recomputed `now + timeout_seconds` whenever a
  resumed answer had a missing, blank, or non-string `verdict`, so repeated
  malformed answers arriving near the deadline could extend a canonical HITL
  pause indefinitely. All three now recover the original deadline from the
  durable pause evidence (`answer_record`'s stamped `_pause` field) the store
  already carries on every resumed answer, and fall back to a freshly
  computed deadline only on a node's very first pause, where no earlier
  deadline exists to preserve.

## [1.0.0] - TBD

First tagged release. Prior to this, the repository had no tags, no release
workflow, and no changelog; `develop` was the only integration point.

### Headline

- **Evolve + RSI ship as first-class v1 features**, not experiments — a genome
  tournament optimizer (`maistro-evolve`) and a recursive self-improvement loop
  (`maistro-rsi`) that proposes, sandboxes, and scores changes to this very
  repository.

  **Read this caveat before trusting a score.** The benchmark scorers are
  **proxy-tier** and are now named accordingly — `proxy_ifeval`, `proxy_bfcl`,
  `proxy_swebench`, `proxy_tau_bench`, `proxy_gaia`, `proxy_ragas`,
  `proxy_terminalbench`, `proxy_swebench_pro`. **None of them runs the official
  published benchmark harness against the official dataset**; all score real
  model output at a small, handcrafted scale. Fidelity is *not* uniform even
  within that tier: `proxy_swebench`/`proxy_terminalbench` execute candidate
  code in a real sandbox and assert a real outcome, `proxy_ifeval` performs
  genuine per-instruction rule checks, while `proxy_bfcl`, `proxy_gaia`, and
  `proxy_tau_bench` each carry a text-mention or fuzzy-substring fallback that
  materially weakens them, and `proxy_ragas` is primarily keyword overlap.
  `proxy_osworld` is defined but not runnable. Per-benchmark detail —
  including the exact degenerate cases — is in
  `packages/maistro-evolve/CLAUDE.md`. Real official-harness adapters are
  v1.1 (SPEC-202).

### Added

- **`maistro-core`** — the shared runtime, published to PyPI: memory
  (learnings, episodic, scopes, outcomes), security (Warden threat detection,
  Sentinel policy, PII filtering), classifier, router, agents, builders, A2A
  delegation, skills, graph execution (ADR-062), ontology (ADR-036),
  resilience (ADR-038), quota, sessions, and the DI container.
- **`maistro-canvas`** — the standalone canvas ability: engine, PIL-based
  compositor, PostgreSQL store, REST routes, and protocol interfaces.
- **`maistro-server`** — a thin FastAPI wrapper over the core library.
- **hive-conductor** — the Agent Conductor application (FastAPI backend +
  React SPA). Not published to PyPI; shipped as a container image.
- **`maistro-bootstrap`** — installer and planner CLI.
- `docs/testing/SUITE-INVENTORY.md` — per-suite collected node-ID counts and
  the exact commands to regenerate them.
- `KNOWN-GAPS.md` — the curated register of shipped-but-limited behavior.

### Fixed

- **Unauthenticated arbitrary file read in the Conductor.** The SPA fallback
  route joined an attacker-controlled path onto the static root without
  containment. Because `pathlib` discards the left operand when the right one
  is absolute, `STATIC_DIR / "/etc/passwd"` resolved to `/etc/passwd` — no
  `..` needed — and the route is not behind `AuthMiddleware`, which
  authenticates only `/v1/` paths. Any file readable by the server process was
  retrievable without credentials, including the credential master key, the
  encrypted credential store, and the session database. Now resolved and
  containment-checked against the static root.

  **Operators upgrading from a pre-1.0.0 checkout that was network-reachable
  should treat the credential master key, stored integration credentials, and
  all active sessions as disclosed, and rotate and purge accordingly.** The fix
  prevents further reads; it cannot undo reads that already happened.
- **The Conductor no longer reports fake success when no LLM is configured.**
  The graph runner returned a normal-looking `{"response": "stub: no LLM
  configured", "done": true}` whenever `LITELLM_*` was unset, so a
  misconfigured deployment produced results indistinguishable from real ones.
  It now refuses outright. Set `ALLOW_STUB_LLM=true` to opt in to stub
  responses; those are labelled `"stub": true` in the payload so nothing
  downstream can mistake one for a real result.

  **This can look like a regression.** The graph runner reads `os.environ` and
  never picks up `LITELLM_API_BASE` from `backend/.env`, so a `.env`-only
  deployment was already silently receiving stubs and will now fail loudly
  instead. docker-compose passes the variable as a real env var and is
  unaffected.
- Canvas authentication no longer returns an admin user regardless of the
  supplied API key.
- Design PNG rendering returns a clean `501` rather than surfacing an
  unhandled `NotImplementedError`.
- Two canvas frontend runtime defects an absent lint gate had been hiding: an
  invalid duplicate ESM export that made a whole module unparseable by the
  linter, and a `ReferenceError` in a normalization fallback path.

### Changed

- Benchmark identifiers renamed to the `proxy_*` form described above. **This
  is a breaking change for any stored genome, fitness configuration, or
  tournament state keyed by the old bare names** (`ifeval`, `swebench`, …).
- Dependencies now carry upper bounds in every package.
- hive-conductor gained a `pyproject.toml` and joined the `uv` workspace.
  `backend/requirements.txt` **remains the install path** used by the
  Dockerfile and CI — change a dependency in both.

### Security

- Warden, Sentinel, and the strike ladder are wired through the DI container.
- Constant-time comparison for privilege and admin-key checks.
- CI runs bandit, semgrep, gitleaks, pip-audit, and container scanning.

### API compatibility

**The stable HTTP surface is the `/v1` route mount.** Clients should
address `/v1/...` paths directly. The `/v1` path segment is the stable
resource mount; the *behavioral* version is negotiated, not taken from the
path.

[ADR-076](docs/adr/ADR-076-http-api-versioning.md) version selection is
**implemented** on both business HTTP surfaces (`maistro-server` and
hive-conductor) by the shared `maistro.api_versioning` middleware: a request
selects a version via the `Accept: application/vnd.maistro.vN` media type, an
`api_version` query parameter, or an `api_version` JSON body field; every
response states the served version (`Maistro-API-Version`) and the default
(`Maistro-API-Default`); an unsupported version is refused with `406`. Only
version 1 exists today; a client that sends no selector gets version 1 and
plain `application/json`. The canvas `application/vnd.canvas+json;version=2`
media-type check at `/v2/canvas` is a canvas-local response-format mechanism,
not the general API-version scheme. Do not treat it as one.

The API version axis is independent of the package version: a `1.x` package
release does not imply a `/v2` HTTP surface.

### Supported deployment profiles

See [`docs/product/DEPLOYMENT-STANCE.md`](docs/product/DEPLOYMENT-STANCE.md)
for the supported-profile matrix. Configurations outside it are not covered by
the v1 support statement.

### Known limitations

Verbatim from [`KNOWN-GAPS.md`](KNOWN-GAPS.md), which is the maintained
register:

> v1.0.0 ships with an in-memory task queue, so a restart loses queued and
> active tasks. Canvas jobs require an external runner; Canvas publish and
> some export formats are not implemented. The mounted Canvas data routes are
> unconfigured in the default shipped service and return `503`. Design Studio
> can discover resources and select artifact modes, but visual generation,
> editing/preview, and publish/export are not available. Conductor can run in
> degraded mode when optional services are unavailable.

[Unreleased]: https://github.com/Agent-StrongHold/Project-mAIstro/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Agent-StrongHold/Project-mAIstro/releases/tag/v1.0.0

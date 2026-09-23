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

### Security

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
  `next_due_at` cleared in the same write. A far-future schedule records its
  `next_due_at` and leaves `due()`. All three backends must leave identical
  schedule rows.

### Changed

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

- **`ScheduleRunAdmitter` no longer breaks a downstream `ScheduleStore` that
  predates crash-recovery credit (#1533).** `record_fire` grew a `recovered`
  keyword argument, with a default, when `Schedule.recovered_occurrences`
  recovery landed (#1059) -- but the admitter named it on every call
  regardless of whether there was anything to credit, so an external
  `ScheduleStore` implementation using the previously valid
  `record_fire(self, schedule_id, *, fired_at, run_id, next_due_at,
  fires=None, disable=False)` signature raised `TypeError: unexpected
  keyword argument 'recovered'` on every ordinary recurring fire after
  upgrading, not merely a recovering one. `recovered=` is now passed only
  when the set is non-empty, which keeps the common, no-recovery case
  working unchanged against an older store; a genuinely recovered claim
  still names it, and a store that cannot accept it still fails loudly
  rather than silently losing the credit. `maistro-core`'s own
  implementations (the protocol, `InMemoryScheduleStore`,
  `SqliteScheduleStore`, `PgScheduleStore`) already accept the keyword and
  are unaffected.
- **Builders' canonical pipeline executor no longer disagrees with legacy
  gate/revision, step-budget, and failure-reporting semantics (#1067).** A
  post-merge audit of #734/#744 found 4 parity defects in
  `CanonicalGraphPipelineExecutor`, two of which could silently mark a Run
  `COMPLETED` while a gate was still failing or dropping a same-wave
  sibling's stale output into a revised stage's input: (1) a same-wave gate
  revision now invalidates its stale descendants only after the whole ready
  frontier settles, instead of racing a slower sibling's own commit inside
  the failing node's coroutine; (2) a gated stage with no `revise_target`
  already re-offered itself correctly (fixed on `develop` before this audit
  landed); (3) the durable walk's step bound is now derived from Builders'
  own admitted pipeline size and iteration budget instead of inheriting an
  unrelated generic 256-step ceiling that could fail a large valid pipeline;
  (4) two stages failing in the same concurrent wave now project one
  consistent authoritative failed stage and error, derived from canonical's
  own selected failure, instead of a reversed `NodeRun` scan paired with a
  separately racing shared error variable. A follow-up review found three
  correctness gaps in that same fix before merge: the revision ledger's
  `flush()` was applied once per *stage dispatch* rather than once per
  *frontier*, so a fast/immediate dispatcher could still fail a genuine
  wave-mate out of its own admitted wave (the flush now runs from the
  canonical node resolver, which only ever fires once per frontier, strictly
  after the previous frontier's whole dispatch batch has returned); the
  transient "stale guard" skip marker was not cleared before a stage's real
  redispatch, so a stage that failed for real after an earlier stale defer
  was misreported `SKIPPED` instead of `FAILED` (now cleared as soon as the
  stale guard is passed, before any real work is attempted); and the derived
  step bound assumed a skip-only frontier happens at most once per graph
  node for the whole run, undercounting a revision that repeatedly replays
  an already-skipped node's frontier (now scales the free-frontier
  allowance by graph size per real dispatch, not by a flat one-per-node
  total).

- **Every ADR body status line now agrees with its front matter, and the
  body-status ratchet is empty (no linked issue: completes the `#387` cleanup
  begun in the entry below).** The 28 legacy contradictions `#387` banked are
  corrected rather than carried: 25 ADRs whose body said `Proposed` while
  front matter said `Accepted`, 2 saying `Proposed` against `Deferred`, and
  `ADR-001` saying `Accepted` against `Superseded` on a document whose own
  banner already pointed at `ADR-095`. Readers of those 28 were being told a
  weaker status than the lifecycle machine, the AC ladder and the citation
  gate all act on. `quality/adr-status-language-baseline.json` is now `[]`, so
  the gate has nothing left to tolerate and any contradiction it reports is
  new by construction; refilling it is an expansion needing a landed grant
  (`#534`). Two tests that sourced their fixture from the ledger being
  non-empty now introduce and bank their own contradiction, so a clean corpus
  no longer fails the suite that guards it.

- **The body/front-matter status gate no longer exempts documents by the shape
  of their status line (no linked issue: found while fixing the order-dependent
  tests in `tests/test_check_adr_status_language.py`).** `#387`'s category-1
  check matched only a bare `**Status:** X` line, so the 3 ADRs and 20 specs
  that write the same declaration as a Markdown list item (`- **Status:** X`)
  were outside the check entirely -- the form of the line, not its content,
  decided whether a contradiction was visible. It also read only the first word
  of the value, which reported `AC` against a front matter saying `AC Defined`.
  Both forms are now read and the whole value is compared, which surfaced 19
  specs whose body said `Active` while their canonical front matter said
  `AC Defined`; those bodies are corrected to the front-matter value rather
  than banked, so the baseline stays at the 28 legacy entries `#387` recorded.

- **The stranded chat-admission sweep survives a vanished Run (#338).** Two
  defects in the recovery tick #1280 shipped, both found by review after it
  was already queued for merge. `list_node_runs()` raises
  `RunNotFound` on all three stores, and `RunNotFound` is a `KeyError` that
  neither `except` arm caught -- so a Run terminalized by another worker and
  deleted by the chat retention sweeper before this tick's own lookup aborted
  the whole sweep, leaving every later stranded Run uncompensated until the
  next tick hit the same Run. It is now skipped as the settled race it is. The
  scan also asked only for `RunStatus.RUNNING` and rejected foreign Runs
  per-candidate, so an operator whose RUNNING set is mostly scheduled work paid
  for hydrating all of them every tick; it now passes `admission_source` into
  the query, which both SQL backends push down. The per-candidate source check
  stays as defense in depth.

- **Ratchet bases resolve for rebased topic pushes (no linked issue: CI infra).**
  Restores the #727/#534 base rule in three workflows that had drifted off it.
  `quality.yml`'s coverage gate, `ci.yml`'s root suite and
  `vulture-ratchet.yml` named
  `RATCHET_BASE_REV` themselves and fell through to `github.event.before` for
  *every* push. That is right only for a protected branch, which really does
  replace that revision; on a topic branch `before` is the branch's own
  previous tip, and any rebase orphans it — unreachable from every ref, so
  `fetch-depth: 0` (which fetches refs, not orphans) cannot supply it. The
  ratchet then refused with "base revision could not be resolved" and the
  candidate went red on base provenance while its pull-request run passed on
  byte-identical content; a re-run could not clear it, because `before` is
  fixed in the stored event payload. All three now use the integration base
  for topic pushes, matching the two sibling declarations that were already
  correct and what `ratchet_provenance._push_event_base` computes when no base
  is named. A new test pins the shape of every declaration so the two
  behaviours cannot drift apart again.

- **The Simple/Power toggle is removed rather than left silently inert
  (#1409, #1411, #1410).** It promised "Power Mode (DAGs, prompts, topology)" but
  changed nothing observable: `AppShell.tsx`'s navigation never branched on
  it, only `localStorage` did. `ModeToggle`, `ModeProvider` and the
  `hive_ui_mode` key are gone; a browser that stored the key before this
  shipped still gets it swept on sign-out. Persona-driven surface
  configuration — the feature the control was standing in for — is deferred,
  not withdrawn: ADR-081226-e626 gains an amendment recording the removal
  and why, and disambiguating "mode" from the two senses that remain
  (light/dark appearance, `workspace_mode.py`'s authorization sense).
  `tests/e2e/workspace-toolbar.spec.ts` covers it; against the unfixed
  build the drawer still shows the retired control.
- **The shell paints its chrome before the auth chain resolves, and the
  setup-status and whoami probes fire together instead of one after the
  other (#1408).** The Conductor used to await `/v1/setup/status`, then
  `/v1/auth/whoami`, showing a plain "loading hive..." sentence for both
  round trips; whoami's answer never depended on setup's, so the second
  wait bought nothing. Both requests now fire together, and the
  placeholder is the real shell's sidebar-plus-content grid rather than a
  sentence. A fresh, unconfigured instance no longer waits on whoami at
  all before showing the setup wizard — only setup-status's own response
  gates it, so a whoami that is slow or never settles can't strand a new
  operator on the skeleton (caught in review before merge). `tests/e2e/app-shell-loading.spec.ts`
  holds `setup/status` open to prove whoami is requested while it is
  still pending, that the skeleton renders meanwhile, and that a hung
  whoami doesn't block the setup wizard on a fresh instance; each
  assertion fails against the unfixed build.

- **The Jira draft modal's fields answer to their visible labels, and a
  required clarifying question announces as required (#1406).** Every
  clarifying-question and edit-step field rendered its `<label>` as a
  sibling of its `<input>`/`<textarea>`, with no `htmlFor`/`id` pairing, so
  the computed accessible name was empty and a screen reader announced an
  unlabelled textbox. A required clarifying question's `*` was a plain
  visual character with no `aria-required`. The label now wraps its
  control — the same implicit-association pattern `PersonaWizard.tsx`
  already used — and a required clarifying question carries
  `aria-required="true"`. `tests/e2e/work-item-draft-labels.spec.ts`
  covers both steps by accessible role and name; against the unfixed
  build the first assertion fails.

- **The Dashboard's template picker shows a real loading skeleton, not an
  invisible div (#1421).** `TemplatePicker.tsx` rendered
  `<div className="skeleton skeleton-card" />` while its
  `/v1/dashboard/demos` fetch was in flight, but neither `.skeleton` nor
  `.skeleton-card` had a matching CSS rule anywhere in the stylesheet — the
  element existed with no size and no background. Both classes now resolve
  to real rules, reusing the pulse animation the app-shell skeleton
  (`#1408`) already defined. `tests/e2e/template-picker-skeleton.spec.ts`
  slows the fetch and asserts the skeleton has a non-zero bounding box;
  against the unfixed build it times out as hidden.

- **Infinite pulse/spin/bounce animations respect
  `prefers-reduced-motion`, and the shared switch control announces a name
  (#1415, #1414).** Only the skeleton pulse (`#1408`) was guarded; the
  dashboard status dot's `status-pulse` (2.2s), the chat typing
  indicator's `bounce` (1.4s), and a running tool step's `loading-spin`
  (1s) all looped forever regardless of the OS motion setting. All three
  now sit in the same guarded block as the skeleton pulse.
  `tests/e2e/dashboard-reduced-motion.spec.ts` asserts the status dot's
  computed `animation-name` is `none` under a reduced-motion preference
  and `status-pulse` without one; against the unfixed build the first
  assertion fails. Also: `shared.tsx`'s `Toggle`'s `role="switch"` button
  had no accessible name — its label text was a sibling, not associated —
  so it now also carries `aria-label`; `Toggle` has no current consumer in
  the frontend (confirmed via full git history search), so this is a
  source-only fix with no reachable regression test, the same shape as
  `#1413`.

- **Routed pages are code-split instead of riding along in one bundle
  (#1435).** The 24 pages behind `AppShell`'s routes were all statically
  imported into `App.tsx`, so the production build warned on a ~600kB
  chunk and every page paid for every other page's JS regardless of which
  one it rendered. Each is now `React.lazy`-loaded behind a `Suspense`
  boundary reusing the app-shell skeleton (`#1408`) as its fallback; the
  main chunk drops to ~300kB and the build no longer warns. `Setup` and
  `Login` stay eager — one of them is on the critical path for every
  session's first paint. `tests/e2e/route-code-splitting.spec.ts` asserts
  a cold load of `/dashboard` fetches only the Dashboard route's chunk,
  not an unvisited route's; against the unfixed build the first assertion
  fails, since no per-route chunk exists at all.

- **API failures surface as human copy with a recovery hint, not raw
  transport strings (#1436).** The shared request helper
  (`lib/api.ts`) threw `` `${path}: ${detail}` ``, falling back to the
  bare status code (e.g. `500`) when the backend gave no `detail` —
  shown verbatim in toasts and inline errors across the app (an observed
  case: `/v1/workspaces/…/members: Permission 'workspaces.write'
  required...`). The thrown message is now the backend's `detail` alone
  when present (already human copy in this API), or one of a small set
  of status-family sentences with a recovery hint otherwise; the raw
  path/status still travel on the new `ApiError`'s `.path`/`.status` for
  developer diagnostics, not in the primary message. Three call sites
  that bypass the shared helper with their own `fetch()` (`Setup.tsx`,
  `Chat.tsx`'s stream, `LlmProviders.tsx`) reuse the same fallback
  sentences; two others (`KnowledgeBase.tsx`, `Dashboard.tsx`'s
  assistant) already discarded the raw error before display and needed
  no change. `tests/e2e/api-error-copy.spec.ts` mocks a 500 with no
  `detail` and asserts the toast contains neither the route nor a bare
  status number; against the unfixed build it fails on exactly that
  assertion.

- **The shared API client times out and recovers, instead of leaving a
  hung request's spinner up forever (#1423).** `lib/api.ts`'s `request()`
  wrapped `fetch` with no timeout or `AbortController`; only Chat's own
  streaming fetch and the dashboard assistant widget guarded against a
  hung request, so the other ~28 pages that go through the shared client
  did not. It now aborts after 30s, and — same class of bug as #1436 —
  any transport-level failure (the abort, a dropped connection, offline,
  CORS) is wrapped in the same human, retryable `ApiError` a bad HTTP
  status gets, rather than surfacing as a raw `TypeError: Failed to
  fetch` or `AbortError`. `tests/e2e/api-timeout.spec.ts` drives the
  same try/catch/wrapping code the timeout path shares via
  `route.abort()` (fast and deterministic — the real 30s budget isn't
  practical to wait out inside this suite's own CI time limit) and
  asserts the shown message has no raw error name; against the unfixed
  build it fails on exactly that assertion.

- **Toggling a schedule or editing a memory entry no longer costs two
  round trips (#1422).** `Schedules.tsx` and `Memory.tsx` followed every
  create/update/toggle/delete with a GET of the entire collection, the
  same pattern `WorkspaceContext.tsx`'s archive/delete already fixed for
  workspaces. Both pages now patch the changed record into local state
  from the mutation's own response instead. `tests/e2e/optimistic-mutations.spec.ts`
  asserts no collection GET follows a toggle, create, or delete; against
  the unfixed build both specs fail on exactly that assertion.

- **The workspace toolbar explains a first run, truncates long names, shows
  personas by name and tagline, and forgets an account on sign-out (#1426,
  #1431, #1424, #1437, #1418, #1433).** A zero-workspace account now sees a
  one-line explanation of what a workspace is and a "Create workspace"
  action instead of a bare "+". The tab strip holds only tabs and scrolls
  sideways in one row; a long name truncates with an ellipsis and keeps its
  full text in the tooltip, so the toolbar no longer stacks into a column at
  phone width. The create form is a panel below the "+" whose persona picker
  is a radio group showing each persona's name and tagline. The four
  per-account localStorage keys (active workspace, appearance, UI mode,
  onboarding) are stamped with the signed-in user, cleared when a different
  account signs in, cleared on sign-out, and listed with their values on the
  Profile page beside a "Clear browser state" button.
  `tests/e2e/workspace-toolbar.spec.ts` covers each in a real browser.
- **A Workspace and its Root Project are created and deleted in one
  transaction (#1121).** The durable Workspace stores wrote the Workspace row
  and its owner membership, committed, and only then asked the Project store
  for the Root Project on a second connection, with an in-process compensator
  covering an exception between the two and nothing covering a crash there;
  `delete` was the same in reverse. A process that died between the halves
  left a Workspace with no Root Project -- which `root_for_workspace()` treats
  as impossible, so every Run filed to it failed -- or a Project tree with no
  Workspace to reach it by. The PostgreSQL and SQLite Project scope stores now
  expose `TransactionalProjectScopeStore` (`transaction()`, `create_root_in`,
  `purge_workspace_in`), and the Workspace store on the same pool or
  connection issues all of its rows and the Root Project inside that one
  transaction, so either all of it commits or none of it does. On SQLite the
  Workspace store also takes the scope store's write lock rather than one of
  its own, since two locks over one connection is how "cannot start a
  transaction within a transaction" arises. No root is invented lazily on
  read: `root_for_workspace()` stays a true invariant because creation is
  atomic. The conformance suite injects a failure at each seam and reads a
  fresh store back on all three backends.
- **Workspace mutations confirm, ask before they destroy, and cost one
  request (#1407, #1429, #1428, #1430, #1434).** Creating, archiving,
  deleting a workspace, inviting or removing a member and saving tool
  bindings each raise a success toast. Archive takes the same two steps as
  Delete instead of one unconfirmed click. Archived workspaces are listed
  behind an "Archived (n)" disclosure at the end of the tab strip with a
  Restore for each, since the backend has always accepted `PATCH {active:
  true}`. The Tools panel tracks unsaved edits (a badge on the toggle and in
  the panel, Save disabled when clean) and asks before a close would discard
  them. The workspace provider patches the changed record into local state
  after an archive or delete rather than refetching the whole list.
  `tests/e2e/workspace-lifecycle.spec.ts` walks each as the admin account
  and counts the requests.
- **Workspace status messages announce, and wizard fields are named by their
  visible labels (#1405, #1416).** The Conductor's toast container is now a
  polite live region and the error regions of the workspace tab bar, Share
  panel, Tools panel and persona wizard are alerts, so a refused invite or a
  failed save is announced to a screen reader instead of appearing silently
  (WCAG 4.1.3). The draft modal's loading text is a status message. The
  persona wizard's "Persona id" and "Workspace nav sections" fields dropped
  the shorter `aria-label` that overrode their visible labels, so a
  voice-control user can target them by the words on screen (WCAG 2.5.3).
  `tests/e2e/workspace-a11y.spec.ts` asks the accessibility tree for each.
- **Workspace-scoped pages wait for the workspace to resolve (#1427).** On a
  first-ever session the Conductor's Jira drafts, Agents and Missions pages
  fired their workspace-scoped requests before `GET /v1/workspaces` had
  returned, so `/v1/work-items?workspace_id=` went out with an empty id, was
  refused, flashed an error, and was sent again a moment later. The pages now
  wait for the workspace provider's `ready` flag and a resolved id; with no
  workspace at all the drafts page says so instead of erroring, the draft
  modal refuses to suggest, and the guidance thread asks for a workspace
  first. `tests/e2e/workspace-scope.spec.ts` records every request the three
  pages make and fails on one that names a workspace and leaves it blank.
- **Merge-queue builds retain both required PostgreSQL checks (no linked issue:
  observed queue timeout).** The PostgreSQL 17/18 matrix now runs after the
  workflow scope check regardless of path scope. GitHub evaluates a job-level
  condition before expanding its matrix, so skipping it produced one literal
  matrix-name check instead of `postgres (pg17)` and `postgres (pg18)`; the queue
  waited for those missing contexts even though reported checks were green.
  Both real database suites, required check names, and merge rules are unchanged.
  Queue builds for unrelated paths now also run the two PostgreSQL jobs.

- **`/v1/hitl/pending` pages by instant, not by printed offset (#1109).** The
  keyset cursor this scan walks was normalized to UTC in every store, so
  `list_by_status` compares a normalized key -- but the route still built its
  cursor with a bare `.isoformat()`. The two agree only while every
  `created_at` prints the same offset, which is the assumption the
  normalization exists to remove: a row printed at another offset orders one
  way and filters the other, and the walk stops advancing, hiding the human
  pause it was paging toward. The route now spells its cursor with the same
  `cursor_time` helper the stores use.

- **Bounded recovery scans page by instant, bound their own inspection, and no
  longer strand a half-claimed Run (#1098, #1056, #1109, #1127).** Three
  defects found reviewing the fair-scan work, each of which defeated the
  starvation fix it was part of. Keyset cursors ordered rows as timestamps but
  paged past them by comparing the printed ISO strings, which agree only while
  every row prints the same offset -- `01:00+01:00` is the earlier instant than
  `00:30+00:00` yet its string sorts after, so a cursor taken at the first row
  excluded the second from every later page, permanently; cursor keys and the
  index columns written beside them are now normalized to UTC (PostgreSQL was
  already correct, so the three store backends had silently disagreed).
  `CanonicalDurableRunStore.scan_due_page` kept an inspection ceiling
  independent of the walker's, letting one nominally 2,000-row tick inspect
  nearly twice that; the walker's remaining budget is now passed through.
  And `recover_queued_graph_runs` reported *every* unexpected failure as
  candidate-local, including one raised after the candidate was already
  checkpointed and moved to RUNNING -- which stranded that Run permanently,
  since the QUEUED scan no longer returns it and the due index never held it;
  a partial claim now raises instead of being swallowed, while a candidate
  left untouched is still isolated so the tick carries on.

- **The Chat and Deck Builder pages render again over plain HTTP (#1476;
  regression from #1344).** #1344 moved message, session and slide ids off `Math.random`
  onto `crypto.randomUUID()`, which browsers expose only in a secure context
  (`https://`, or `http://localhost`). Agent Conductor's documented homelab
  deployment is reached over plain HTTP at a LAN hostname, and the browser
  e2e harness serves it the same way, so the first render of either page
  threw "crypto.randomUUID is not a function" into the error boundary; the
  e2e walkthrough caught it only when the throw landed before its first
  poll, which is why `hive-conductor-e2e-ui` flickered red. Ids now come from
  `crypto.getRandomValues`, the same CSPRNG and available in every context,
  through a shared `lib/ids.ts`, and the "navigate all key pages without
  errors" e2e test now fails on the error boundary's fallback rather than
  accepting any non-empty body.

- **A chat turn whose canonical record fails *after* the model answered is no
  longer asked again (#1108).** `Container._execute_chat_turn` fell
  back to a fresh `dispatch()` on any `RunIntegrityError` without knowing
  which side of the model call it came from, so a store failure while
  persisting the completed Attempt or reconciling its NodeRun re-ran the
  turn — a second model charge, a second set of agent side effects, a second
  assistant message — while the first answer's evidence sat on disk.
  `ChatAttemptExecutor` now raises `ChatDispatchUnrecorded`, carrying the
  answer it already obtained, for any integrity failure past the dispatch
  boundary; the container hands that answer back and leaves the durable
  Attempt/NodeRun to the existing lease-reclaim and reconciliation paths. A
  dispatch that itself failed and then could not be recorded arrives as its
  own exception rather than the recording error. The pre-dispatch fallback —
  answering a turn whose spine could not be written before the model was
  called — is unchanged; #1108's other half (refusing a turn outright when no
  canonical spine is wired) is not addressed here.
- **A launch the store refuses no longer masks itself as a lifecycle error
  (#1108 follow-up to #1288).** When the Attempt's own RUNNING write failed,
  the executor's failure path asked the lifecycle for `FAILED` from `CREATED`
  — a transition it has never allowed — so the caller saw
  `InvalidLifecycleTransition` instead of the refusal, and the chat
  pre-dispatch fallback never received the `RunIntegrityError` it answers on.
  An Attempt still `CREATED` now settles as `CANCELLED` carrying the refusal
  as its error (nothing ran, so nothing failed), the refusal propagates, and
  the NodeRun parks for a retry decision exactly as a `FAILED` Attempt would.
- **A task's worker executes under the request id that admitted it
  (#1063).** `TaskRunAdmitter` recorded `X-Request-ID` on the Run's
  provenance, but the worker that later picks the task up runs from the
  dispatcher's own context, after the admitting request has ended, and
  restored nothing — so the execution's ambient context and log lines carried
  no request id at all. `TaskAttemptExecutor` now binds the Run's persisted
  request id, Workspace and Project around the Attempt it runs, so one id
  follows a task from the HTTP boundary through the Run into its execution.
- **The migration chain has one head again, and the debt ledger matches the
  shipped tree (no linked issue: base-branch repair).** Merging #1263 carried
  a renumber made against an older base: it renamed
  `033_project_membership_unique_per_principal.py` to `034_…` and moved its
  `revision` with it, colliding with the `034_hitl_deadline_index` already on
  develop. Git merged it without a conflict — different files — so the chain
  silently grew two `034`s, lost `033`, and forked `035`, and `alembic
  upgrade` could not resolve a path. Project membership is restored to `033`
  (down `032`) and `035_outcome_scope_thumb_index` follows `035` again, so the
  chain is linear: `032 → 033 → 034 → 035 → 035_outcome_scope_thumb_index`.
  No migration body changed; nothing already applied is rewritten. The same
  repair banks the three `capabilities/invocation.py` identities #1310
  introduced without authorizing (`observed_at`, `_validate_reconciliation`,
  `_validate_evidence`), un-breaking the `exact-debt-ledger` gate for every
  candidate.

- **A manual schedule fire claims its run before creating it, and never moves
  the recurrence cursor (#1119).** `ScheduleStore` gains `reserve_fire` /
  `settle_fire`: the quota is counted (and the schedule disabled on
  exhaustion) atomically under the store's lock *before* the Run exists, so
  two "run now" requests racing on the last run yield one Run and one refusal
  instead of `runs_so_far` overshooting `max_runs`, and a failure after the
  Run exists leaves the slot counted rather than a Run the next request
  duplicates. `last_fired_at` and `next_due_at` are no longer stamped with the
  manual fire's instant, so an occurrence the cron already owed is still
  admitted by the next tick; `last_run_id` still points at the manual Run.
- **A schedule's due cursor is recorded on every evaluation, and SQLite
  `record_fire` is serialized (#1199).** `ScheduleRunAdmitter` computed
  `next_due_at` on an evaluation that fired nothing but never persisted it, so
  a schedule whose first occurrence was days away stayed `next_due_at=None`
  and was selected by `ScheduleStore.due()` on every tick until then.
  `record_fire` now takes `fired_at=None` to record the due cursor alone —
  the enumeration cursor (`last_fired_at`), `last_run_id` and `runs_so_far`
  are untouched — and the admitter writes it whenever it changes and nothing
  is owed; a `BUFFER_ONE` occurrence held behind an active Run keeps the
  schedule due rather than hiding it until the occurrence after it.
  `SqliteScheduleStore.record_fire` was a get-then-put with nothing between
  the read and the write, so a tick and a manual fire advancing one schedule
  could both read `runs_so_far = n` and both write `n + 1`, losing each
  other's `last_run_id` and `next_due_at` with it; every SQLite writer now
  goes through one `BEGIN IMMEDIATE` critical section, matching the
  PostgreSQL store's `FOR UPDATE`. That section is the connection's, so the
  container now opens the schedule store its own SQLite connection
  (`Container.schedule_conn`, on the session store's terms) rather than
  sharing the spine's, where its BEGIN collided with a sibling store's open
  transaction and its rollback discarded that sibling's work; a cancelled
  writer waits the queued COMMIT out before deciding whether a rollback is
  real. `ScheduleStore.put` keeps an existing row's recorded cursors
  (`last_fired_at`, `last_run_id`, `runs_so_far`, `next_due_at`) instead of
  writing back the copy the caller read, so the Hive tick's per-tick
  definition refresh can no longer undo a fire that landed between its read
  and its write; a changed recurrence clears `next_due_at` for re-evaluation.
  `record_fire`'s `fires` now follows `fired_at` when omitted (none for a
  due-cursor-only write), so a bounded schedule cannot be spent by one. The
  live Hive tick still enumerates its own schedule rows; moving it onto
  `ScheduleStore.due()` is #1199's remaining scope.
- **HITL settlement repair is fair, idempotent, and keeps the recorded time
  (#737).** Startup reconciliation now finds crash residue (a canonical Run
  still PAUSED under a CANCELLED/TIMED_OUT continuation) from the canonical
  PAUSED side before the per-status scan, so an accumulating COMPLETED prefix
  can no longer starve it; a second tick that loses the race to the same
  repair stops instead of raising; the repaired Run and NodeRun are stamped
  with the durable `decided_at`, not the reconciliation time. The expiry tick
  repairs a continuation whose pause was never mirrored to its Run and widens
  its candidate page past projections it cannot repair. Migration 033
  validates each legacy `resume_at` (ISO-8601 with an explicit offset) before
  casting, leaving malformed or timezone-less values unindexed rather than
  aborting the upgrade or reading them in the session zone.

- **Ambiguous capability Invocations are recoverable, and the recovery is
  safe to operate (#1118).** Reconciliation checks the caller's Workspace and
  Project before returning a terminal Invocation, consults a provider adapter
  outside the service-wide effect lock and refuses its evidence if the row
  moved meanwhile, accepts and backfills scope on Invocations written before
  scope was persisted, announces the reconciled terminal state on the event
  stream, carries recovered usage into an APPLIED settlement, and reads naive
  timestamps as UTC instead of raising during discovery.
- **A scheduled Run whose resumed Attempt died is resumed again by the
  ordinary tick (#1112).** `recover_abandoned_attempts` reclaims a crashed
  resume's Attempt as CANCELLED and parks the Run WAITING, but
  `resumable_pause` read only the newest Attempt, so every later
  `resume_parked_runs` tick skipped the Run and the schedule stayed parked
  forever. The pause is now read past Attempts the recovery sweep reclaimed
  (recognised by the sweep's own error text via `is_reclaimed_attempt`);
  FAILED, TIMED_OUT, and requested-CANCELLED rows still park the Run for
  whoever owns retries.
- **`agent.synth_dag` can no longer report success for a sub-graph nothing
  ran, and node dependencies are declared on the class (#1193).** The
  production node resolver fell through to generic registry construction for
  `agent.synth_dag`, handing it `run_store=None`, and the node then completed
  with `success=True` and "execution skipped" — the third node found built
  without an authority it required (after `llm.summarize`, #1079, and
  `agent.delegate_remote`, #147). A node now declares the Container-owned
  authorities it needs (`BaseNode.required_authorities`) or uses
  (`optional_authorities`); `register_node` refuses a declaration the
  resolver could not honour, and `compose_node` refuses to construct a kind
  whose required authority is missing (`NodeCompositionError`) instead of
  filling it in from the constructor's permissive default. `build_node_resolver`
  builds every kind from those declarations rather than a hand-maintained
  branch list, takes the durable `graph_run_store`, and hands itself on so a
  synthesized child graph is built with the same wiring; the Container
  exposes the one production resolver as `Container.node_resolver()`, and
  Hive's registered-DAG path passes the graph store through. On the
  Container's canonical graph store the node now admits its child Run on the
  spine (parent Run and NodeRun, launch metadata) before the first checkpoint,
  the way `agent.delegate_remote` files its child. A node constructed
  directly without a store fails its NodeResult with `NodeCompositionError`
  naming the missing authority rather than completing.

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

- **A chat turn that crashes after admission but before its first physical
  Attempt no longer strands its Run RUNNING forever (#338).** Chat admission
  persists RUNNING durably before dispatch creates the turn's NodeRun; a
  process crash in that gap left a canonical Run claiming work was in flight
  that no sweep could see — `recover_abandoned_attempts` reclaims Attempts by
  expired lease, and there was no Attempt here to carry one. A new operator
  tick, `Container.recover_stranded_chat_admissions()`, compensates a RUNNING
  chat Run with no NodeRun after a bounded grace period, recording
  `execution_never_started` — a new, distinct category from the existing
  `admission_incomplete` (which covers the earlier CREATED/QUEUED gap).
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

- **Bounded recovery and HITL scans can no longer be starved by an ineligible
  prefix ahead of the eligible work behind it (#1098, #1056, #1109, #1127).**
  `recover_queued_graph_runs`, `resume_due_graph_runs`, `expire_hitl_pauses`,
  and `GET /v1/hitl/pending` previously queried a fixed-size page and filtered
  eligibility afterward: if more rows than the tick's `limit`/the caller's
  page ahead of the eligible ones belonged to another consumer, had no
  deadline yet, or were machine-only pauses, every tick re-read the same
  prefix and the eligible work behind it was never reached, even though it
  was durably correct and its deadline had passed. All four now page the
  underlying store with an advancing keyset cursor and filter as they walk,
  bounded by a fixed inspection ceiling per call so one pathological prefix
  cannot turn a single tick into an unbounded scan — and the three recovery
  ticks (`recover_queued_graph_runs`, `resume_due_graph_runs`,
  `expire_hitl_pauses`) take a `ScanContinuation` the caller holds across
  ticks, so each tick resumes after the last row the previous one inspected
  and restarts from the top only once it has walked off the end: a prefix
  longer than the per-tick ceiling is crossed within a bounded number of
  ticks instead of never. Hive's recovery runner and HITL expiry route hold
  one per (seam, store). `DurableRunStore` and `GraphContinuationStore`
  (memory, SQLite, PostgreSQL) gained an `after` keyset-cursor parameter on
  their status/due listings to support this. A store that filters its own
  page reports progress and results separately, so a page that yields nothing
  is no longer mistaken for the end of the index: `CanonicalDurableRunStore`
  drops due-index rows whose canonical Run has since gone terminal, and a
  settled prefix longer than one page previously reset the scan to the top on
  every tick and hid the live Run behind it.

- **A candidate-local failure during Graph recovery no longer aborts the
  whole tick (#1143).** `recover_queued_graph_runs` and
  `resume_due_graph_runs` previously let any exception other than
  `LiveAttemptOwned` (and a narrow already-settled `KeyError`/`ValueError`
  recheck) escape the per-candidate loop, so one Run whose resume path
  raised — a resolver bug, a downstream API error — silently abandoned every
  other due/queued candidate in the same batch. An unexpected failure tied to
  one candidate is now logged and isolated: the candidate's durable state is
  left untouched for a later retry, and later independent candidates in the
  same tick are still attempted. A failure raised while listing candidates
  (the store/session itself) still aborts the tick, since that failure
  invalidates the whole scan rather than one Run.

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

- **The legacy-event replay bridge has a durable, crash-safe resume position
  instead of restarting from cursor zero every time (#1163).**
  `Container.durable_event_cursor` was a plain process-local `int`, so a
  restart always replayed the entire retained `durable_event_log` regardless
  of how much of it had already settled; correctness survived only on
  `InvocationStore`'s per-`(trigger_id, event_id)` idempotency. A new
  `ConsumerCursorStore` (in-memory, SQLite, and PostgreSQL implementations)
  gives `process_durable_events` a durable position keyed to a fixed
  consumer identity plus a claim lease with a fencing token, so of several
  replicas that might tick the bridge at once, only the lease holder
  re-scans/redispatches a given round, and a stale or reordered write cannot
  regress the recorded position. The durable position advances only after
  the tick's events are confirmed settled, so a crash between "processed"
  and "cursor written" costs at most a replay of already-idempotent work and
  never skips an event still in flight. Nor is it persisted past an id the
  log handed out but has not committed: PostgreSQL allocates `BIGSERIAL`
  ids before commit, so `process_events_batch` reports every id it skipped
  over and the container holds its durable position below the first such
  hole until the id appears or a grace window
  (`Container.durable_event_hole_grace_s`, 60 s) lapses, after which the
  hole is treated as an aborted append. Handler work is never delayed by a
  hole, only the persisted resume point. The `consumer_cursors` table ships
  as Alembic revision `036_consumer_cursors` for deployments whose
  application role cannot create tables, and ADR-086 carries a dated
  amendment recording the cursor's ownership, lease, fencing and gap
  semantics.

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

**The stable HTTP surface in 1.0.0 is the `/v1` route mount.** Clients should
address `/v1/...` paths directly.

[ADR-076](docs/adr/ADR-076-http-api-versioning.md) specifies version selection
by **content negotiation** (`Accept: application/vnd.maistro.vN+json`). **That
scheme is not implemented.** No server in this release performs it; the only
negotiation code anywhere in the tree is a narrow, canvas-specific
`/v2/canvas` media-type check unrelated to the general scheme. Do not write
clients against it. Implementation is deferred to v1.1.

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
> degraded mode when optional services are unavailable, and API-wide HTTP
> content negotiation from ADR-076 is deferred to v1.1.

[Unreleased]: https://github.com/Agent-StrongHold/Project-mAIstro/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Agent-StrongHold/Project-mAIstro/releases/tag/v1.0.0

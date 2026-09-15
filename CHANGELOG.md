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

### Changed

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

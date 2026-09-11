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

- **Bootstrap credential staging is now private, atomic, and never follows a
  link (#809).** `write_bootstrap_credentials` writes secrets to a fresh 0600
  temp file in the same directory and promotes it with `os.replace`, so secret
  bytes never land in a pre-existing permissive inode, a planted symlink at
  the final path is refused rather than followed, and an interruption can no
  longer leave truncated JSON at the staged path. A pre-existing file is
  reused only after parse-validation — existence alone is no longer treated
  as staged input by the CLI's "already staged" skip either.
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

---
inventory-delta:
  packages/maistro-core/tests: +3
  tests/: +2
---
# issue-1194-replay-contract-repair

Repair round for the verifier findings against `9379e2490` (issue #1194,
Make Graph-node retry/idempotency semantics enforceable): the branch widened
`InvocationStore.list_effect` to `node_run_id: str | None` (the logical-effect
identity) and updated SQLite/in-memory, but the Postgres twin still filtered
`node_run_id = $2` — binding NULL, matching no rows, so completed-Invocation
dedup and the `UnsafeEffectRetry` guard never fired on the production DB.

## What the repair adds

- `PgInvocationStore.list_effect` accepts `node_run_id: str | None`; `None`
  issues a node-filter-free query (mirrors `SqliteInvocationStore`), so the
  logical-effect history is found on Postgres too.
- `_SCHEMA` (and Alembic revision 042, new) drop `node_run_id` from
  `idx_capability_invocation_effect`, ending the index-shape drift between the
  two durable backends; admission uniqueness
  (`uq_capability_invocation_active_effect`) keeps `node_run_id` in both.
- `_wire_capability_invocations` binds concrete stores before calling
  `ensure_schema` (a wiring concern the `InvocationStore` protocol does not
  carry), clearing both documented mypy errors at container.py:2459-2460.
- The dead, contract-contradicting `idempotent: ClassVar[bool]` on the
  unregistered builders `_StageNode` is removed; replay policy lives only in
  the `ReplaySemantics` contract.

## Net suite delta (+3 core, +2 root)

Core (`packages/maistro-core/tests/capabilities/test_pg_invocation_store.py`):
the fake asyncpg pool now emulates both `list_effect` SQL shapes faithfully
(a present `node_run_id=$2` filter binds its argument exactly — NULL matches
nothing; an absent filter spans NodeRuns) with the real ordering. Three cases:
the logical lookup spans NodeRuns and stays run/binding/effect-scoped;
`InvocationExecutionService.invoke(logical_effect=True)` replays one completed
Invocation across a new NodeRun/Attempt without a second dispatch or INSERT;
a live RUNNING Invocation from another NodeRun raises `UnsafeEffectRetry`.
The old store returns `[]` for the logical lookup under this fake — these
pins fail against `9379e2490` and pass here.

Root (`tests/migrations/`): new `test_capability_invocation_effect_index_migration.py`
pins 042's chain wiring (single head) and the exact index drop/create shapes
for upgrade and downgrade. `test_audit_scope_migration.py` and the
capability-table migration scan pin are updated to enumerate 042 (same
strictness — any further migration touching `capability_invocations` still
fails); their node counts are unchanged.

## CI-gate repair round against `1e02cf2` (no suite delta)

The verifier run at `1e02cf2` failed five CI jobs. Repairs, all evidence
driven, none cosmetic:

- SAST: `SqliteInvocationStore.list_effect` composed its SQL with an f-string
  fragment (bandit B608 at invocation_store.py:184). The method now issues two
  fully literal statements — one per `node_run_id` arity — mirroring the
  PostgreSQL twin; behaviour and parameters are unchanged.
- Quality gate: the `claim_run_by_effect` implementations (memory/SQLite/PG)
  and `InvocationExecutionService.invoke` had crossed the radon C threshold
  against the trusted baseline. The optional parent-chain validation moved into
  a `_require_locked_parent_scope` helper per store and the admission-race
  re-read moved into `_completed_replay_after_admission_race`; pure code motion,
  all suites (including the PostgreSQL legs) pass, and the ratchet reports
  70 → 70 reviewed blocks with no new findings or regressions.
- exact-debt-ledger / shipped-surface: the new A2A admission route
  (`POST /tasks/create:create_a2a_task`) is now classified in
  `quality/shipped-surface-truth.json` as canonical (it admits one idempotent
  remote delegation through `RunStore.claim_run_by_effect`).
- exact-debt-ledger / vulture: the two new FastAPI handlers are banked in the
  `fastapi-route-handler` findings ledger (candidate bookkeeping); the grant
  that authorizes them against the trusted base must land on the integration
  base in a separate change by design (`ratchet_provenance.load_authorizations`
  reads grants from the base revision, so a branch cannot authorize its own
  debt). Two store methods this branch added with no caller anywhere —
  `update_run_provenance` (×3 stores, dead) and `find_child_run_by_effect`
  (×3 stores, one test caller) — are deleted per the ledger's own policy that
  new unreachable-code findings must be fixed, never allowlisted; the delegate
  replay test now asserts the child Run through `find_run_by_effect` and adds
  the parent-scope binding assertions, so the replay proof is unchanged in
  strength.

## Re-validation round at `b548bfa75` (post-merge head; no suite delta)

Every previously failing gate was re-run locally at the merged head, with CI's
own invocation shapes:

- Coverage gate: full producer battery (core, canvas, evolve, rsi, bootstrap,
  server, turing src+backend, design, hive-conductor backend, root `tests/`)
  under `coverage run --branch`, then `scripts/check-diff-coverage.py
  coverage.xml --base 03c8ba83a711` -> ok, per-file floors 90% lines / 80%
  branches hold.
- SAST: bandit Medium+ = 0 on `packages/maistro-core/src`,
  `packages/hive-conductor/backend`, `packages/maistro-server/src`; semgrep
  0 findings for the custom ruleset AND for `p/security-audit` +
  `p/owasp-top-ten` + `p/secrets` (361 rules); gitleaks clean over
  `03c8ba83a711..HEAD`.
- Quality gate scripts: radon ratchet, reachability, credential-authority,
  wiring-reads, agent-store-writes, contract-markers, convergence-matrix,
  reachability-dispositions, security-inventory, image-inventory,
  backlog-consistency, enumerations, doc-links, version/release consistency —
  all pass. `mypy --strict packages/maistro-core/src` clean (629 files) once
  the `bootstrap` extra is installed as CI does.
- acceptance-state ratchet + mandate against a real pg18 (pgvector compose
  image): `alembic upgrade head` walks the branch's 041/042 revisions (and the
  re-parented 036) cleanly; `check-ac-state.py --run-tests --ratchet --mandate
  03c8ba83a711` reports every declared criterion proven and no new unlinked
  chain documents.
- pyright: 22 errors at head vs 26 at the merge base under the same pyright
  (1.1.414) — the branch strictly reduces findings; the checked-in baseline of
  21 is stale against current pyright for every branch, including the base.
  Left untouched: adjusting it is a gate-policy change for maintainers.
- exact-debt-ledger: still failing for the documented structural reason above —
  the candidate ledger banks both identities (re-running `--update` produces a
  byte-identical file), and the authorization grant must pre-exist on the
  integration base, which no branch edit can provide.

The last residual of the dead descriptive flag itself: three BaseNode
subclasses outside maistro-core still carried `idempotent: ClassVar[bool] =
False` while inheriting `ReplaySemantics.PURE` — a contract-contradicting
second source of truth nothing read. Removed from
`hive_conductor/backend/services/legacy_dag_node.py` (`LegacyConductorNode`),
`maistro_turing/backend/execution.py` (`_ChatNode`) and
`maistro_design/nodes.py` (the orchestrate node); the executable contract is
now the only replay declaration on every node class in the repo. The full
vulture scan reports no `idempotent` identities, so no ledger row is affected.
All three packages' suites pass unchanged (hive-conductor backend 2715,
design 264, turing 255).

Local-only note: a stale gitignored `quality/ac-state.json` left in a worktree
by an earlier test run makes `tests/test_branch_independence_repository.py`
fail locally (`discover_quality_json` rglobs untracked JSON). It passes on a
fresh checkout; CI never co-locates the generator and that check.

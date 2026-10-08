# Generalized protocol conformance suites: experiment record (#892, M8-A12)

Parent epic: #880 (advanced verification techniques). Deliverable per the
issue: a prototype implementation-agnostic conformance suite over protocols
with multiple production implementations, recorded evidence, and a
GRADUATE / INCUBATE / REJECT / WATCH disposition. This record routes
findings; it does not change production semantics or retire existing tests.

## Prototype

`packages/maistro-core/tests/conformance/` — the archive tier's shared-suite
pattern (`tests/archive/test_archive_conformance.py`, one suite over
filesystem + S3), generalized to a contract/leg split:

- `_invocation_contract.py` — 12 behavior checks for the capability
  `InvocationStore` / `EffectClaimStore` protocols
  (`maistro.capabilities.invocation`), written against the protocol, never
  against a backend: round-trip fidelity and copy detachment, absence
  semantics, optimistic concurrency (`StaleInvocationUpdate`), admission
  refusal beside live and completed priors (`UnsafeEffectRetry`),
  FAILED-prior-only retry eligibility, duplicate-id refusal, `list_effect`
  scope/span/order, `list_ambiguous` staleness predicate, and the atomic
  claim's replay/refuse/admit-after-failure semantics.
- `_approval_contract.py` — 7 behavior checks for the durable `ApprovalStore`
  protocol (`maistro.capabilities.approval_store`): pending round-trip with
  digest binding, explicit absence, idempotent create by effect identity,
  duplicate request_id refusal, verified-actor requirement (#329 /
  ADR-090726-9a4e), first-decision-wins idempotence, and
  decision-survives-restart.
- `_legs.py` — the backend knowledge: build / restart / close for the three
  production implementations of each protocol (in-memory, SQLite via real
  aiosqlite, PostgreSQL via real asyncpg). The PostgreSQL leg runs against a
  server named by `MAISTRO_TEST_DATABASE_URL` and skips without one — the
  same honest-skip discipline as `tests/events/test_durable_store_conformance.py`
  ("a skipped leg is untested, not passing"). Rows are isolated by namespace,
  so the suite never truncates or assumes exclusive ownership of a database.
- `test_invocation_store_conformance.py` /
  `test_approval_store_conformance.py` — the matrix: one node per check x
  backend (65 run + 7 claim-skips on PostgreSQL here; 72 collected), plus
  per-leg structure guards.
- `test_conformance_teeth.py` — the strictness evidence, executable: seven
  deliberately drifted stores (admission never refuses, lost updates,
  reordered history, amnesiac claim, anonymous decisions, last-vote-wins,
  decision lost across restart) each trip exactly the expected check, and an
  honest in-memory leg violates exactly the recorded findings and nothing
  else.

Every known cross-implementation divergence is an `xfail` in the matrix,
citing its finding number below. `strict=True` markers make a repair flip
the node to XPASS and fail the suite until the marker is retired: the suite
retires its own findings.

## Protocols chosen

Two protocols, each with three production implementations the container
wires (per `maistro.container` and `capabilities/__init__.py`):

| Protocol | Implementations | Prior evidence |
|---|---|---|
| capability `InvocationStore` + optional `EffectClaimStore` | `InMemoryInvocationStore`, `SqliteInvocationStore`, `PgInvocationStore` | per-implementation files only: `test_invocation_store.py` (SQLite/in-memory, 16 tests), `test_pg_invocation_store.py` (fake-asyncpg pool, 12 tests) |
| durable `ApprovalStore` | `InMemoryApprovalStore`, `SqliteApprovalStore`, `PgApprovalStore` | `test_durable_approval.py` (in-memory/sqlite integration), `test_pg_approval_store.py` (FakePool, 13 tests) |

Protocols already covered by an existing shared suite were deliberately not
duplicated: the events durable stores (`test_durable_store_conformance.py`),
archive stores (`test_archive_conformance.py`), working-log stores
(`test_working_log_store_conformance.py`), and the episodic/user-model
backend-parametrized suites. The gap this experiment fills is the capability
tier, where evidence was per-implementation.

## Measured evidence, per the issue's metric list

**Duplicate test reduction.** The 18 shared checks cover behavior families
that today need one hand-written body per backend: the claim semantics
alone are pinned five times for SQLite in `test_invocation_store.py`
(:608-:731) and re-proved ad hoc for the fake-pool PG twin, and the
#1194 logical-admission property is asserted separately against the
in-memory store (:336), the SQLite store (:392), and the service race
(:519). A fourth backend leg now costs a ~60-line `_legs.py` builder, not a
~500-line parallel test file (the two existing PG test files total ~930
lines against fake pools). Nothing was deleted: consolidation of the
existing per-implementation bodies is the owner's rollout decision under
GRADUATE, and this prototype deliberately leaves them in place.

**Drift defects found.** Six, all reproducible from the matrix, none fixed
here (routing below):

- **F1 — PostgreSQL terminal dedup missing at the ledger.**
  `PgInvocationStore.create` admits a fresh Invocation beside a `COMPLETED`
  prior (its partial unique indexes cover only active statuses); the
  reference and the SQLite twin both refuse with `UnsafeEffectRetry`.
  Confirmed against a real PostgreSQL 18 server, not a fake pool. Today this
  is masked by `InvocationExecutionService`'s history pre-read
  (`invoke()` re-lists the effect before admission), which is exactly the
  masking the issue's "abstraction leakage" metric warns about: the ledger
  guarantee the PG store's docstring advertises ("Effect admission uses a
  partial unique index") does not extend to terminal priors, and every
  future caller inherits the burden silently. Owner: capability/invocation
  maintenance.
- **F3 — the in-memory claim never refuses.** `InMemoryInvocationStore.claim`
  returns a live prior (and a just-claimed duplicate id) where the durable
  contract — pinned by the SQLite twin's own tests
  (`test_claim_refuses_a_non_terminal_prior_as_an_unsafe_retry`) — refuses
  with `UnsafeEffectRetry`. Service-masked today by
  `_settled_by_another_admission` re-checking whatever claim returns. Marked
  non-strict xfail: single-process leniency may be deliberate. Owner:
  capability/invocation maintenance.
- **F4 — SQLite claim misses Run-scoped completed priors (#1194).**
  `SqliteInvocationStore.claim` scopes its history read to the candidate's
  `node_run_id`, so a `logical_effect` Invocation whose completed canonical
  row sits under an earlier NodeRun is re-admitted (`claim` returned the
  fresh candidate) instead of replayed — the exact retry-across-NodeRuns
  shape the logical-effect discriminator exists to serialize. Service-masked
  by the history pre-read; reachable in the race window admission exists
  for. Marked strict xfail. Owner: capability/invocation maintenance.
- **F6 — the in-memory history does not honor the tiebreak.**
  `InMemoryInvocationStore.list_effect` sorts by `created_at` alone
  (stable → insertion order) where both durable twins document and
  implement `ORDER BY created_at, invocation_id`. Consumers read
  `history[-1]` as *the latest* Invocation, so under a timestamp tie the
  reference and the system of record select different rows — potentially a
  different replay decision. Marked strict xfail. Owner:
  capability/invocation maintenance.
- **F2 — duplicate-invocation_id error mapping diverges.** Reference raises
  `ValueError`; both durable twins raise `UnsafeEffectRetry`. The suite
  pins only the portable property ("refuses"); the canonical type is an
  owner decision recorded here. Owner: capability/invocation maintenance.
- **F5 — duplicate-request_id error mapping diverges.** Reference raises
  `ValueError`; SQLite leaks `sqlite3.IntegrityError` and PostgreSQL leaks
  `asyncpg.UniqueViolationError` to callers of
  `SqliteApprovalStore.create` / `PgApprovalStore.create`. This is the
  issue's "canonical error mapping" candidate assertion verbatim: the
  durable twins translate *effect-identity* collisions into domain errors
  but not *primary-key* collisions. Owner: durable-approval maintenance.

**Abstraction leakage.** The suite's contract/leg split keeps every check
implementation-free; the only backend knowledge is lifecycle code in
`_legs.py` and the xfail matrix. One leakage trap was deliberately *not*
taken: approval secret redaction looks like a store behavior but is applied
by callers (`maistro.capabilities.governed_invocation` calls
`redact_approval_value` before persistence), so a naive suite would pin the
wrong boundary. The suite asserts round-trip fidelity instead, and this
paragraph records why.

**Setup cost for real backends.** SQLite: none (file-backed aiosqlite in
tmp_path, ~10 lines per leg). PostgreSQL: a real server is required for the
property that matters — the fake asyncpg pools the existing per-impl tests
use cannot testify about partial unique indexes or `ON CONFLICT` behavior,
and F1 is invisible to them by construction. With `MAISTRO_TEST_DATABASE_URL`
set (here: a local PG 18 scratch database) the full 72-node matrix runs in
~2.4 s; without it, the PG leg skips loudly. Namespace isolation means the
suite can point at a shared database without truncating it.

**Strictness.** Executable, via `test_conformance_teeth.py`: each of seven
single-behavior drifts flips exactly its expected check, and an honest leg
violates exactly the recorded findings. The teeth double as the regression
guard on the suite itself — a future check edit that goes quietly no-op
breaks the honest-leg expectation test.

## Disposition: INCUBATE

Reasons:

1. The hypothesis holds and paid immediately: six cross-implementation
   divergences — including two terminal-dedup/ledger gaps (F1, F4) on the
   exactly-once effect boundary and one "latest row" selection divergence
   (F6) — were invisible to the existing per-implementation suites and were
   found by one shared matrix in its first run.
2. The pattern is already half-adopted (archive, events, working-log,
   episodic suites all parametrize over backends); this prototype's
   contract/leg split adds what those suites lack: reusable check bodies,
   an executable strictness proof (teeth), and finding-numbered xfail
   discipline that self-retires on repair.
3. Cost is bounded: no production code, no services beyond an optional
   PG URL, ~2.4 s wall, +72 collected nodes on an existing suite.

Conditions to GRADUATE (filed for the testing/implementation owners; not
part of this research change):

- Route F1/F3/F4/F6 to the capability/invocation owner and F2/F5 to the
  durable-approval owner; retire the strict xfails as repairs land.
- Fold the per-implementation bodies the suite now subsumes into the shared
  matrix (deleting ~30 near-duplicate test bodies), keeping backend-specific
  tests only for what a contract genuinely cannot express (e.g. SQLite
  cross-connection locking, migration DDL).
- Add a real-backend CI leg (`MAISTRO_REQUIRE_PG_LEGS` + service container,
  as the `durable-events` job already does) so the PostgreSQL column stops
  skipping on PRs.
- Extend the same contract/leg split to the next protocol with 2+
  implementations (candidate: the events-subsystem handler `InvocationStore`
  already has three implementations and a suite that predates the split).

REJECT would require the suite to have found only artifacts of its own
harness; WATCH would fit if the findings were all service-masked and
uninteresting. Neither matches the evidence: F1 and F4 are ledger-level
guarantee gaps that every future caller of the durable stores inherits.

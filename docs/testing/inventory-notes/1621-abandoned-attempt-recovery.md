---
inventory-delta:
  packages/maistro-core/tests: +31
  packages/maistro-server/tests: +10
---

# 1621 abandoned-Attempt recovery activation

Activates the two dormant halves of the canonical recovery story on the
shipped server process and fences parent completion behind settled children
(#1621, refs #232/#42/#47/#147).

maistro-server (+10): a new process-lifetime cadence ticks
`Container.recover_abandoned_attempts` every 10s — the task worker's
`TaskAttemptExecutor` now constructs its lease with `DEFAULT_TASK_LEASE_TTL`,
so a lease is only written when this process also collects it. Four tests pin
the cadence in isolation (one tick calls the container sweep with the default
limit; a store failure is swallowed and returns 0 so the next tick retries; a
non-awaitable recover is ignored; start is idempotent and stop joins without
further ticks), and the lifespan suite proves `_runtime_lifespan` starts the
sweep with the app container and awaits its stop during shutdown. A CI
coverage-gate repair (#1621) adds five more on the shutdown and error paths
the first round left dark: a Container without the sweep ticks as a noop; a
cancelled sweep propagates instead of being swallowed; a tick stuck past the
join deadline is cancelled (the `_STOP_TIMEOUT_S` seam keeps the test off the
five-second literal); a stop whose caller is cancelled re-raises while the
shielded cadence survives and stays joinable; and a join aborted by the
cadence's own cancellation is tolerated rather than re-raised.

## Validation evidence at head 2fe392fe4 (merge of origin/develop f8a2df966)

Without a database the battery passes 421 / skips 153 (the PostgreSQL legs).
With `MAISTRO_TEST_PG_DSN` pointed at a pgvector:pg18 container at alembic head
(revision 068), the same six paths pass **573 / skip 1** — the lone skip is
`find_run_by_effect` on the in-memory backend, a durable-store-only read. The
Postgres leg therefore executed the spine-conformance completion refusal and
eventual-completion cases, the delegation child guard, and the chat-admission
and retention transitions against `PgRunStore.transition_run`, whose guard
reads child statuses after the parent row lock. The affected-package
inventory gates (`check-suite-inventory.py --suite` on maistro-core and
maistro-server) match the recorded counts, and the vulture per-identity gate
(`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`) passes with the `recover_abandoned_attempts` row removed
from the ledger: the server now consumes it.

## Independent verification round at head c9b76daed

Reproduced at the recorded head, not taken on trust. Default battery: the six
affected paths pass **421 / skip 153**; with `MAISTRO_TEST_PG_DSN` on a fresh
pgvector:pg18 container migrated to head (068), the same paths pass **573 /
skip 1**, and the CI coverage producer for `packages/maistro-core/tests/runs`
+ `tests/graph` runs **4161 passed / 5 skipped / 4 xfailed** against that
server. A direct probe through the public `InMemoryRunStore.transition_run`
confirms the production refusal (`RunIntegrityError: Run cannot complete while
1 child Run(s) are non-terminal`), the parent staying `running` afterwards, and
`FAILED` remaining legal over the open child. CI-exact gates re-run locally:
vulture with `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
(1237 findings vs 1238 reviewed identities — the removed row is banked),
`check-diff-coverage.py` with the server + core producers and the PG leg
appended (every measured changed file ≥ 90% lines / ≥ 80% branch arcs), both
mypy invocations (`packages/.../src` union and `--strict packages/maistro-core/src`
after `uv sync --locked --all-extras`), reachability, ratchet provenance,
shipped-surface truth, cross-package imports, durable-table inventory,
agent-store writes, doc links, and both affected-suite inventory gates.
`quality/vulture-baseline.json` carries the same 12 rule groups as
`origin/develop` with exactly the one intended deletion (no merge-lost rows).

## Driver verification round at head 606fb5d2

The round's deterministic battery reproduced the branch-level claims with
first-hand evidence. Driver checks: `uv sync --locked --extra dev`, ruff check
+ format --check (clean), the six affected pytest paths **421 passed / 153
skipped**, and both affected-suite inventory gates `ok` (core 18442 node IDs,
server 680). Independent re-validation: the same six paths re-run locally —
**421 / 153** without a database and **573 / 1** with `MAISTRO_TEST_PG_DSN` on
a fresh pgvector:pg18 container migrated to head (068), matching the recorded
Postgres-leg counts; the three guard cases
(`parent_cannot_complete`, `parent_completes_once`, the human-pause variant)
confirmed PASSED on the `[memory]`, `[sqlite]` and `[postgres]` params by name.
`test_lifespan_starts_and_stops_abandoned_attempt_recovery` and all nine
cadence tests pass. CI-exact gates re-run: `uv run mypy` with the ci.yml union
of seven `packages/*/src` paths (exit 0, 1017 files), `mypy --strict
packages/maistro-core/src` after `uv sync --locked --all-extras` (exit 0, 839
files — the transient import error seen under a dev-only sync is the uninstalled
`maistro_bootstrap` extra, not a code defect), and
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (exit 0, 1238 reviewed identities → 1237 findings,
unclassified 0). `git diff --numstat origin/develop -- quality/` shows exactly
`0  1` on `quality/vulture-baseline.json`, and commit messages on the branch
contain no closure keywords.

maistro-core (+8): `refuse_completion_while_children_open` makes a parent Run's
`COMPLETED` transition refuse while any child Run is non-terminal — failure,
cancellation and timeout stay legal. The spine conformance suite gains the
refusal and the eventual-completion case on every backend (2 tests × 3
backends = +6), and the delegation suite proves a delegate_remote child keeps
its delegating parent un-completable while the child is in flight (+1). The recovery
replay also revalidates that a reclaimed Attempt is still current immediately
before parking; a regression test inserts a leased retry after the replay's
selection snapshot and confirms the active NodeRun and Run remain `RUNNING` (+1).
Existing chat-admission, retention and forced-delete cases now settle their
child Runs first, so they exercise deletion/purge of parents whose children
reached a terminal state rather than relying on the previously unguarded
sequence.

## Current repair round at merge head 250cfe7097

Review against the actual merged tree found that parent completion protection had
been lost during the rebuild: unlike the earlier heads documented above,
`transition_run` no longer checked child Runs before accepting `COMPLETED`.
The canonical in-memory, SQLite, and PostgreSQL Run stores now reject that
success claim while a child Run is non-terminal; failure remains legal. The
shared spine test proves refusal without mutating the parent, continued failure
legality, and successful completion after the child settles. The existing
parent-retention test now settles its child before completing the parent, so it
continues to test deletion rather than the new completion fence. These are
re-established at the current head; older validation evidence above does not
apply to the rebuilt head.

Current test inventory delta: one new parametrized core conformance test adds
six node IDs across the memory, SQLite and PostgreSQL spine backends; total note
delta is `packages/maistro-core/tests: +31`, server tests unchanged.

## Bounded supply-chain repair at starting head 5edfca330

Job `cdc0349204254f1e83fe0b338525dbed` independently reproduced the CI
supply-chain failure rather than relying on prior verification notes. The
locked dev environment's `pip-audit --strict --format=json` producer and
`scripts/pip_audit_gate.py` rejected four fixable advisories:

- `dnspython` 2.9.0: CVE-2026-128089, fixed by 2.9.2.
- `graphql-core` 3.3.0: CVE-2026-119286, fixed by 3.3.1.
- `joserfc` 1.7.5: CVE-2026-119284, fixed by 1.7.6.
- `opentelemetry-api` 1.45.1: CVE-2026-126360, fixed by 1.45.2.

Targeted lock resolution updates only those four distributions and the
OpenTelemetry SDK / semantic-conventions versions required by their exact
version coupling (1.45.2 / 0.66b2). Unrelated uv-generated lock revision and
macOS marker normalization were excluded; locked sync still passes. Both CI
audit shapes were rerun: locked
`--extra dev` and locked `--all-extras`, followed by freeze, strict JSON audit,
and the shared gate. Both gates pass; only the existing reviewed ecdsa
PYSEC-2026-1325 remains. No advisory exemption or gate was changed.

Independent validation after the lock repair:

- Ruff check and format check pass (3563 files); `git diff --check` and
  `check-shipped-surface-truth.py` also pass.
- Full server package with CI's `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`:
  **670 passed / 10 skipped**. Core `tests/runs` + `tests/graph` without
  services: **3652 passed / 514 skipped / 4 xfailed**. These broader runs
  emitted aiosqlite worker-thread/event-loop-closed warnings (one in server,
  five in core) as well as existing HTTP-status deprecation warnings; they
  were not failures and were not suppressed or repaired in this round.
- The six affected pytest paths above: **421 passed / 153 skipped** without
  PostgreSQL; **573 passed / 1 skipped** on an isolated pgvector:pg18 database
  migrated through revision 068. The remaining skip is the memory backend's
  durable-only effect lookup.
- `test_container_wiring.py -k sweep`: **3 passed**, exercising actual
  Container reclaim and logical parking rather than only a mocked ticker.
- Exact CI vulture invocation: **1237 findings, 0 unclassified**, against
  1238 reviewed identities. The existing one-row removal is correct; no
  additional ledger amendment is justified.
- Affected suite inventories pass: core **18442**, server **680**. No
  repository tests were added, so this round does not change the delta above.

### Unresolved acceptance evidence: not merge-ready

The supplied review concerns were checked against reachable production
behavior, not dismissed because the selected tests pass. A standalone probe
using the real `create_container`, canonical store and server cadence proves:

1. `ClaimingInMemoryRunStore.create_run` accepts a new `CREATED` child after
   its parent is `COMPLETED`. The completion-time guard does reject existing
   children (proven on all three backends), but does not establish a lasting
   parent/child invariant. PostgreSQL's FK lock wait alone cannot prevent an
   insert after completion; its comment in `transition_run` overstates this.
2. If shutdown's cadence join deadline expires after real
   `reclaim_expired_attempts` has settled the Attempt but before logical
   reconciliation, the sweep is cancelled. Two later real Container ticks
   each return 0 and leave the **CANCELLED Attempt / RUNNING NodeRun / RUNNING
   Run** combination unchanged. The deterministic probe parks at an asyncio
   event after the actual reclaim, without fabricating persisted state, and
   shortens only the cadence join deadline. Terminal replay currently scans
   `COMPLETED` Attempts, not the reclaimed `CANCELLED` Attempt. This does not
   satisfy ADR-082526-b36a's recovered logical parking guarantee.

These lifecycle hazards are **not repaired by this lockfile-only CI fix**;
repair requires canonical serialization/recovery decisions, not a speculative
scanner edit or another execution authority. PostgreSQL worker kill/restart
acceptance for issue #232 remains outside this round's proof.

The supplied PR body also needs an owner-applied wording change
to remove negated issue-closure syntax. Safe replacement:

> Scope is limited to PR 1621; issues #42 and #232 remain open. Issue #1194
> remains a prerequisite for #42. PostgreSQL worker crash/restart acceptance
> for #232 is outside this PR's proof.

Full local command output and the deterministic probe are in
`/home/dev/maistro/jobs/cdc0349204254f1e83fe0b338525dbed/` (`audit-before.json`,
`audit-after.json`, `audit-all-extras.json`, `pytest-focused.log`,
`pytest-pg-focused.log`, `pytest-canonical-recovery.log`, `vulture.log`, and
`acceptance-probes.py` / `acceptance-probes.log`). The prior worker ended on
provider quota; its committed implementation was preserved. No GitHub state
was mutated.

## Lifecycle-hazard repair at head 72671203f

Both hazards the previous round recorded are repaired against their
reproductions, not around them. The same probe script from job
`cdc0349204254f1e83fe0b338525dbed` was re-run first to confirm each hazard
still reproduced at the starting head, and re-run after the repair to confirm
neither does.

Hazard 1 — a child filed under a terminal parent (#1621):
`refuse_child_under_terminal_parent` now refuses `create_run` children whose
parent has already reached a terminal status, called through
`validate_child_scope` on all three backends (the delegation pre-flight gets
the same refusal before it dispatches). PostgreSQL's `insert_prepared_run`
additionally re-derives the parent's status `FOR UPDATE` inside the insert's
own transaction: `prepare_run` checks on an unlocked read, and a completion
committing in that window would otherwise land the child under a terminal
parent. Whichever writer wins the parent row, the loser observes the winner —
the child's committed row appears in the completion scan, or the completion's
status appears in the child's locked read. The `transition_run` comment that
claimed the FK lock wait alone made the scan complete was rewritten to state
what actually serializes the two writers.

One acceptance was reconciled against an accepted ADR: the durable Graph fork
(ADR-062 / ADR-082826-d9f5) files a child under a *terminal* source by
contract — "a terminal source Run cannot be reopened... so a fork branches
identity instead" — so a blanket refusal broke shipped time travel
(`test_time_travel.py` caught it). The guard exempts exactly the fork fact:
`DURABLE_GRAPH_FORK_PROVENANCE` moved beside `PAUSE_AWAITS_HUMAN` in
`runs/model.py` (same dependency-runs-the-other-way justification), and the
exemption holds only when the fact's `parent_run_id` names the parent being
filed under. A fork of one run cannot unlock filing under another, and plain
provenance unlocks nothing.

Hazard 2 — an interrupted reclaim never healed: the terminal replay
(`_reconcile_unreconciled_terminal_attempts`) scanned only `COMPLETED`
Attempts, so a crash between the sweep's reclaim and its RECOVERED park left
CANCELLED Attempt / RUNNING NodeRun / RUNNING Run stranded forever — the
tick's own docstring promised healing that the code could not perform. The
replay now includes reclaimed Attempts, recognized by the sweep's own marker
(`is_reclaimed_attempt`), so a requested cancellation — the other meaning of
CANCELLED, whose disposition belongs to the path that took it — is never
replayed as a recovery. The RECOVERED park counts as observed persisted
progress under the #1850 budget rule, so a page of such healings reports and
charges what it did. A live retry lease still wins: `has_live_execution_lease`
keeps the replay off a NodeRun a newer attempt holds.

Tests added (core delta +13, total +20): the spine conformance suite gains the
terminal-parent refusal, the all-terminal-statuses variant, and the fork
exemption pin (3 × 3 backends = +9); the Container wiring suite gains the
interrupted-reclaim healing, the requested-cancellation leave-alone, and the
live-retry precedence (+3); `test_pg_root_preparation.py` gains the
insert-after-completion refusal on the real server (+1). The retention
`child_exists` fixture now files and settles its child while the parent is
open, per the same invariant.

Validation after the repair: ruff check and format --check clean; canonical
seven-package `mypy` clean (953 files); exact CI vulture invocation passes
(1237 findings, 0 unclassified, 1238 reviewed identities — no ledger edit
needed); full server package **670 passed / 10 skipped**; core
tests/runs + tests/graph + container wiring **3720 passed / 518 skipped / 4
xfailed** without PostgreSQL; the conformance + preparation + wiring paths
with `MAISTRO_TEST_PG_DSN` on a fresh pgvector:pg18 container migrated to head
(068) pass **616 / skip 1** — the PostgreSQL leg executed the new
insert-transaction refusal, the terminal-parent refusals on all three
backends, and the fork exemption on `[postgres]`. Both affected-suite
inventory gates match the recorded counts after `--update` recorded the
delta. Residual, unchanged: PostgreSQL worker kill/restart acceptance for
#232 remains outside this PR's proof.

## Independent re-validation round at head f862c2326

Reproduced first-hand at the branch head, not taken on trust from the
sections above. Without a database, the eight affected paths (delegation
child, chat admission, pg root preparation, retention, spine conformance,
container wiring, server lifespan, server cadence) pass **489 / skip 164**,
matching the driver's recorded run exactly. With `MAISTRO_TEST_PG_DSN` on a
fresh `pgvector:pg18` container migrated to alembic head (068), the same
eight paths pass **652 / skip 1** — the lone skip is the memory backend's
durable-only effect lookup. By name on the `[postgres]` param:
`test_a_child_cannot_be_filed_under_a_terminal_parent`,
`test_no_child_is_filed_under_any_terminal_parent_status`, and
`test_a_fork_is_the_one_child_a_terminal_parent_accepts` all PASSED, as did
`test_insert_refuses_a_parent_that_terminalized_after_preparation` (the
locked insert-transaction refusal on the real server) and the three wiring
recovery tests (interrupted-reclaim healing, requested-cancellation
leave-alone, live-retry precedence). CI-exact gates re-run at this head:
`uv run mypy` with the ci.yml ten-path union (exit 0, 1121 files),
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (exit 0, 1238 reviewed identities → 1237 findings), both
affected-suite inventory gates ok (core 18455, server 680), ruff check and
format --check clean. `git diff --numstat origin/develop -- quality/` shows
exactly `0 1` on `quality/vulture-baseline.json` — the single intended
removal, no merge-lost rows — and a scan of every branch commit message
finds no issue-closure keyword. Residual, unchanged from the rounds above:
the PR body's negated closure phrasing ("Does not close #42") needs an
owner-applied wording change, and PostgreSQL worker kill/restart acceptance
for #232 remains outside this PR's proof.

## CI-gate repair round at head 64b1cc24e

The merge-queue evaluation of this head red four checks; each was reproduced
locally at the exact head before touching anything, and each repair is
evidence-backed rather than cosmetic:

- **Quality / Radon** and **Quality / Xenon**: the Hazard-2 repair left
  `Container._reconcile_terminal_attempt_progress` at C (12) — the radon
  ratchet reported exactly `container.py:1557 -> C (12)` as the one
  unbaselined block, and xenon counted 127 block violations against its
  baseline of 126. Per the floor-raise rule a same-branch grant cannot
  authorize its own change, so the block was refactored away instead: the
  three progress predicates (accepted / settled / parked) moved verbatim into
  a module-level `_reconcile_progress_observed` helper (B (10)), leaving the
  method at A (3). CI-exact invocations after the refactor:
  `check-radon-baseline.py` exits 0 at 126 -> 126 with zero new, regressed or
  stale entries, and xenon counts exactly 126 block violations (the
  `--max-absolute B` / `--max-modules B` / `--max-average A` invocation from
  quality.yml). No ledger row was added.
- **Coverage gate**: reproduced with `check-diff-coverage.py` against the
  merge base — `pg_store.py` measured 14.3% of its 7 changed lines without a
  database (the PG legs skip) and 85.7% even with the postgres producer
  appended, because the locked re-derivation's missing-parent branch
  (`RunNotFound`, line 544) had no test. A from-scratch accumulation of the
  CI producers (full server suite; core runs/graph/wiring; the affected paths
  under `MAISTRO_TEST_PG_DSN` on a fresh pgvector:pg18 migrated to alembic
  head 068) reproduces that refusal cleanly. The repair is the missing
  degenerate-path test: `test_insert_refuses_a_child_whose_parent_row_is_gone`
  prepares a real child, presents it for insertion with the parent row gone,
  and asserts `RunNotFound` with nothing filed. With it the same gate reports
  `ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs`. The publish-set floor producers were green in CI at this
  head and are unchanged by this round.
- **Quality gate (Pillars 1–4, 7, 8)** is a pure aggregate of the quality-`
  jobs; radon and xenon were its only red leaves at this head, so the
  refactor above is its repair.

Round validation: affected paths without a database **489 passed / 165
skipped** (the new test is the +1 skip); preparation + spine + wiring with
`MAISTRO_TEST_PG_DSN` **490 passed**, full PG-leg subset 637 / 1; full server
package `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1` **670 passed / 10 skipped**;
core runs/graph/wiring **3720 passed / 519 skipped / 4 xfailed**; CI-exact
mypy union **953 files, no issues**; vulture CI-exact invocation exits 0
(1238 reviewed identities -> 1237 findings, no ledger edit); ruff check and
format --check clean (3563 files); both affected-suite inventory gates ok
(core 18456 after this round's +1, server 680) with the front-matter delta
updated to +21.

Not reproduced, recorded rather than guessed: the ci.yml `test` job red. Its
server-suite step failed once here (sigterm shutdown sandbox case) and passed
on immediate re-run, in isolation, and in two later full-suite runs — an
order-dependent flake, consistent with concurrent docker activity on this
host during the first run, not a deterministic defect of this branch. The
`Container scan + SBOM + cosign` red could not be reproduced locally (its
registry/scanning infrastructure is not in this environment); the same head's
`docker-build`, `hive-conductor-e2e` and compose-durability runs are green on
the identical image build. Both remain marked for the next CI evaluation to
confirm rather than being claimed fixed. Residual from prior rounds,
unchanged: PostgreSQL worker kill/restart acceptance for #232, and the PR
body's owner-applied wording change.

## Independent CI-repair verification at head bda89e212

Reproduced available evidence at the assigned head. The focused core/server
battery (delegation child, chat admission, pg root preparation, retention,
spine conformance, Container wiring, server lifespan, and recovery cadence)
passes **490 / skips 165**. Ruff check and format check pass (3563 files);
the affected-suite inventory gates match core **18457** and server **680**.
The exact vulture gate, `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, passes with
**1237 findings / 1238 reviewed identities**, so no further ledger change is
supported. The driver check logs independently show the same ruff, formatting,
test and inventory outcomes.

Current-run limits and outstanding items: `MAISTRO_TEST_PG_DSN` is unset, so
this run did not execute PostgreSQL legs; the earlier PostgreSQL evidence above
was gathered at earlier heads. PostgreSQL worker kill/restart acceptance for
#232 remains outside verified acceptance. The captured PR body still contains
negated closure wording (`Does not close #42 or #232`) and says closed issue
#1194 is open; this requires an owner-applied PR-body correction, which this
worker cannot perform under the no-GitHub-mutation rule. The known
read-then-write `_require_current_attempt` guard around recovered parking
remains a possible concurrency window; it is recorded as residual rather than
claimed atomic. No tests were added or removed in this verification round, so
the suite inventory delta is unchanged.

## Atomic reclaimed-Attempt park guard

At the next repair head, the confirmed stale-read window was closed at the
store write boundary. Reconciliation now supplies the reclaimed Attempt ID as
an expected-current token on the NodeRun park transition. In-memory and SQLite
stores check that token while holding their write serialization; PostgreSQL
checks it inside the transaction after locking the NodeRun row, the same lock
that serializes `create_attempt`. Durable Graph execution storage performs the
same check within its canonical record mutation and forwards the token to its
backing RunStore when present. A newer retry therefore prevents the stale
park from committing. Completed Attempt reconciliation and explicit outcome
acceptance also carry their Attempt ID into the guarded NodeRun transition, so
a superseded physical completion cannot be accepted after its preliminary
currentness read. The existing deterministic race test was strengthened: it
inserts and starts a live retry after recovered reconciliation's pre-check but
immediately before the guarded transition; the retry remains RUNNING and the
parent Run remains RUNNING. This changes no test inventory count (the test is
strengthened, not added). PostgreSQL transaction behavior has not yet been
executed in this round and remains an explicit validation limitation.

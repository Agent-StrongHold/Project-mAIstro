---
inventory-delta:
  packages/maistro-core/tests: +104
  packages/hive-conductor/backend/tests: +2
---
# Governed harness timer residual (#1192, selective replacement for #1373)

## Scope and provenance

This is the surviving harness wait slice, rewritten against the reviewed #1192
contract. It does not transplant #1373's unauthenticated external-answer writer,
unpaginated recovery sweep, Event composition, or obsolete A2A completion hook.
Existing owner branches and any unpublished work are preserved unchanged.

The dependency-only integration snapshot is `1d844f94615bde8081fb1cbbb7ccfe5ffd5f3450`
(tree `ffd69a740b9a1b3b7c0f7c2c8b8087068ed4adac`), combining these existing heads:

- #1362: `9fd9188e339a6d8474770a5621a473bbe33d680e` (governed history/approval composition)
- #1946: `c36ea32c99dc5b39f7519b88408ca303f71a71cd` (approval continuation helper)
- #1947: `286b79ea547e8107484e3194de0cdc776f962a1a` (current per-node pause carry)

All share develop `35f2e0158a9138e592b56ed84bd08aa2e04c92a4`. Their work is a
prerequisite, not an implementation claim of this residual. The residual must be
retargeted to develop and revalidated after prerequisites land.

## New behavioral cases

`tests/graph/nodes/test_agent_spawn_harness.py` grows from 19 to 92 collected
cases (+73). The added cases exercise the real governed Invocation authority:
first-pause-before-poll, fixed original deadline, canonical observation ordinal,
pending replay, terminal failure domain parity, exact dispatch/observation
provenance, current Binding/provider refusal, new physical Attempts/NodeRuns,
approval before Invocation admission, policy denial after approval, forged
approval bodies, current-pause precedence, CREATED/RUNNING/UNKNOWN refusal,
APPLIED/NOT_APPLIED/INDETERMINATE reconciliation, provider-error uncertainty,
cancellation, bounded physical reads, exact deadline boundaries and original
observation-time evidence. Ambiguous cross-NodeRun legacy receipts under a
wildcard Binding are refused; same-NodeRun or explicitly node-pinned legacy
receipts retain replay support.

`tests/graph/durable_runs/test_harness_timer_recovery.py` adds 15 cases (five
oracles across memory, SQLite and PostgreSQL). These use real canonical Run,
continuation, Binding and Invocation stores with a fake remote adapter:

- persist ordinal zero and the first due instant before any provider poll;
- rebuild stores/effect context/node and complete without redispatch;
- checkpoint exactly one new ordinal after a pending observation;
- fail the local wait at its fixed deadline without claiming remote cancellation;
- two recovery-store instances converge with one physical poll and one dispatch.

SQLite reconstruction opens another connection to the same file. PostgreSQL
uses actual PgRunStore, PgGraphContinuationStore and PostgreSQL effect stores
when the existing service fixture is configured. Reconstruction is not an
OS-process-kill test or a claim of independent PostgreSQL pools.

Hive adds two cases: exact Container adapter identity survives fresh resolver
composition, and a schedule-admitted registered DAG completes through the
shipped `wake_due_registered_dag_runs` caller with one dispatch and one poll.
Existing legacy-answer tests retain their count and terminal domain projection,
while now asserting zero ungoverned provider polls.

## Fail-before evidence

Against the exact dependency integration snapshot, all eight initial memory/
SQLite timer oracles failed: no initial resume instant, no poll/ordinal progress,
and no fixed wait expiry. The five PostgreSQL cases were not run locally.
The Hive adapter-identity regression separately failed before the one-line
resolver pass-through and passed afterward. Initial H1 node regressions also
failed before implementation. Independent review reproduced the wildcard
legacy sibling-receipt defect through actual governed Invocation before its
narrow provenance guard was added.

## Verification limits and retained dependencies

This note is not closure evidence for #1192 or #1373. Local PostgreSQL service
is unavailable; real PostgreSQL execution and process-boundary durability need
exact-head CI/acceptance evidence. Supported adapter/admission profiles must be
explicitly proven. In particular, HarnessRunnerDispatchAdapter retains a
process-local result cache; an unknown handle cannot certify a pending remote
job or provide restart proof.

Production HITL-to-DurableApproval integration remains with #55, and authorized
unattended approval expiry remains with #62. No synthetic system principal,
permission grant, new answer API, second lifecycle, or policy bypass is added.
Historical accepted WAITING pauses with no resume instant are not automatically
backfilled or redispatched by this change; their disposition is separate.
Broader #1613 provider guard/failure semantics and #61/#1062 canonical Event
publication remain with their existing owners.

## Executed local validation

Before the final gate-only decoder refactors, the combined durable-Graph,
Graph-node and affected Hive service test selection passed **1,189 tests, with 44 skips**. Five skips
are this change's PostgreSQL cases; the remaining skipped backend cases retain
their existing service prerequisites. Independent final review ran **178 tests
with five PostgreSQL skips**, including the last empty-server-pause hardening
regression, and found no blocking defect in this bounded H1/H2 scope.

The inventory gate collected **13,409 core** and **3,346 Hive backend** cases and
matched the checked-in per-change deltas. Scoped and full-repository Ruff/format
checks, full configured mypy selection (802 source files), complexity ratchet,
release consistency and the approved stacked-base policy check passed.

The one-process `uv run --frozen pytest -q -ra` aggregate did not execute tests:
it stopped with 53 collection errors because `maistro-core/tests/config` was
loaded as `config` before Hive imported its own `config` module. Per-suite
execution follows the existing CI separation; no import-mode or test-policy
change is included here. Full-suite and remote CI results must be read from the
exact published revision rather than inferred from the focused checks above.

The untouched dependency integration snapshot independently reproduces the same
53 combined-collection errors. Separate full-suite runs on residual `ddf71eb`
reported **12,500 passed / 66 failed / 842 skipped / 1 xfailed** for Core and
**3,310 passed / 24 failed / 12 skipped** for Hive backend. Every one of those
66 Core and 24 Hive failed node IDs was rerun on the untouched integration
snapshot and failed there too. The failures include unavailable SOCKS support,
network/DNS and runtime-environment assumptions; they are not represented as a
green aggregate. The final version-decoder gate adjustment is subsequently
covered by the complete focused suite and exact-head CI remains mandatory.

Vulture bookkeeping removes exactly one now-absent finding, the preexisting
`capabilities/invocation.py::unused variable 'observed_at'` identity. The new
continuation version is read by its actual decoder before receipt lookup;
there is no dummy caller, allowlist expansion, grant, or quality-policy change.

Final reviewed node Git blob: `1a63cae55ce2c14ea5623b22832218b03246f7d8`
(SHA-256 `62f8f5b1977dbfccc96ba8f66d90080260142841f95731c1407e932fdbb63583`).
After the decoder extraction, the exact-source affected harness/Graph/Hive
selection passed **144 tests with five PostgreSQL skips**; independent review
ran **108 tests**, including all 92 node cases. Full mypy (802 source files),
Radon and Vulture were rerun successfully on that final source. The final
refactor changes only decoder structure; the adapter change is documentation.


## 2026-10-05 publication refresh

Current dependency-only snapshot: `575c686635d5ecfe24e3e21f488ffd8d96a49cbc`
(tree `cc4d7b091bd4b33fc9eddc32e86f544af8c1740e`). It preserves the initial
snapshot above and adds current develop
`31d891a561dffd6db1312ea4a85c4835c8048440` plus #1362 head
`afb5b0d4c452007d43bc4bfe2401000670725f96`. #1947 has landed as
`8a063e396e28533243e389a3a85c8efa353061b6` with unchanged source head
`286b79ea547e8107484e3194de0cdc776f962a1a`. #1946 remains open at
`c36ea32c99dc5b39f7519b88408ca303f71a71cd`. Existing dependency acceptance
holds remain; a green check is not a release disposition.

No previously reviewed residual behavior file changed in the refresh. The
merged #1725 memory-exposure patch reverse-applies cleanly, and an independent
review verified exact ancestry and ledger preservation. Refreshed Graph/node/
Hive/memory-authority integration selection: **1,262 passed, 145 skipped**.
Full mypy now covers 803 source files; Ruff/format, Radon and Vulture pass
against this exact dependency base.

Fresh full-suite runs at residual merge `cbf8c50224bb8ac6275bbbde6ee2d93e08e9a458`:
Core **12,599 passed / 66 failed / 943 skipped / 1 xfailed**; Hive backend
**3,310 passed / 24 failed / 12 skipped**. All 66 and 24 failed node IDs were
rerun on the refreshed untouched dependency snapshot `575c686` and failed there
too. This is new baseline evidence; the earlier snapshot's classifications
were not assumed to apply. PostgreSQL remains unavailable locally.

A coverage preflight identified unexercised legacy-pause compatibility paths.
Sixteen test-only cases were then added, bringing the node file from 92 to 108
collected cases (+89 versus its 19-case pre-H1 baseline). They prove explicit
node-local legacy re-entry preserves the canonical dispatch/deadline and
checkpoints ordinal 0 before any poll; typed completed/failed/timed_out answers
work through both current-pause and server-wrapper transports; missing,
foreign or incomplete canonical receipts and mismatched handles refuse.
These are explicit node re-entry tests, not automatic discovery or repair of
historical Graph rows whose resume instant is absent.

Node-only changed-code coverage against `575c686`: 256/278 executable lines
(92.086%) and 120/138 branch arcs (86.957%), exceeding the unchanged 90/80 floors.
No production code, assertions, thresholds, skips or grants changed for these
additional cases. Current inventory delta is +104 Core and +2 Hive backend.

The final refreshed slice run passed **160 tests with five PostgreSQL skips**.
Coverage was collected for `maistro` and the shipped Hive resolver; the exact
`check-diff-coverage.py --base 575c686635d5ecfe24e3e21f488ffd8d96a49cbc`
check passed for all four changed measured files. This is the complete local
diff-coverage check, not just the node-only measurement above.

## First remote PostgreSQL run and fixture correction

The first PostgreSQL coverage job for published head
`4092529b4d636bf61544e9b28e6029a5f36b1f39` reached all five new PostgreSQL cases:
[run 37248090880, job 111569898307](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/37248090880/job/111569898307).
It reported 5,548 passed, 92 skipped, one failure and four setup errors.
The first failure was the fixture's in-memory Project paired with PgRunStore,
which correctly refused the missing canonical_projects foreign key. The later
setups reused the same immutable Binding ID for newly allocated Projects;
the shared PostgreSQL fixture does not truncate capability Bindings.

The correction is test-only: PostgreSQL now creates its Project through
PgProjectScopeStore and supplies that same authority to PgRunStore. Each case
allocates one fresh Binding ID, retained by every reconstruction in that case.
All five test bodies, recovery assertions, production stores and skip rules
are unchanged. Local rerun: 10 passed, five PostgreSQL skips; actual PostgreSQL
execution remains pending the corrected head's CI. No production code,
assertion relaxation, schema workaround or additional test count is introduced.

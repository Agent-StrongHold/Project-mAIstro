# Issue #860 — e025f198 repair checkpoint

## Frozen scope

- One issue: #860; branch `auto-860`, clean starting head
  `02b60f8c0815e8699136f903b032f9816465aacd`; supplied develop base
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inspect existing soak harness, promotion tests, production learning-schema fence,
  adjacent tests, repository instructions and governing ADRs.
- Candidate edits limited to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `quality/vulture-baseline.json` (only reviewed actual scanner findings), an inventory
  note if test coverage changes, and this report. No production changes guessed from
  historical evidence; no deployment or GitHub mutations.
- Run the requested vulture gate, schema/soak tests, lint/format and relevant CI gates.

## Initial evidence / ambiguity

The current job directory contains no `check-*.log` at initial inspection. The supplied
prior `98a11313167b41a98a420abfda80c292/check-3.log` records a schema-fence assertion
expecting 21 statements but observing 24. This may already be repaired; reproduce
before changing it. Prior result `d6a0ddcfb31c43fa88b58207df36ec36/result.json` reports
BLOCKED, not production acceptance. Assume the assignment is a bounded evidence-based
CI repair, not authorization to invent an RC artifact or weaken promotion gates.

## Validation

- Required vulture command passed: 1,323 findings, 1,323 reviewed identities,
  zero unclassified/never-allowlist. No evidence warrants a ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped (1.52 s). Historical failure does not reproduce: expected
  DDL already includes all three validation audit columns at lines 175–177.
- Existing profile explicitly excludes exact-RC equivalence, representative
  users/Workspaces and successful model/Graph/Design/Canvas traffic; its schedule
  probe only admits and cancels a Run. Do not relabel this preflight as acceptance.

Additional commands (all validation commands used a 1,200-second timeout):

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed in 2.36 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run python scripts/check-doc-links.py` | PASS, 2,709 Markdown files, zero broken links |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |

The six schema suite skips require `MAISTRO_TEST_PG_DSN` (the adjacent persistence
fixture explicitly requires a migrated database); no live database race or
production deployment was exercised. Vulture arguments match
`.github/workflows/quality.yml:1078–1081`. No new test or test count change was
needed, so no inventory delta is warranted. Only this report changes.

## Architecture and acceptance evidence

Read the repository instructions, documentation authority map, accepted
ADR-082826-b601 (canonical consumer) and ADR-085 (principal rate limits), and
Proposed ADR-081 (deployment). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The accepted consumer ADR forbids a separate execution/claim authority. The
proposed deployment ADR and the profile's stated scope limits cannot waive #860's
acceptance criteria. No authority or runtime behavior was changed.

Freshly inspected reachable paths:

- `scripts/soak/run_soak.py:744` always rejects preflight artifact equivalence;
  line 1579 feeds that check into generated results. The executed CLI regression
  at `tests/test_soak_promotion_gates.py:106` rejects otherwise-passing four-hour
  synthetic evidence with missing, null or preflight artifact records.
- `scripts/soak/run_soak.py:1067` cancels a schedule probe Run without executing
  it. Admission deduplication does not prove physical-work deduplication.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the production
  middleware; `api/rate_limit.py:93` creates an instance-local limiter. The executed
  test at `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on
  **each** instance for the same authenticated or anonymous identity. This is
  actual middleware behavior, not a simulated shared limiter; it does not prove
  deployment-level replica-selection non-bypass.

| #860 acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED**: inspected `m3a-load-profile.md`; users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background workloads remain gaps. |
| At least two production replicas | **UNVERIFIED**: ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks, restart | **UNVERIFIED**: focused regressions are short tests, not sustained production observations. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED**: schedule probe admits then cancels; no physical-work oracle exercised. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent per-instance allowances reproduced; production non-bypass/security/degraded guarantee **UNVERIFIED**. |
| Complete database, application-loop, worker, RSS, descriptor, queue/error telemetry with thresholds | **UNVERIFIED**: sampler regression passed, but no qualifying live production series captured. Driver-loop latency is not application-loop latency. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED**: no production kill/restart experiment executed. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**: runner deliberately fails exact-RC equivalence, regardless of duration. |
| Findings classified to earliest broken invariant before promotion | Backlog consistency passed; completeness of production findings **UNVERIFIED**. No GitHub mutations. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**: this source-validation report is not an immutable production-soak bundle. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The historical CI error is already repaired, and
there are no scanner findings to bank. Do not redispatch the stale schema log as
an outstanding defect. Remaining work requires a selected immutable RC artifact
and runtime configuration, a representative production workload, physical-work
and recovery oracles, complete telemetry, and the qualifying long soak. Resolve
the replica-selection budget claim rather than treating local enforcement as a
cluster guarantee. A longer host preflight cannot satisfy artifact identity.

No uncommitted incoming work or sync conflict existed. All inherited files are
preserved. This focused round does not certify the broad inherited branch diff.
Local commit is a writer handoff only, never integration approval.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; command errors
0. Bounded CI investigation complete; next is production acceptance evidence,
not speculative code/ledger changes.

# Issue #860 — repair checkpoint (job 9a5827ac)

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `63d2abfb281a83dc39a748f4f0b4ae149e13dd6d`, supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect supplied dispatch context and prior failed `check-3.log`; no GitHub
  enumeration, fetch, mutation, or unrelated branch repair.
- Validation targets: `scripts/check-vulture-baseline.py`, root Ruff checks,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, their governing
  ADRs, workflow gate arguments and soak profile/evidence documents.
- Edit scope: this report; the schema-fence test and matching inventory note
  only if the supplied failure reproduces; vulture ledger/identified source
  only if the exact mandated scan establishes retained/dead identities.

## Initial evidence and assumption

The assigned head resolves and the worktree was clean. No `check-*.log` files
were present in this job directory at entry. The supplied prior log records a
schema-fence assertion mismatch (24 statements versus 21). The supplied prior
result was BLOCKED on exact-RC soak evidence, not a merge conflict. Therefore
no develop merge is assumed necessary. Previous passing claims will be rerun,
not inherited. Actual checks and acceptance disposition follow below.

## Fresh validation checkpoint

All commands below ran with 1,200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,323 findings / reviewed identities,
  zero unclassified and never-allowlist findings; automatically selected base
  `4aa68edc0b6b`. No scan-supported ledger change exists.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Supplied historical failure does not reproduce;
  skipped integration tests are not live database proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **65 passed**.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 53 consumers;
  non-fatal invalid-escape SyntaxWarnings from AST scans.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check`: PASS.

The vulture/provenance/shipped-surface commands match the blocking workflow at
`.github/workflows/vulture-ratchet.yml:76-85`. These local gates selected their
own recorded base above; no claim is made that they compared against the supplied
dispatch base instead.

No source or test edits are justified by these results. No new tests or suite
count delta; no inventory note needed. The remaining task is acceptance review,
not another attempt to fix an already-passing scanner/test.

## Acceptance review

Read the repository `AGENTS.md`, supplied issue body/linked draft PR body and
latest comments from the frozen dispatch, soak profile, production limiter and
schema-fence code, and the promotion regression tests. Read accepted
ADR-081426-1f7c (physical execution identity is Attempt), ADR-081626-f383
(durable fencing), ADR-082126-f69c (recurrence produces canonical Runs), and
ADR-085 (per-principal rate limiting).

Reconciliation: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A schedule
admission count is not physical execution proof. Lease reclaim cannot be invented
by the soak harness; the fencing ADR explicitly separates initial durable fencing
from later reclaim authority. Process-local limits are documented implementation
behavior, not a waiver of #860's replica-selection acceptance criterion. No new
scheduler, authority, store, authorization path, or policy change is proposed.

The schema test already independently expects the three validation-audit columns
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179`, and
production takes its advisory lock inside the transaction at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215-222`. The supplied
21-versus-24 historical assertion is stale for this head.

| #860 acceptance | Freshly inspected/executed evidence and disposition |
| --- | --- |
| Representative release-candidate workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373-1395` uses one credential, health/task/receipt/metrics traffic. `docs/testing/soak/m3a-load-profile.md:152` explicitly leaves users/Workspaces, Graph fan-out, successful tools/models, Canvas and Goal/background workloads incomplete. |
| At least two supported application replicas | **UNVERIFIED for RC.** `run_soak.py:730-742` identifies host-uvicorn preflight, not the promoted Compose artifact. ASGI test instances are not deployed replicas. |
| Sustained saturation, queues, expiry/reclaim, retry/backoff, leaks, shutdown/restart | **UNVERIFIED.** No sustained RC run or long-window resource series executed. Sampler regressions passed, including real wrapper/child resource observation, but do not establish sustained production behavior. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044-1077` cancels the schedule probe Run without executing it. Admission regressions exercise canonical receipt identity, not physical Attempt effects or Goal reconciliation. |
| Rate/security/degraded non-bypass under concurrency/replica selection | **UNVERIFIED overall; independent allowances reproduced.** Executed both parametrizations at `tests/test_soak_promotion_gates.py:439`: the same authenticated/unauthenticated identity obtains `[200, 200, 429]` independently on each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,96` documents/constructs process-local state. Healthy local 429 responses do not prove replica-independent enforcement. |
| Required telemetry and explicit pass/fail thresholds | **UNVERIFIED.** Profile thresholds exist, but no fresh complete series. `run_soak.py:1410-1423` measures driver event-loop lag rather than application lag. |
| Replica restart during active work; drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427-1450` signals after elapsed time, not an observed active Attempt; rejoin and terminal Run counts cannot prove physical recovery. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `run_soak.py:1551` always emits failing `exact_rc_artifact`. Executed `test_four_hour_preflight_cannot_pass_cli` rejects missing/null/preflight artifact evidence, even with synthetic four-hour duration. No four-hour RC soak executed. |
| Findings filed/reclassified before promotion | Local disposition recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This report records the source HEAD only; it is not a deployed artifact evidence pack. No immutable promotion image/config was designated in the supplied assignment. |

## Disposition

**BLOCKED** on acceptance prerequisites, not on the requested CI scan. Only this
report changes; no source/test/ledger/grant modifications. A speculative scanner
repair or another preflight run would not establish the missing exact-artifact
acceptance evidence.

Next: designate the immutable RC image/configuration and representative workload;
disposition the replica-selection allowance at its owning invariant; exercise
physical Attempt effects and active-work recovery through the canonical spine;
then execute the long unchanged RC soak and publish hash-bound telemetry and
findings. This report does not authorize promotion, integration, or issue closure.

Progress: checked 1 issue; CI investigation done 1; acceptance-complete 0;
skipped issues 0; command failures 0. Local commit required; no push.

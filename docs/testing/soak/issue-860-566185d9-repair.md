# Issue #860 — bounded repair 566185d9

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Verified clean starting HEAD: `b7e6e29f6eddd96f72f7434c1d5476883b5169ea`.
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process the supplied dispatch snapshot, prior result and prior check-3 log;
  do not refresh GitHub or enumerate additional issues/PRs.
- Inspect `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, production rate middleware and
  relevant ADRs. Run the specified Vulture gate and focused checks.
- Conditional repair file: `quality/vulture-baseline.json` only if the actual
  scan identifies reviewed retained debt. Otherwise preserve it.
- This report is the checkpoint/handoff; additional implementation is allowed
  only for an evidenced #860 defect, with adjacent tests and inventory notes.

## Initial observations

No `check-*.log` files were present in the supplied current job directory.
The supplied prior result is BLOCKED, not acceptance evidence. No unresolved
merge or uncommitted incoming work exists. Assumption: this is a writer CI-repair
round, not a verifier-only invocation. Exact-RC identity/configuration must not
be inferred from a host-process preflight or historical evidence.

## Validation

The exact requested Vulture command passed: 1,323 findings / 1,323 reviewed
identities, zero unclassified or never-allowlist findings. It selected its
automatic base `4aa68edc0b6b`; no ref or authorization was modified. There is no
actual scanner debt to repair, so no ledger edit is justified.

The supplied historical check-3 log is a schema-test failure, not Vulture:
24 emitted DDL statements versus 21 expected. The current test independently
lists all 24, including three Gauntlet audit columns. Fresh execution is next.
The profile and tests explicitly distinguish local rate enforcement and
host-process preflight from complete production RC acceptance.

Fresh `uv run ruff check .` passed; `uv run ruff format --check .` passed
(3,270 files). The focused pytest command passed with **119 passed, 6 skipped**:

```sh
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q
```

Six PostgreSQL-gated skips are not database integration evidence. In particular,
the supplied schema mismatch does not reproduce. No tests changed; inventory
delta is zero. Validation commands use 1,200-second timeouts.

Additional executed gates:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; two non-fatal invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `git diff --check` | PASS |

The full monorepo test tree and a live production soak were not run. No prior
result or captured PR validation claim is counted as executed evidence here.
The latest captured issue comments and linked PR bodies supply no immutable
promotion RC identity or completed acceptance run.

## Architecture reconciliation

Read accepted ADR-081226-69ee, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
physical runtime identity is the Attempt ID, not an admission receipt. The later
lease ADR supplies renewal/reclamation semantics beyond the older fencing ADR;
a schedule admission race cannot establish those properties under load.
ADR-085's per-principal requirement is not proof of a distributed rate budget.
The stronger replica-selection acceptance remains unmet rather than being
rewritten to mean a local 429. ADR-081 was read but is **Proposed**, not accepted
authority for waiving RC evidence. No execution, authorization, store or event
authority is changed.

## Acceptance review

| # | Criterion | Fresh evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:152` lists missing multi-user/Workspace, Graph fan-out, successful tools/models and Design/Canvas traffic. `run_soak.py:1373` uses one credential; the mix at 1381 does not supply those workloads. |
| 2 | Two application replicas in supported deployment | **UNVERIFIED for the RC.** `run_soak.py:730` identifies host-uvicorn preflight, not the promoted Compose artifact. ASGI middleware tests do not constitute deployed replicas. |
| 3 | Sustained saturation, queue, reclaim/retry, leak observations | **UNVERIFIED.** No fresh long-running load was executed. Unit/regression tests cannot prove pool saturation, lease expiry/reclaim, retry/backoff or long-window leak behavior. |
| 4 | No duplicate physical work, including schedules and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044` cancels the schedule probe Run without execution. Passing admission-accounting tests are not physical Attempt/effect uniqueness or Goal reconciliation proof. |
| 5 | Rate/security/degraded non-bypass across replicas | **UNVERIFIED as a whole; stronger rate claim falsified locally.** The two passing cases at `tests/test_soak_promotion_gates.py:439` exercise production middleware with identical identity on two instances: both independently return `[200, 200, 429]`. `rate_limit.py:32` explicitly documents N-times-limit aggregate scope. |
| 6 | Complete production telemetry with thresholds | **UNVERIFIED.** The real uv-child sampler test passes, but `run_soak.py:1410` measures driver loop lag, not application loop lag; the driver database probe is not application pool-wait/query telemetry. No fresh complete production series exists. |
| 7 | Active-work kill/restart, graceful drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427` schedules a signal by elapsed time, not observation of an active physical Attempt. Rejoin and aggregate terminal counts do not prove no silent loss or duplicate effects. |
| 8 | Long unchanged exact-RC soak | **UNVERIFIED.** `run_soak.py:730` unconditionally rejects preflight artifact identity. All three four-hour preflight CLI regression cases pass by rejecting absent/null/preflight identity; no actual four-hour RC run occurred. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED externally.** Gaps and their scope are recorded locally here. GitHub mutations are prohibited; no filing, closure or external disposition was performed. |
| 10 | Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for an RC soak.** This report identifies the checked HEAD and executed commands, but is not a machine-readable production soak or image/config identity pack. Historical packs are not transferred to this head. |

## Handoff

**BLOCKED for issue acceptance.** Only this report changed in this round. The
reported stale schema failure is already repaired at the starting head; the
Vulture ledger already exactly matches the scanner. Editing either without new
evidence would be cosmetic or guessed repair. No tests or inventory counts
changed, and all inherited work is preserved.

Next: select the immutable RC image/configuration intended for #89; implement
and run a production-topology workload covering the missing supported surfaces,
physical Attempt/effect reconciliation and application telemetry. Resolve the
replica-selection budget contract through the existing limiter/authorization
seams. Then run the full unchanged long soak and publish hash-bound machine and
human evidence, with failures dispositioned before promotion. A further rerun
of the same stale check or a four-hour host preflight cannot close these gaps.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; fresh
validation errors 0. Local report commit is the deliverable, not merge or
promotion approval.

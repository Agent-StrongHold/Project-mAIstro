# Issue #860 repair checkpoint — ba3f34b9

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `4049bca8d48db79b4282abe7718a8ce9ee9d28c0`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree is clean. No incoming changes require salvage.
- Review inputs: supplied dispatch-context.json, prior result
  76d87a9659484508a2a5f429804fa3b7, and prior check-3.log
  98a11313167b41a98a420abfda80c292. No check-*.log files were present in
  this job directory at initial inspection.
- Production/test scope: scripts/soak/run_soak.py,
  tests/test_soak_promotion_gates.py, task admission in maistro-server,
  adjacent concurrency tests, existing m3a load profile and evidence.
- Candidate edits: this report; quality/vulture-baseline.json only if the
  prescribed scan provides actual reviewed identity evidence; production/test
  changes only for demonstrated #860 defects within the scope above.
- Ambiguity: assignment is a CI repair but prior result reports missing
  production acceptance evidence. Treat these as separate questions. Do not
  manufacture production acceptance from deterministic tests or change gates.

## Progress

The exact prescribed Vulture scan passed: 1323 findings / 1323 reviewed
identities, zero unclassified or never-allowlist findings. No ledger amendment
is justified. The historical check-3.log is a schema-fence assertion failure
(24 DDL statements versus 21 expected), not a scanner failure.

Fresh focused validation passed: 126 passed, 6 skipped in 3.12 seconds:

```text
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q
```

The historical failure does not reproduce. Skipped database tests and ASGI
checks do not establish a deployed multi-replica soak. No production code or
test change is warranted by these results.

Additional fresh checks (1200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2690 Markdown files,
  zero broken relative links.
- `git diff --check`: PASS.

Vulture invocation matches `.github/workflows/vulture-ratchet.yml:82`:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
(600-second timeout). No new tests, inventory delta, ledger/grant changes,
production changes or runtime configuration changes in this round.

## Architecture reconciliation and acceptance evidence

Read repository instructions and accepted ADR-081226-a66b, ADR-081626-f383,
ADR-082526-b36a, ADR-082826-08f0 and ADR-085. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. Queue receipts are not a competing
execution lifecycle.

**Correction to the prior handoff:** the original fencing ADR's historical
boundary does not mean reclamation policy is still undefined. Accepted
ADR-082526-b36a defines renewable TTL leases and expiry reclamation;
ADR-082826-08f0 defines canonical recovery dispositions and lifecycle
reconciliation. A production soak must exercise those existing contracts,
not invent another scheduler or treat the old boundary as a waiver. This round
does not claim runtime coverage of their full recovery behavior.

The historical schema assertion is already repaired at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:177`: all three
validation-audit columns are explicitly included. Production schema upgrades
acquire the transaction-scoped advisory lock at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.

`tests/test_soak_promotion_gates.py:439` freshly passed against the production
rate middleware: the same identity gets 200/200/429 independently on each
instance, with both authenticated and unauthenticated cases. This agrees with
the process-local contract in
`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`, but does not
prove replica selection cannot increase aggregate allowance. ADR-085 requires
per-principal limiting; do not silently convert local enforcement into proof
of a cluster-wide budget. Release acceptance needs explicit reconciliation.

`tests/test_soak_promotion_gates.py:564` freshly passed through the production
task router: the admitted receipt reads 200 locally and 404 on the peer.
`packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the local
queue. Admission visibility is not a physical-execution deduplication oracle.

`scripts/soak/run_soak.py:744` unconditionally reports the host preflight as
not the exact production Compose artifact. The executed CLI gate tests reject
otherwise-passing synthetic four-hour evidence without exact-RC identity.
Running this emulator longer would not satisfy promotion acceptance.

| Issue acceptance criterion | Current evidence / disposition |
| --- | --- |
| Representative RC workload | Profile read; its remaining-gaps section excludes multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. **UNVERIFIED**. |
| At least two production application replicas | Executed ASGI-instance tests only; no deployed RC replicas this round. **UNVERIFIED**. |
| Sustained saturation, retries, lease reclaim, leaks and shutdown | Sampler and accounting regression tests pass; no sustained production execution this round. **UNVERIFIED**. |
| No duplicate physical work across schedules/task/Run/Attempt/Goal | Admission identity checks pass; no full physical-work oracle under load. **UNVERIFIED**. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Local limiter and admission backpressure checks pass; independent allowances demonstrated. Full criterion **UNVERIFIED**. |
| Required production metrics and pass/fail thresholds | Partial sampler/gate tests pass; application event-loop latency, full pool and worker behavior not established. **UNVERIFIED**. |
| Kill/restart during active work; drain/fencing/recovery | Boot contracts pass, not active-work kill/recovery evidence. **UNVERIFIED**. |
| Long-running exact RC artifact/config soak | Current runner explicitly fails this gate; no immutable RC/configuration designated in the assignment, no production soak executed. **UNVERIFIED**. |
| Findings filed/reclassified before promotion | No new live-load findings claimed; no GitHub mutation performed. **UNVERIFIED**. |
| Published machine/human soak evidence tied to all artifact hashes | This report identifies validated source HEAD only, not a production soak. **UNVERIFIED**. |

## Handoff

**BLOCKED**, not integration approval. Only this report changes. Actual supplied
CI failure no longer reproduces; inventing a scanner or ledger repair would not
address evidence. Required next work is to designate the immutable RC and
production configuration, complete the representative workload/physical-work
oracles, reconcile the rate-limit acceptance contract, and run the exact-RC
soak (profile minimum four hours). Do not repeat a passing static scanner as
an attempted substitute for these acceptance requirements.

Progress: checked 1, done 0, skipped 0, validation errors 0; next: production
acceptance prerequisites above. Existing work remains preserved; commit is a
validation handoff only.

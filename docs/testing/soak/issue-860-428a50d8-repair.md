# Issue #860 — repair pass 428a50d8

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`4601a5e36e959d303f2c8368be5a64fcbcfc6603`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Worktree started clean. No driver `check-*.log` files were present in this job
directory at initial inspection. Prior results are claims, not fresh validation.

Files eligible for edits in this pass: this handoff and
`quality/vulture-baseline.json` only if the prescribed scan identifies reviewed
retained debt. Production/test edits require concrete reproduced evidence and an
explicit scope update here first. No grants, other issues, remote mutations,
or execution-authority changes.

Assumption: this is a writer CI-repair assignment, not the read-only verifier
role described in the shared prompt. Existing long-soak acceptance remains to
be checked; passing unit tests must not be represented as production soak proof.

## Results

The exact prescribed Vulture scan passed: 1323 findings, 1323 reviewed
identities, zero unclassified and zero never-allowlist findings. No ledger
amendment is warranted. The historical check-3.log is a schema-fence test
failure, not a Vulture failure; it does not reproduce now.

Fresh focused pytest: 126 passed, 6 skipped in 2.92s. Both repository-wide
Ruff checks pass (3277 files already formatted). Commands used 1200-second
timeouts:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
```

These are deterministic regression checks, not production-soak evidence.
No new tests or inventory delta in this pass.

`uv run python scripts/check-doc-links.py` passed (2691 Markdown files, zero
broken relative links); `git diff --check` passed. No validation command failed.

## Architecture and reachable behavior

Read the captured primary issue's complete acceptance list, repository
instructions/documentation authority map, accepted ADR-081226-a66b,
ADR-082526-b36a, ADR-082826-08f0 and ADR-085, the existing load profile,
production admission/rate middleware/schema-fence code and adjacent tests.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Renewable lease TTLs and
canonical recovery dispositions already have accepted contracts; neither a
second scheduler nor receipt state may replace them.

- `packages/maistro-core/tests/persistence/test_pg_learnings.py:177` already
  explicitly expects the three validation-audit columns absent from the old
  failed assertion. The fresh schema-fence test passes against the production
  transaction/advisory-lock boundary at
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.
- `scripts/soak/run_soak.py:744` unconditionally rejects the host-process
  preflight as exact-RC evidence. Extending its duration cannot satisfy the
  artifact gate. Its gate regression tests passed in this run.
- `tests/test_soak_promotion_gates.py:439` exercises production rate middleware:
  the same identity receives 200/200/429 independently on both instances.
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` explicitly
  documents the process-local allowance. ADR-085 requires principal-keyed
  limiting, but does not itself prove a shared cluster budget. The issue's
  stronger replica-selection claim remains unreconciled; do not silently
  waive it or invent an alternate authorization path.
- `tests/test_soak_promotion_gates.py:564` executes the production task router
  with shared canonical admission: an observed receipt is 200 on its owner
  and 404 on its peer. The route reads its local queue at
  `packages/maistro-server/src/maistro_server/api/tasks.py:144`.
  This proves visibility behavior, not physical-work deduplication.

## Acceptance disposition

Every item below is from the supplied #860 snapshot. None is inferred from
historical handoff claims or treated as fulfilled by unit-test success.

| Criterion | Fresh evidence and remaining requirement |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: existing profile explicitly lacks multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. |
| At least two production replicas | **UNVERIFIED**: executed ASGI-instance tests, not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff, leaks and shutdown | **UNVERIFIED**: accounting/sampler regressions pass; no sustained production run executed. |
| No duplicated physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**: admission/receipt regression tests do not observe all physical execution. |
| Rate/security/degraded behavior non-bypass across replicas | **UNVERIFIED**: production middleware has independently exhausted allowances; backpressure tests pass but do not establish the stronger multi-replica contract. |
| Required metrics and explicit thresholds | **UNVERIFIED**: current sampler/profile is partial; driver loop latency is not application loop latency and full pool/worker behavior is not established. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**: boot contracts pass; no active-work production kill/recovery performed. |
| Long-running exact-RC soak | **UNVERIFIED**: runner intentionally fails exact-RC gate; no promotion image/config identity designated in this assignment, no four-hour RC soak executed. |
| Findings filed/reclassified before promotion | **UNVERIFIED**: no new live-load findings claimed; no GitHub mutations permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED**: this handoff identifies the source checked, not a production artifact soak. |

## Handoff

**BLOCKED** on acceptance prerequisites, not on a reproducible scanner failure
or merge conflict. Only this handoff changes; no ledger, grant, test, runtime
configuration or production-code edits are justified by this pass. Existing
work is preserved. Local commit is a validation checkpoint, not integration
approval.

Next: designate the immutable RC and production configuration, complete its
representative workload and physical-execution oracles, reconcile the
replica-selection rate contract, then execute and publish the exact-RC soak.
Repeating the passing scanner is not a repair for missing production evidence.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; next is the
production acceptance work above.

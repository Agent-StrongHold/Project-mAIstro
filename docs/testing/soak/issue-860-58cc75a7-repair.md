# Issue #860 — bounded repair 58cc75a7

## Frozen scope and initial results

Only issue #860, assigned worktree/branch `auto-860`, starting clean at
`713ce7d90210dd4a9e0e18e954ce61c58a38d1ff`; supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.

Review scope: supplied dispatch snapshot and prior result/check-3 artifacts,
repository instructions, relevant execution/fencing/rate-limit ADRs, existing
soak profile/driver/tests, production limiter wiring and schema-fence tests.
Edit scope: this report; `quality/vulture-baseline.json` only if the requested
scan demonstrates an identity discrepancy. No unrelated issues or PRs processed.

The current job directory has no driver check-*.log files. Supplied historical
check-3.log reports 24 schema statements versus 21 expected. Fresh validation:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Historical failure does not reproduce.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1323 reviewed identities / 1323 findings, zero unclassified or
  never-allowlist identities. No ledger amendment justified.

Ambiguity: CI repair instructions coexist with full release-soak acceptance.
Proceed by checking the supplied failure and actual production evidence, not
inventing a candidate release or altering passing gates. Prior BLOCKED result
is an acceptance blocker, not a develop-sync conflict. No merge required.

## Focused validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, **66 tests**.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique identities, no duplicate evidence.

The current schema-fence test independently expects all 24 statements, including
`validated_evaluator_version`, `validation_run_ids`, and
`validation_content_hash` (test_pg_learnings.py:176–178). Production declares
these columns in `_EPISTEMIC_COLUMNS`. The historical 21-statement expectation
has already been corrected; changing this passing test would not repair anything.
The six skipped tests do not constitute live PostgreSQL evidence.

## Architecture reconciliation

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085,
and proposed deployment ADR-081. Graph snapshots and canonical Run/NodeRun/Attempt
identity remain authoritative. Lease renewal/reclaim extends the older fencing
contract; the older deferral is not an acceptance waiver. ADR-085's per-principal
keying does not supply cluster-wide storage. ADR-081 is Proposed, not authority
to introduce a second scheduler or waive canonical execution. No runtime changed.

Production `main.py:648` installs `RateLimitMiddleware`, whose constructor at
`api/rate_limit.py:93` creates an instance-local `InMemoryRateLimiter`. The executed
`test_replica_selection_has_an_independent_production_allowance` at
`tests/test_soak_promotion_gates.py:439` sends the same credential/IP to two actual
middleware instances: each accepts two requests then rejects with 429. This is a
meaningful reproduction of independent budgets, not a deployed concurrency soak.
The existing source explicitly documents N-times-limit semantics, so local
429 enforcement must not be relabeled as proof of replica-selection non-bypass.

## Acceptance assessment (all ten criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | UNVERIFIED: reviewed `m3a-load-profile.md:155`; it explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool, Canvas and Goal traffic. No designated RC scope closes those gaps. |
| Two application replicas | UNVERIFIED: `deploy/docker-compose.prod.yml:26,75` defines two services, but no exact-RC deployment was run. ASGI instances are not deployment evidence. |
| Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: focused tests supply no sustained window. |
| No duplicate physical work across admissions/reconciliation | UNVERIFIED: gate tests reject invalid admission evidence but do not witness deployed physical execution. |
| Rate/security/degraded non-bypass | Independent per-replica allowances reproduced by the executed middleware test; deployed non-bypass remains UNVERIFIED. Backpressure tests are not complete security/degraded soak coverage. |
| Full telemetry with explicit thresholds | UNVERIFIED: profile records missing application-loop/pool/worker observations; no current RC telemetry captured. |
| Active-work restart/drain/fencing/recovery | UNVERIFIED: fail-closed drain gate tests pass, but no active production replica was restarted. |
| Long exact-RC artifact/configuration soak | UNVERIFIED / BLOCKED: `scripts/soak/run_soak.py:730` unconditionally rejects its host-process topology. Executed synthetic four-hour preflight tests confirm rejection, not a real four-hour run. No designated immutable RC artifact/configuration supplied. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification UNVERIFIED. No GitHub mutation performed. |
| Hash-bound machine/human soak evidence | UNVERIFIED for this RC. Historical shakedowns cannot certify the present artifact; this report is not a soak evidence pack. |

## Handoff

Only this report changed. No tests added/removed; no inventory delta required.
No ledger discrepancy or reproduced CI failure warrants a speculative repair.
Existing work preserved; no merge, push, PR or issue mutation performed.

Verdict: **BLOCKED** on release acceptance, not on the supplied stale check-3 or
vulture scan. Next: supply the immutable RC artifact/configuration and workload
scope, implement/use an exact-topology runner, and collect at least four hours
of full telemetry and physical-work/recovery witnesses. Repeating this already
passing CI-repair scan cannot satisfy that prerequisite.

Progress: checked 1, done 0 (release acceptance incomplete), skipped 0,
command errors 0. Report committed locally for handoff, not integration approval.

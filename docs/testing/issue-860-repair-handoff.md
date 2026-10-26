# Issue #860 repair checkpoint

## Frozen scope

- Issue #860 only; assigned branch `auto-860`, starting HEAD
  `5daebe7efa744facf6ea3eb92121dcb27d819680`, dispatch base
  `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Repair the evidenced CI failure, including the expressly authorized vulture
  per-identity ledger repair if the exact scan reports retained debt.
- Inspect existing issue-860 implementation/evidence and relevant ADRs; do not
  treat CI success as execution of the release-candidate soak.
- Incoming edits: `scripts/ci_merge_group_scope.py` and
  `tests/test_ci_merge_group_scope.py`, preserved before edits in
  `../incoming-860.patch`. Assumption: these are salvage from the prior repair;
  validate before retaining. No other issues/PRs will be processed.
- Potential edit paths are those two incoming files, an inventory note for their
  test addition, this handoff, and `quality/vulture-baseline.json` only if the
  prescribed scan supports an amendment. Other files are inspection-only.

## Initial evidence

- Working directory and HEAD match assignment; two incoming modified files.
- Current job directory contains no `check-*.log` files at initial inspection.
- No refetch/re-enumeration of GitHub; use the supplied dispatch snapshot.

## Results

- Exact vulture command passed: 1328 reviewed identities / 1328 findings,
  zero unclassified. No ledger amendment is justified or needed.
- Prior `98a113.../check-3.log` reports a learnings-schema test expected 21 DDL
  statements but observed 24. Fresh targeted run on this HEAD passes:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q` — 37 passed, 6 skipped. No schema-test repair is justified.
- Prior result `6cc9ebb6.../result.json` was BLOCKED on soak acceptance, not a
  develop merge conflict. No sync/merge is indicated by that evidence.
- The branch already contains the soak harness and extensive historical
  evidence. This round will not expand into unrelated historical repairs.

- `uv run ruff check .` passed. `uv run ruff format --check .` failed only
  on the incoming classifier edit; retain its behavior and correct formatting.
- `.github/workflows/ci.yml:853-879` proves the wheel-import verifier is in the
  conditionally selected job. Incoming classifier repair therefore addresses
  a real missing trigger, not an assumed scanner finding.
- An inspection path for server `middleware/rate_limit.py` was not found;
  skipped. Use the existing production-middleware test imports instead.

- Incoming regression test fails against the exact starting-HEAD classifier
  executed in memory, and passes against the repaired classifier. Source files
  were never replaced for this mutation check.
- Focused CI-scope, soak-gate, boot-contract and server backpressure tests:
  **94 passed**. Includes real production rate-limit middleware with independent
  allowances on two ASGI application instances (not a live two-container soak).
- `uv run python scripts/check-suite-inventory.py --suite tests/` passed:
  **5056** collected identities; delta note accounts for the one salvaged test.

## Architecture reconciliation

Read ADR-081226-9944 (product ownership), ADR-081226-69ee (Graph/Node execution),
ADR-081626-f383 (Attempt lease/fencing) and ADR-081 (deployment). The first three
are Accepted; ADR-081 remains Proposed and cannot waive accepted execution
contracts. No scheduler, store, authorization, event authority or execution
model changes are introduced. Admission deduplication is not proof of physical
Attempt fencing. Lease-expiry takeover is explicitly outside ADR-081626-f383's
initial boundary; the soak still needs evidence for whichever reclaim behavior
the selected RC actually claims. The documented process-local rate limit is not
proof of issue #860's stronger replica-selection non-bypass criterion.

## Final validation

All commands ran locally in the assigned worktree with 1200-second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1328 reviewed / observed identities; ledger unchanged |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped (not PostgreSQL integration proof) |
| `uv run pytest tests/test_ci_merge_group_scope.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 94 passed |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS, 5056 identities |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS after correcting incoming formatting, 3159 files |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19 classified / observed lifecycles |
| `uv run python scripts/check-doc-links.py` | PASS, no broken relative links |
| `git diff --check` | PASS |
| `uv run python scripts/ci_merge_group_scope.py --json scripts/verify-wheel-imports.py` | Wheel imports and Docker true; other specialized legs false |

The in-memory regression check used `git show` at the exact assigned starting
HEAD, then invoked the new test with its classifier rebound to that source.
It failed at the wheel-import assertion before the repair and passed after it.
The source tree was not mutated for that check.

A fresh `uv run python` evaluation imported the actual soak evaluator and read
`docs/testing/soak/evidence/m3a-round30-shakedown.json`: it reports **420.08 s**
against **14400 s**, failing `sustain_duration` and `exact_rc_artifact`.
Its `hashes.git_head` is `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, not this
candidate. This verifies rejection of historical evidence, not execution of a
new soak. No host preflight was launched because it cannot satisfy the exact-RC
criterion even if extended to four hours (`scripts/soak/run_soak.py:730`).

## Acceptance assessment (not promotion approval)

| Issue #860 criterion | Executed evidence / outstanding requirement |
| --- | --- |
| Representative RC load profile | PARTIAL: inspected `m3a-load-profile.md`; its remaining-profile-gaps section admits missing users/Workspaces, fan-out, successful calls, Design/Canvas and Goal workloads. Representative coverage UNVERIFIED. |
| At least two production replicas | UNVERIFIED in this round. Two ASGI middleware instances are tests, not production Compose replicas. |
| Sustained saturation, reclaim, retry, leaks and shutdown | UNVERIFIED: no long production soak executed. Historical duration rejected by actual evaluator. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission probe tests pass but do not establish physical-work uniqueness or Goal reconciliation. |
| Security/rate/degraded behavior cannot be bypassed by replica choice | NOT PROVEN: passing production-middleware tests show each replica independently returns 200, 200, 429 for the same identity. Production main installs that middleware at line 648. Local enforcement is not a shared budget. Backpressure tests pass separately. |
| Complete production telemetry with thresholds | UNVERIFIED: sampler/gate tests pass, but driver loop lag is not application loop lag; no full production measurement window. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED: boot cleanup and gate tests are not live physical-work recovery evidence. |
| Long exact-RC/config soak | UNVERIFIED / BLOCKED: current host-process runner always fails artifact gate; selected historical evidence fails duration and artifact gates. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness. No GitHub mutation attempted; this note records the outstanding evidence gaps locally. |
| Machine/human exact-artifact hash-bound evidence | UNVERIFIED for this candidate: existing historical evidence is not tied to this HEAD or the promoted image/configuration. |

## Handoff

Changed files this round: the two preserved classifier/test files, one +1
inventory note, and this handoff. No quality ledger, runtime, governance gate,
Soak threshold, or authorization change. The inherited classifier salvage is
CI-only and not asserted to repair the broader soak acceptance gaps.

Result: **BLOCKED** on issue acceptance, although focused CI repair is complete.
Checked: 1 assigned item; CI repair done: 1; complete issue acceptance: 0;
skipped items: 0. Historical schema failure did not reproduce; initial incoming
format failure was repaired. Next: select an exact RC image/configuration and
provide a production-topology runner/profile covering the gaps, then execute the
required long soak. Do not repeat short preflights as promotion evidence.

No release-promotion claim. Local commit only; no push or GitHub mutation.

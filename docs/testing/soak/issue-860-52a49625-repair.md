# Issue #860 CI repair — job 52a49625

## Frozen scope and starting state

- Assigned issue only: #860; writer lane `auto-860`.
- Verified starting HEAD: `14fdf9542ecd4805f56c6af63d40662a2919d71b`.
- Verified develop base: `534d475e6360985a2c95d6c82869d07001e82cda`.
- Worktree initially clean; no incoming changes to salvage.
- Frozen inputs: supplied `dispatch-context.json`, supplied prior result if present,
  repository instructions, relevant ADRs, soak runner/profile/tests and exact
  vulture gate implementation/workflow/ledger.
- Repair targets: this handoff and `quality/vulture-baseline.json` only if the
  required scan identifies retained debt; genuinely dead source only if proven
  by that scan and surrounding callers/tests. No unrelated issues or remote mutations.
- Assumption: explicit CI-repair permission allows reviewed ledger amendments,
  not weakening gates or claiming that unit tests replace the production soak.
- No `check-*.log` files were present in the supplied job-directory listing.

## Progress

Initial refs and clean state verified. Required exact vulture scan executed:
exit 0; 1,338 findings match 1,338 reviewed identities; zero unclassified or
never-allowlist findings. No ledger/source repair is justified by this scan.
Log: `/tmp/issue-860-52a49625-vulture.log`. Its automatic merge base is
`8a4bc239fe9a`, not the dispatch develop ref; record this rather than silently
claiming a scan against the supplied base.

Supplied prior result was read: it reports BLOCKED, not a sync conflict.
The guessed prior handoff filename `issue-860-2ed49662-repair.md` was not found;
skipped. The prior result does not establish current acceptance. The current
profile explicitly labels the runner a host-process preflight, with missing
representative workload surfaces and no exact-Compose artifact proof.

Read ADR-081 (Proposed), ADR-081226-a66b (Accepted lifecycle), and
ADR-081626-f383 (Accepted execution fencing). Reconciliation: admission counts
are not physical-work proof; lease-expiry takeover is explicitly outside the
accepted fencing ADR's current boundary. Do not invent reclaim authority or a
second scheduler to satisfy the issue. ADR-081 alone is not an accepted topology
contract. Production middleware explicitly enforces process-local budgets;
#860's stronger replica-selection requirement remains unmet, not waived.

`git diff --check 534d475e6360985a2c95d6c82869d07001e82cda...HEAD`
passed: the historical EOF finding is not reproduced at the assigned head.
The vulture workflow confirms the requested scan arguments and uses
`RATCHET_BASE_REV`; a second scan will pin the verified dispatch base.
A mistargeted handoff edit matched no text and made no change.

Validation checkpoint: ruff check passed; format check passed (2,917 files);
all 52 existing soak-promotion tests passed in 1.31s, including production
middleware replica-selection counterexamples and real Linux process-group
sampling. The explicit `RATCHET_BASE_REV` scan also passed, resolving the
supplied ref to merge-base `8a4bc239fe9a` as the ratchet reports. Both scans
agree; no debt is unbanked. No tests have been added or changed, so no inventory
delta is required. Remaining bounded validation completed below.

## Executed validation

Validation batches used 1,200-second timeouts in the assigned worktree.
Logs use `/tmp/issue-860-52a49625-` as prefix.

| Command | Outcome / log suffix |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,338 exact reviewed identities; `vulture.log` |
| Same command with `RATCHET_BASE_REV=534d475e6360985a2c95d6c82869d07001e82cda` | PASS; `vulture-base.log` |
| `uv run ruff check .` | PASS; `ruff-check.log` |
| `uv run ruff format --check .` | PASS, 2,917 files; `ruff-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 52 passed; `pytest.log` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 23 passed; `server-tests.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 14 suites, 25,950 unique identities; `inventory.log` |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items; `backlog.log` |
| `uv run python` importing the current runner and calling `failed_promotion_checks` on `m3a-round6-shakedown.json` | Rejected: `sustain_duration`, `exact_rc_artifact`; 90.43 seconds versus 14,400 required |

The historical-evidence evaluation also called `preflight_artifact_check()`:
`ok=false`, `topology=host-uvicorn-preflight`. No production soak was launched:
running this emulator longer cannot satisfy its explicit exact-RC failure.

## Acceptance disposition (all ten issue criteria)

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative users/Workspaces and workload | PARTIAL definition only. `m3a-load-profile.md:152-165` explicitly lacks users/Workspaces, Graph fan-out, successful model/tool, Canvas and Goal workloads. Representative RC profile UNVERIFIED. |
| At least two application replicas | `deploy/docker-compose.prod.yml:26-80` defines two replicas; tested six-path topology validation is not deployment execution. Exact-RC multi-replica behavior UNVERIFIED. |
| Sustained saturation, reclaim, retry, leaks and restart | Historical `m3a-round6-shakedown.json:221-224` is 90.43 seconds. No new sustained run; UNVERIFIED. |
| Admission, reconciliation and physical-work fencing | Existing HTTP oracle tests pass; server backpressure contract passes. Neither executes cross-replica physical Attempts; `m3a-load-profile.md:197-200` explicitly distinguishes schedule admission from execution. UNVERIFIED. |
| Rate limiting/security/degraded behavior across replicas | Local principal/auth/backpressure tests pass. `tests/test_soak_promotion_gates.py:439-488` reproduces fresh allowance on replica 2 for both authenticated and unauthenticated identity; shared/non-bypass requirement NOT MET. Full RC security/degraded soak UNVERIFIED. |
| Complete telemetry with thresholds | Sampler regressions pass, including actual child-process RSS/FD growth; profile distinguishes driver-loop from application-loop lag. Complete deployed worker/loop/pool/queue/lock/error telemetry UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | Historical process exit/rejoin is not current physical-work recovery proof; no new deployed test. UNVERIFIED. |
| Long soak of exact RC artifact/configuration | NOT MET: current runner fails `exact_rc_artifact` unconditionally (`scripts/soak/run_soak.py:635-668`); historical duration also fails when evaluated now. |
| Findings filed/reclassified to earliest invariant | Human pack records findings and classifications (including F11/F12 as M3-A evidence validity); backlog consistency passes but does not prove complete filing. Complete criterion UNVERIFIED. No GitHub mutation permitted or performed. |
| Published machine/human evidence with exact hashes | Historical pair exists but cannot establish current artifact identity. Fresh current-RC evidence UNVERIFIED. |

## Handoff

**BLOCKED** on issue acceptance, not on the requested vulture CI gate. The gate
repair item is explicitly skipped because the actual scan passes; no invented
dead-code deletion or ledger amendment was made. Only this handoff is changed.
No source, runtime configuration, tests, inventory baseline, grants or gates
were changed. There was no develop-sync conflict to resolve.

Next owner needs an exact production-artifact runner, an explicit RC profile
covering the omitted surfaces, resolution of the documented replica-budget
mismatch, and a new at-least-four-hour measured soak proving physical fencing
and recovery. Do not rerun the host preflight or amend a clean ledger as a
substitute. Accepted lifecycle/fencing authority must remain canonical.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped
1 unnecessary ledger repair; errors 0 validation-command failures. One missing
prior filename and two rejected handoff edits made no changes; all were
resolved or skipped without broadening scope. This is not integration approval.
Commit this evidence locally; no push or issue closure.

# Issue #860 — repair validation (job 0afe221c)

## Frozen scope

- Issue: #860 only; writer lane, worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `1e8f85126fb02c1143b08035f4e7e89660aa8cd9` (resolved; clean).
- Base: `4df9dd9bde4c6d03fccd1466cf9d6827a8fd4aa8` (resolved).
- Review files: repository instructions; ADR-046, ADR-062, ADR-081,
  ADR-085, ADR-081426-1f7c, ADR-081626-f383;
  `scripts/soak/run_soak.py`, `scripts/soak/nginx-soak.conf`,
  `deploy/nginx.conf`, `deploy/docker-compose.prod.yml`,
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`,
  four historical JSON evidence packs: `m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json`,
  `m3a-round6-shakedown.json`;
  `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`;
  server rate limiter/tasks and adjacent concurrency tests;
  core PG learnings implementation and adjacent tests;
  `scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`.
- Edit scope: this report; genuinely evidenced CI debt in the requested ledger
  scan only if found. No speculative runtime repair or promotion claims.
- No new test is planned unless an actual defect requires a focused repair.

## Initial evidence / ambiguity

The assigned job directory contains no `check-*.log` files at initial snapshot.
Driver green claims are therefore unavailable, not assumed. The previous result
is present and says BLOCKED; its claims will be revalidated locally.
The brief requests a writer repair, so the verifier-only no-edit restriction
is not applicable. A supported production artifact/configuration to promote is
not identified by an image digest in the assignment. Historical preflight
traffic must not be relabeled as an exact-RC soak.

## Results

- Requested exact vulture command executed successfully: 1371 findings / 1371
  reviewed identities, zero unclassified, zero never-allowlist violations.
  No ledger amendment or dead-code deletion is justified by this output.
- Current profile explicitly excludes promotion eligibility for the host-process
  harness; historical evidence is explicitly provisional. The prior false
  shared-store H3 claim is already corrected in the starting HEAD.
- ADR reconciliation: ADR-046 is superseded by ADR-082126-f69c (follow-up read
  required); ADR-081 is Proposed, not an accepted waiver. Accepted runtime and
  lease ADRs tie physical execution to canonical Attempt identity and fenced
  mutations, not merely a deduplicated Run admission. ADR-085's per-principal
  limits do not establish a cluster-wide implementation. No new execution or
  authorization authority is introduced.

- Followed ADR-046's supersession to accepted ADR-082126-f69c: recurrence
  produces canonical Runs, never a separate persistent scheduler.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2720 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  -x -q -rs`: **88 passed, 5 skipped** in 8.67s. The five real-PG learnings
  tests require `MAISTRO_TEST_PG_DSN`; they are not counted as proven. No new
  tests were added; no inventory delta is required for this report-only change.
- Executed `uv run python` importing the current `failed_promotion_checks`
  against each of the four frozen historical JSON packs. All four fail both
  `sustain_duration` and `exact_rc_artifact`. Runs 5/6 record 90.17/90.43 seconds;
  the two earlier packs omit observed `sustain_seconds`. No historical pack
  was modified or promoted to fresh evidence.
- The executed production-middleware tests reproduce independent allowances:
  replica 1 gives `[200, 200, 429]`, then replica 2 gives `[200, 200, 429]` to
  the same identity, for authenticated and unauthenticated requests
  (`tests/test_soak_promotion_gates.py:480-486`). These are ASGI middleware
  tests, not a live production-topology soak.

## Acceptance disposition

| # | Acceptance | Fresh evidence / disposition |
|---|---|---|
| 1 | Representative RC profile | PARTIAL: profile exists; `run_soak.py:1276-1289` drives one-key health/task/metrics mix, not user/Workspace, Graph fan-out, successful tools/models, Design/Canvas or Goal traffic. Complete representative coverage UNVERIFIED. |
| 2 | Two application replicas | Compose source declares two replicas; boot-contract tests pass. Live exact-RC multi-replica traffic UNVERIFIED in this round. |
| 3 | Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: four historical packs fail duration; no new load run. |
| 4 | No duplicate physical work / Goal reconciliation | UNVERIFIED: `run_soak.py:947-978` cancels the admission-only schedule probe Run without execution. Receipt/admission uniqueness is not physical Attempt fencing. |
| 5 | Security/degraded/non-bypass | Non-bypass NOT MET by the executed independent-allowance regression; production limiter explicitly documents N-times aggregate limits (`rate_limit.py:25-30`). nginx degraded-response policy tests pass, not a concurrent security soak. |
| 6 | Full telemetry and thresholds | UNVERIFIED: `run_soak.py:1311-1325` measures driver loop lag, not application loop lag; process-group sampler tests pass but are not long-window cgroup/worker/queue/lock evidence. |
| 7 | Active-work kill/restart/drain/fencing/recovery | UNVERIFIED: historical process exit/rejoin cannot establish physical-work recovery; no new kill/restart performed. |
| 8 | At least four hours on exact RC/config | UNVERIFIED / BLOCKED: current driver always rejects its host-process artifact (`run_soak.py:635-645`); no immutable RC image/config supplied or executed. |
| 9 | Findings classified before promotion | Local F1–F12 classifications remain in `m3a-soak-evidence.md`; no external filing verified or performed (GitHub mutations prohibited). |
| 10 | Machine/human evidence tied to exact hashes | Historical JSON hash fields and human report exist; qualifying exact-RC hash-tied soak evidence UNVERIFIED. |

## Handoff

**BLOCKED, not integration approval.** No scanner repair is justified: the
requested exact-identity gate is already green. This round changes only this
validation report, preserving all prior fixes and evidence. It does not claim to
resolve the previous substantive soak block by rerunning unit tests.

Next action is to select and freeze the promotable image/configuration, resolve
the cluster rate-limit acceptance mismatch, implement the production-topology
workloads/telemetry and physical-attempt recovery oracle, then run at least
14,400 seconds against that unchanged artifact. Another host-uvicorn shakedown
cannot satisfy acceptance. No code/config changes were made in this round.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation command failures; blocked 1. Five PG tests remain skipped.
No GitHub mutations, scheduler changes, ledger changes, or discarded work.
`git diff --check` passed before staging. This report is committed locally;
no runtime/configuration artifact or historical evidence file was changed.

# Issue #860 — e27f4f67 repair validation

## Frozen scope and initial evidence

- Assigned issue: #860 only; writer on `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `b1d362ad0bd9cff81c2ca6c60098f595a29d9232`; resolved base:
  `cfb6c3b647145dfcd3ad9b7a1c38f4713d949103`. Initial worktree was clean.
- Process only the supplied issue snapshot and its exact-debt-ledger repair.
  Inspection scope: repository instructions, applicable ADRs, production
  Compose/rate-limit/task/learning-store paths, existing soak driver/evidence,
  adjacent regression tests, gate scripts and their CI arguments.
- Planned edit scope: this validation/handoff record; amend
  `quality/vulture-baseline.json` or production code only if the prescribed
  scanner identifies an actual defect. No historical evidence rewriting,
  authorization changes, external filing or GitHub mutation.
- The supplied job directory contains no `check-*.log` files in its initial
  listing. Driver checks are unavailable, not presumed green. The previous
  result artifact exists and reports BLOCKED; its claims are not fresh proof.
- Executed exact scan:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1342 findings / 1342 reviewed identities, zero unclassified and zero
  never-allowlist findings. No ledger amendment is justified by this scan.
- Ambiguity: the repair brief requests ledger amendment but supplies no failing
  identity. Proceed with the executed clean scanner result, not guessed debt.
  The prior block concerns release-soak acceptance, not a merge conflict.

## Executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2857 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **80 passed, 5 skipped**. PostgreSQL legs require `MAISTRO_TEST_PG_DSN`;
  skipped tests are not live-database proof. Executed tests include real
  production middleware's independent replica allowances, actual task router
  backpressure/retry, fail-closed promotion CLI, and live uv-child sampling.
- Vulture exact-debt gate: PASS as recorded above; its arguments match
  `.github/workflows/vulture-ratchet.yml:82-86`.
- `uv run python scripts/check-ratchet-provenance.py`: PASS (47 quality JSON
  consumers checked, delegated gates passed).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Inline `uv run python` imported the actual soak driver, loaded unchanged
  `evidence/m3a-round6-shakedown.json`, and asserted its failed promotion
  checks are exactly `['sustain_duration', 'exact_rc_artifact']`: PASS.
  Observed 90.43 seconds versus 14400 required; the current artifact check
  returns `ok=false`, `topology=host-uvicorn-preflight`.
- `git diff --check`: PASS.

## Inspection checkpoint

- The prior incorrect shared-limiter-store assertion is already corrected in
  `m3a-soak-evidence.md:171`. The current text states process-local enforcement
  and increased aggregate allowance on replica selection. No cosmetic repair
  or duplicate test is needed.
- `deploy/docker-compose.prod.yml` defines two application services, Redis,
  PostgreSQL primary/replica and shared files, with an external model gateway
  required. The host-process, provider-less shakedown does not execute it.
- The existing learning-schema fence test asserts transaction/SQL ordering with
  a fake connection; it does not prove concurrent live database startup.
- Accepted ADR-081626-f383 requires canonical Attempt fencing; admission
  uniqueness and process exit/rejoin are not proof of physical-work uniqueness.
  ADR-081 deployment guidance is Proposed, not an accepted acceptance waiver.
- The current profile explicitly identifies its driver as a host-process
  preflight that cannot certify the exact production artifact, even at four
  hours. No new soak is claimed.
- Accepted ADR-085 specifies principal-keyed limits but does not establish
  cluster-shared state. Accepted ADR-082426-82c7 specifies occurrence-keyed Run
  admission, not physical-effect uniqueness. No competing scheduler, store,
  authorization path or execution authority is introduced; retain
  Goal → Graph → Run → NodeRun → Attempt. These ADRs do not waive #860's
  replica-selection requirement.

## Acceptance disposition — BLOCKED

| Criterion | Evidence and remaining gap |
|---|---|
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md` defines a preflight mix but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal-worker workloads. |
| At least two application replicas | Compose declares two services; historical preflight used two host processes. **UNVERIFIED for the exact RC**; no live production-topology run performed in this round. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks, shutdown | **UNVERIFIED**: executed evaluator rejects the 90.43-second shakedown; historical wrapper-only RSS/FD observations are invalid as application evidence. |
| Exactly-once/fenced operations avoid duplicate physical work | **UNVERIFIED**: `run_soak.py:947-974` cancels the admitted schedule probe Run without execution. Admission identity and terminal Run counts cannot prove physical-work uniqueness or Goal reconciliation. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | **NOT MET** for replica-selection non-bypass: executed production-middleware tests return independent `[200, 200, 429]` allowances for the same identity on both replicas. Full concurrent RC auth/degraded proof remains **UNVERIFIED**. |
| Required metrics with explicit thresholds | **UNVERIFIED**: current profile lists PG sessions/locks, probe latency, Run depth and process-group samples. Driver-loop lag is not application-loop latency; complete worker counts and saturation/reclaim/error thresholds remain gaps. The live child-sampling regression passes, not a soak. |
| Active-work kill/restart, drain/fencing/recovery without loss/duplication | **UNVERIFIED**: historical process exit/rejoin does not correlate physical Attempt effects across recovery. |
| Long soak of exact RC artifact/configuration | **NOT MET**: executed driver rejects both duration and artifact. The assignment does not select immutable RC image digests/configuration; this runner cannot certify Compose even with a longer duration. |
| Findings filed/reclassified to earliest broken invariant | Local F1–F12 classification records inspected. External filing **UNVERIFIED**, and prohibited in this lane. |
| Machine/human evidence tied to exact hashes | Historical JSON/Markdown pairs exist; **UNVERIFIED for the exact RC to promote**. No new image/config-bound evidence produced. |

## Handoff and change scope

Only this validation record changes. No demonstrated unbanked identity remains;
therefore no ledger amendment, runtime patch or speculative scanner fix was made.
No tests were added or removed; inventory delta is zero, so no new inventory note
is needed. Historical evidence and all inherited work are preserved.

The previous BLOCKED state is not resolved by green CI gates. Next work requires
selection of the exact immutable RC image/config/provider topology, completing
representative workload and physical-effect/telemetry oracles, resolving the
replica-selection enforcement mismatch, and running that artifact for at least
four hours with active-work restart/fencing/recovery evidence. Any subsequent
code/runtime-config change requires a new soak. Do not substitute another host
emulator shakedown or relabel old evidence.

Progress: checked 1, done 0, skipped 0, errors 0; one blocked handoff. Commit this
record locally; no push, merge, PR, issue mutation or destructive Git operation.

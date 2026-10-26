# #860 repair checkpoint — job 00d20301

## Frozen scope

Only issue #860, branch `auto-860`, starting clean at
`6b3c755ca26270c30761de806de2cf0a13c452e5`; supplied develop base
`d7f7f6f81a83d99ed4598ed449a4d256c75d51a0` resolves locally.
This round's intended change is this validation/handoff record only unless the
required scan reveals an actual repair. No other issue, GitHub mutation or
runtime authority change is in scope.

## Executed initial checks

- Required vulture scan (`uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) passed:
  1359 reviewed identities, 1359 findings, zero unclassified/never-allowlist.
  No unbanked identity exists to repair or amend in the ledger.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` failed (exit 1):
  cannot connect to the Docker daemon. A new live Compose soak is blocked.
- The supplied job directory contained no `check-*.log` files when inspected.
  Prior job results are historical claims, not fresh validation.
- Current profile/evidence already retract the historical cluster-wide limiter
  claim and reject host-process/short-duration evidence for promotion. The
  supplied prior finding about that misleading prose is already repaired.

Assumption: this is a writer CI-repair round, but a passing debt gate does not
justify cosmetic ledger edits. Preserve all historical evidence; do not launch
another emulator run and label it a production soak.

## Focused validation

All commands ran in the assigned worktree with long timeouts:

| Command | Observed result |
|---|---|
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 102 passed, 5 skipped, 3.25 s |
| `uv run pytest packages/maistro-server/tests -x -q` | 476 passed, 9 skipped, 22 deprecation warnings, 25.59 s |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 2770 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | All 14 suites match |

Also executed an inline `uv run python` check importing
`scripts/soak/run_soak.py` and calling `failed_promotion_checks` against the
four fixed historical evidence files below. Asserted that each failure list
contains both `sustain_duration` and `exact_rc_artifact`; all assertions passed:

- `evidence/m3a-soak-evidence.json`: both rejected (plus other gates).
- `evidence/m3a-repair-validation.json`: both rejected (plus other gates).
- `evidence/m3a-round5-final.json`: 90.17 seconds, both rejected, H3 also fails.
- `evidence/m3a-round6-shakedown.json`: 90.43 seconds, both rejected.

The executed middleware regression
`test_replica_selection_has_an_independent_production_allowance` checks both
credential classes against real `RateLimitMiddleware` instances: each replica
returns `[200, 200, 429]` for the same identity. This is a reproduction of
independent allowances, not live deployment evidence. Skips are not credited
as acceptance proof. No tests were added, so no inventory delta is required.

## Architecture reconciliation

Read repository instructions, accepted ADR-081426-1f7c (physical identity is
Attempt), ADR-081626-f383 (canonical store owns fencing), ADR-082426-82c7
(occurrence uniqueness on Run), and ADR-085 (per-principal limiting), alongside
Proposed ADR-081 and `deploy/docker-compose.prod.yml`.

Admission uniqueness does not prove physical execution uniqueness. The lease
ADR explicitly leaves expiry takeover outside its contract; this lane must not
invent reclaim authority to satisfy a soak checkbox. ADR-085 does not turn
process-local middleware into a coordinated cluster budget. Proposed ADR-081
cannot waive #860's exact-artifact requirement. No production behavior or
canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` authority was changed.

## Acceptance disposition

| #860 criterion | Current evidence / remaining requirement |
|---|---|
| Representative profile | PARTIAL: `m3a-load-profile.md` defines traffic and thresholds, but explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained Goal/background traffic. Representative RC scope UNVERIFIED. |
| At least two application replicas | Compose defines two server replicas; no live RC replicas exercised this round. UNVERIFIED. |
| Sustained saturation, queues, reclaim, retry, leaks, shutdown | Historical short preflights rejected by current gates; long-window production behavior UNVERIFIED. |
| No duplicate physical work / Goal reconciliation | Existing admission probes are not physical Attempt observations. UNVERIFIED. |
| Rate/security/degraded non-bypass | Same-principal cluster allowance disproven by the executed middleware regression; full concurrent RC security/degraded behavior UNVERIFIED. |
| Complete telemetry with thresholds | PARTIAL profile only; application event-loop latency and complete production observations remain UNVERIFIED. Driver-loop lag is not application-loop lag. |
| Active-work kill/restart with fencing/recovery | No live RC execution; process rejoin is not physical-work fencing. UNVERIFIED. |
| Long-running exact RC artifact/config soak | NOT MET: all four historical packs rejected; Docker daemon unavailable. Host preflight always fails artifact gate at `scripts/soak/run_soak.py:635-646`. |
| Findings filed/reclassified | Local F1–F12 records exist in `m3a-soak-evidence.md`; no new runtime finding this round. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence bound to exact hashes | Historical packs remain unchanged; no new hash-bound promotion evidence. UNVERIFIED. |

## Handoff

Verdict: **BLOCKED**, not integration approval. No evidence-backed code or
ledger repair was available from the assigned CI scan. Only this handoff record
changed. The previous blocker could not be resolved: Docker remains unavailable,
and restoring it alone would not close profile, limiter and exact-RC-runner gaps.

Next: provide the selected immutable RC image/configuration and reachable
production soak environment; resolve the replica-budget acceptance mismatch
through the canonical security path; complete representative workloads and
physical Attempt/Goal/telemetry observations; then execute at least 14400 seconds
on that exact artifact and classify failures before promotion. Do not launch
another four-hour host emulator as a substitute. Any code/runtime-config repair
requires a fresh soak.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC environment and acceptance blockers}`.
The error is the Docker environment check, not a claimed product regression.

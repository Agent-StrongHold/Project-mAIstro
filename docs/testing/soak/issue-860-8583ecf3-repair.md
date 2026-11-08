# Issue #860 — repair checkpoint (8583ecf3)

## Frozen scope

- Sole item: issue #860, branch `auto-860` in the assigned worktree.
- Starting HEAD: `13747aee0163dfb07ed4d3fb8fa8f9ef0c25f099` (verified).
- Develop base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f` (verified).
- Starting worktree clean; no salvage needed. No merge conflict exists.
- Evidence: supplied `dispatch-context.json`, preceding result
  `46d6f3dde4b34107be90deaa4c61e804/result.json`, current soak runner,
  `tests/test_soak_promotion_gates.py`, load profile, round6 evidence,
  production rate-limit middleware, adjacent task/persistence tests and
  relevant architecture/quality instructions.
- Planned write: this checkpoint only unless the exact requested vulture scan
  identifies an actual defect. The explicit CI-repair exception permits
  `quality/vulture-baseline.json` changes only for reviewed scan findings.
- No driver `check-*.log` files exist in the supplied job directory.
- Ambiguity: the generic verifier/writer prompt describes both roles. Proceed
  as assigned repair writer; validate, preserve evidence, commit locally.

## Initial result

Prior result reports BLOCKED, not an unresolved merge. Its claims are inputs
for verification, not acceptance proof. No GitHub changes, gate weakening,
authorization changes, or new execution authority will be introduced.

The exact requested vulture scan passed: 1336 reviewed identities matched
1336 findings, with zero unclassified and zero never-allowlist findings. No
unbanked identity or stale ledger entry was reported. No ledger change is
justified; the CI-repair subtask is complete without a source change.

The supplied issue has ten acceptance criteria. The current runner explicitly
rejects its host-uvicorn topology as exact-RC evidence, and the production
middleware deliberately creates independent process-local limiters. Focused
validation checked those paths rather than treating prior claims as proof.

## Architecture reconciliation

Read accepted ADR-085, ADR-081626-f383 and ADR-082426-82c7, plus the
quality-gate instructions. ADR-085 specifies principal identity, but does not
establish a distributed request budget. The middleware documents process-local
allowances; that is not proof of issue #860's replica-selection non-bypass.
ADR-081 is Proposed, not an accepted waiver for deployment evidence.
Occurrence admission uniqueness and Attempt physical-work fencing are separate
contracts. Canonical Run-store ownership remains unchanged; no parallel
scheduler, Goal store, event authority, or authorization path is introduced.

## Fresh validation

All commands ran in the assigned worktree, with 600-second validation timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1336/1336 identities. Matches `.github/workflows/vulture-ratchet.yml:82-85`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3003 files already formatted.
- `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`: PASS. Prior EOF whitespace findings are not reproduced.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 61 tests in 2.38 seconds.
- `uv run python` importing the current runner and evaluating retained round6
  evidence: PASS as a rejection check, asserting exactly
  `['sustain_duration', 'exact_rc_artifact']`. The current artifact check returns
  `ok=false`, `topology=host-uvicorn-preflight`.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

The focused tests include real production middleware instances, router/spine
admission backpressure, real child-process resource sampling and fail-closed
CLI artifact checks. Production wiring is reachable at
`packages/maistro-server/src/maistro_server/main.py:628,715,734`.
ASGI instances and configuration assertions are not deployed multi-replica soak
proof. No fresh soak or full-package test run is claimed.

## Acceptance audit

| Issue criterion | Evidence / disposition |
|---|---|
| Representative RC users/Workspaces and workload mix | UNVERIFIED. `m3a-load-profile.md:152-165` documents absent fan-out, successful tool/model work, Canvas, Goal reconciliation and worker coverage. |
| At least two deployed replicas | UNVERIFIED for the RC. `m3a-load-profile.md:19-24` identifies host processes, not the promoted Compose artifact. |
| Sustained saturation, reclaim, retries, leaks and shutdown observations | UNVERIFIED. Round6 evidence lines 163-165,221-224 records only 90.43 seconds against 14400 required. No new production time series exists from this attempt. |
| Admission, Goal reconciliation and fenced physical-work uniqueness | UNVERIFIED. Admission probe regression tests pass, but the schedule probe cancels its queued Run without physical execution (`m3a-load-profile.md:197-200`). |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance. Passing `tests/test_soak_promotion_gates.py:439-488` demonstrates `[200,200,429]` independently on both middleware instances for the same identity. `api/rate_limit.py:25-30,72-76` explains the production process-local state. Full security/degraded behavior under production concurrency remains UNVERIFIED. |
| Complete production telemetry and thresholds | UNVERIFIED. `m3a-load-profile.md:157-165` distinguishes driver lag/process-group snapshots from application-loop latency, worker counts and sustained pool/reclaim observations. Sampler tests do not supply a production time series. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Historical process exit/rejoin does not prove stale-worker rejection or absence of duplicated/lost physical work. |
| Long-running exact-RC soak, repeated after runtime changes | NOT MET. `scripts/soak/run_soak.py:635-646` rejects the runner's topology. Executed re-evaluation rejects both artifact and duration. Running this emulator longer cannot close the artifact gap. |
| Findings filed/reclassified to earliest broken invariant | Historical findings exist; completeness UNVERIFIED without the required run. No GitHub mutation was performed. |
| Human/machine evidence bound to exact artifact hashes | UNVERIFIED for this RC. Round6 evidence line 71 names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head; no promoted application-image identity is supplied. This checkpoint is validation evidence only. |

## Disposition

**BLOCKED.** The reported CI debt is not reproduced. No source or ledger repair
is warranted by the observed scan; no test additions or inventory delta were
made. Only this report changed. Existing code and evidence were preserved.
The preceding worker-attention blocker remains an acceptance/deployment gap,
not an unresolved merge conflict.

Next: select the exact production RC/configuration, implement its missing
representative workloads and telemetry through existing execution authorities,
resolve the replica-budget contract, then run and publish a new >=4-hour
multi-replica soak including active physical work and failure injection.
A repeat of this passing vulture scan cannot satisfy those prerequisites.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; command errors 0.
The local report commit is a handoff checkpoint, not integration approval.

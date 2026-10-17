# Issue #860 repair checkpoint — 5f6c02f1

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `ff0384ba79431e5373657816f82fe7b1badfedb2`.
- Supplied base: `35f2e0158a9138e592b56ed84bd08aa2e04c92a4`.
- Initial worktree clean; no salvage required.
- Repair targets: exact vulture gate and only identities it actually reports;
  existing soak runner, promotion tests, load profile, historical round6 evidence,
  server rate middleware, adjacent tests, relevant governance/CI instructions.
- Potential writes: this report; reviewed vulture identities/ledger only if the
  executed gate provides evidence for a repair. No runtime or policy expansion.
- Job directory listing contains no `check-*.log`; driver results unavailable.
- Prior result was read, but its verification claims are not reused as results.

## Interpretation

This is a writer/CI-repair round, not a verifier-only round. The explicit ledger
exception applies only to proven vulture debt. A missing immutable RC artifact
and incomplete production soak cannot be repaired by relabeling host preflight
as release evidence. Canonical execution ownership must remain unchanged.

## Progress

Exact assigned vulture command passed (exit 0): 1,339 reviewed identities,
1,339 findings, zero unclassified and zero never-allowlist findings; ratchet
base resolved to the supplied `35f2e0158a91`. No unbanked identities exist to
repair, so no ledger amendment is justified.

Read repository instructions and ADR-081 (Proposed), ADR-085 (Accepted),
ADR-081626-f383 (Accepted), and ADR-083026-a91e (Accepted). Reconciliation:
request limits being per-principal does not demonstrate a shared replica budget;
admission uniqueness does not establish physical Attempt fencing. Unmeasured
production telemetry remains unverified, never zero or passing.

## Executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2,911 files).
- `git diff --check 35f2e0158a9138e592b56ed84bd08aa2e04c92a4...HEAD`:
  PASS; prior whitespace failure is not reproduced at this head.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 61 tests in 3.72s. Includes actual production rate middleware instantiated
  twice: same identity receives `[200, 200, 429]` from each replica independently
  (`tests/test_soak_promotion_gates.py:439-488`). These ASGI tests are not a soak.
- Exact vulture invocation matches `.github/workflows/vulture-ratchet.yml:82-85`.

- `uv run python scripts/check-ratchet-provenance.py`: PASS (49 quality
  consumers; delegated checks pass).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run python scripts/check-suite-inventory.py`: PASS (14 suites; 25,711
  unique test identities). No tests added, so no inventory delta required.
- `uv run python -` loaded `scripts/soak/run_soak.py` with `runpy.run_path`,
  read `evidence/m3a-round6-shakedown.json`, and asserted
  `failed_promotion_checks(evidence) == ['sustain_duration', 'exact_rc_artifact']`:
  PASS. Observed duration 90.43 seconds; evidence head
  `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head. Current
  `preflight_artifact_check()` returns `ok: false`, `host-uvicorn-preflight`.

All executable validations used `uv run` and 1,200-second command timeouts.
No fresh soak was run: the existing runner explicitly cannot sign exact-RC
production evidence, regardless of duration. No immutable promotion artifact
was identified in the assignment.

## Acceptance evidence and remaining blockers

| #860 acceptance | Current executed evidence / disposition |
|---|---|
| Representative users/Workspaces and request mix | PARTIAL: profile exists; `m3a-load-profile.md:152-160` explicitly lacks users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and background reconciliation coverage. Representative RC workload UNVERIFIED. |
| At least two production replicas | UNVERIFIED: runner is host preflight (`run_soak.py:635-647`); ASGI middleware pair tests do not prove production Compose behavior. |
| Sustained saturation, queue, reclaim, backoff and leak observation | UNVERIFIED: current evaluator rejects the historical 90.43-second run against the 14,400-second requirement (`m3a-round6-shakedown.json:221-224`). |
| Exactly-once/fenced physical work, schedule and Goal reconciliation | UNVERIFIED: tests exercise admission evidence semantics, not sustained physical work; profile `:197-200` explicitly distinguishes the single cancelled schedule probe from Goal reconciliation and Attempt fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared budget: executed production middleware tests `test_soak_promotion_gates.py:439-488` reproduce fresh allowance for the same identity on replica 2; local enforcement tests pass. Successful backpressure tests do not establish full concurrent security/degraded acceptance. |
| PostgreSQL, loop, worker, RSS/fd, queue/error telemetry and thresholds | PARTIAL: real child-memory/fd sampler regression test passes; required production application-loop/worker and long-window measurements remain UNVERIFIED (`m3a-load-profile.md:155-163`). |
| Kill/restart during work with drain/fencing/recovery | UNVERIFIED: historical exit/rejoin counters do not prove absence of lost or duplicated physical work; no current production kill/recovery execution. |
| Long soak of exact promoted RC/config | NOT MET: historical evidence fails both duration and artifact checks; current runner always fails exact-RC check. |
| Findings filed/reclassified to earliest broken milestone | PARTIAL: local `BACKLOG.md:267-279` records the unresolved cluster-budget finding and backlog gate passes. External filing/reclassification and complete milestone disposition UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | PARTIAL: historical JSON/profile retained, but current qualifying RC evidence UNVERIFIED; historical head differs and lacks promoted application image identity. |

Also read accepted ADR-082526-b36a: lease renewal/reclaim belongs to the
canonical Attempt lifecycle, not a soak-specific scheduler or recovery authority.
Nothing in this round changes `Goal -> Graph -> Run -> NodeRun -> Attempt`.

## Handoff

Verdict: **BLOCKED**, not promotion approval. The assigned exact-debt-ledger
repair is checked and needs no code/ledger edit. Existing runtime and historical
evidence are preserved. The only changed file is this validation report.

Next: designate immutable RC image/configuration, complete representative
production workload/telemetry coverage, resolve the recorded cluster-budget
policy gap through its canonical implementation seam, then execute the full
production soak and restart/fencing probes on that unchanged artifact. Do not
re-run this CI-repair lane expecting a clean vulture scan to satisfy load evidence.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
validation errors 0; blocked 1. Commit this report locally; no push or GitHub action.

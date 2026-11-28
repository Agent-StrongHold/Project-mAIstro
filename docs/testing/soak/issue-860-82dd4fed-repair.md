# Issue #860 repair — job 82dd4fed

## Frozen scope and initial evidence

- Process only assigned issue #860, branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
- Verified starting HEAD `058267810fbaeaca7ea2a798d3086a4aee03f1c2`; supplied base `680329c960cd722034bd0053be745f3de138ba8d` resolves locally.
- Starting worktree clean: no incoming edits to salvage. Preserve all existing evidence.
- Job directory snapshot contains no `check-*.log` files. Prior result `186977cdd7234dfe8b76df4e38f794b5/result.json` reports BLOCKED, not acceptance proof.
- Inspection scope: repository instructions, canonical execution/fencing/recurrence and rate/telemetry ADRs; existing soak runner, profile, historical round6 evidence and promotion tests; production Compose/rate middleware; adjacent task-backpressure and PostgreSQL learnings code/tests; exact vulture gate and associated CI/provenance.
- Repair scope: only actual issue-860 failures or scanner-reported dead identities, reviewed retained ledger identities if any, inventory note if tests change, and this handoff. No remote enumeration or mutations.
- Ambiguity resolved: this is a writer CI-repair assignment, not the read-only verifier. No exact immutable RC image/configuration is supplied; do not equate host preflight with production acceptance.

## Results so far

- Exact requested command `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1342 reviewed identities / 1342 findings, zero unclassified or never-allowlist findings. Checker reports base `928993dda1c9`, candidate `058267810fba`. No evidence justifies changing `quality/vulture-baseline.json`.
- Read accepted ADR-081626-f383 and ADR-085: fencing stays with the canonical Run store; limits are per principal. No competing authority or scope exemption will be introduced.
- Read load profile: explicitly host preflight, not promoted Compose; single API key and missing Graph/tool/Canvas/Goal coverage. Four-hour minimum alone cannot qualify this runner.

- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (2891 files).
- `git diff --check 680329c960cd722034bd0053be745f3de138ba8d...HEAD` and `git diff --check`: PASS. Prior EOF-whitespace findings do not reproduce.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 88 passed, 5 skipped in 3.36s. PostgreSQL integration cases skipped; no database soak claim.
- `uv run python scripts/check-deployment-claims.py`: PASS. `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- Executed production middleware regression `test_replica_selection_has_an_independent_production_allowance` for both authenticated and pre-auth identities: each replica returns `[200, 200, 429]` independently for the same identity. This falsifies a shared allowance, not local enforcement. Do not reinterpret six passing burst probes as replica-selection non-bypass.
- Accepted ADR-082426-82c7 binds occurrence uniqueness to canonical Run persistence; ADR-082526-b36a requires heartbeat/expiry/reclaim semantics, not restart-implies-death. ADR-083026-a91e disallows invented zero measurements. No acceptance waiver follows from these ADRs, and no competing scheduler, Goal store or authorization path is warranted.

- `uv run pytest packages/maistro-server/tests -x -q`: 494 passed, 8 skipped, 22 deprecation warnings in 47.03s.
- `uv run python scripts/check-ratchet-provenance.py`: PASS (49 consumers plus delegated gates); `uv run python scripts/check-shipped-surface-truth.py`: PASS. Exact vulture arguments match `.github/workflows/vulture-ratchet.yml:82-85` and `quality.yml:963-966`.
- Fresh inline `uv run python` imported the current runner, evaluated historical round6 JSON and asserted failed checks are exactly `sustain_duration` and `exact_rc_artifact`. Also asserted the current artifact check is false. Historical duration is 90.43 seconds, required 14400; evidence names commit `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this assigned head. This evaluates an old record, not newly observed production traffic.

## Acceptance audit

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | PARTIAL: profile defines request mix/thresholds but expressly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads (`m3a-load-profile.md:152-165`). Complete representative coverage UNVERIFIED. |
| Two application replicas | UNVERIFIED for exact production artifact: Compose declares two; no production Compose load run executed. Two ASGI instances are not deployment proof. |
| Sustained saturation, queue growth, reclaim, backoff, leaks and shutdown | UNVERIFIED. Historical 90.43-second sample fails duration gate; focused tests are not a sustained measurement. |
| Exactly-once/fenced physical work, schedules and Goal reconciliation | UNVERIFIED. Historical schedule race admits then cancels one Run; no proof of physical Attempt execution or sustained Goal reconciliation (`m3a-load-profile.md:197-200`). |
| Concurrent rate/security/degraded non-bypass by replica selection | NOT MET for a shared per-principal allowance: executed middleware tests demonstrate a fresh allowance on replica 2 (`tests/test_soak_promotion_gates.py:439-488`). Local backpressure regression passes; full production concurrency/security behavior UNVERIFIED. |
| Required telemetry and thresholds | PARTIAL: process-group sampler tests pass with real child RSS/fd growth; application-loop/worker telemetry and qualifying PostgreSQL/pool/queue/error series UNVERIFIED. Driver loop lag is not application loop lag. |
| Kill/restart with drain/fencing/recovery | UNVERIFIED: no active-work production replica killed/restarted this round. Historical rejoin/terminal counts do not prove physical-effect uniqueness. |
| Long exact-RC soak | NOT MET: `scripts/soak/run_soak.py:635-647` explicitly disqualifies host preflight. No immutable RC image/configuration selected or qualifying four-hour run performed. |
| Findings filed/reclassified before promotion | PARTIAL: local backlog gate passes; completeness and external filing/reclassification UNVERIFIED. GitHub mutation prohibited. |
| Hash-tied machine/human evidence | PARTIAL: historical evidence preserved; current qualifying image/package/commit/config evidence UNVERIFIED. This handoff is validation evidence only. |

## Disposition

**BLOCKED.** The exact-debt-ledger and whitespace failures do not reproduce; no speculative source or ledger amendment is justified. Only `docs/testing/soak/issue-860-82dd4fed-repair.md` changed this round. No tests changed, so no inventory delta/note is required. Existing source, tests, runtime configuration and historical evidence remain intact. Gates were not weakened.

Next: select an immutable RC image/configuration; implement a production-topology workload covering the missing surfaces with physical-effect/fencing and application telemetry; resolve the replica-selection budget gap through existing canonical security seams; then run the required long soak after the final runtime change. Never substitute another host shakedown or static gate pass for these acceptance criteria. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and accepted ADR ownership throughout.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "issue #860 blocked on qualifying RC soak prerequisites"}`. Local validation complete, acceptance incomplete. Commit this handoff locally only; no push or GitHub mutations.

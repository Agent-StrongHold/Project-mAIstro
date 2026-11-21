# Issue #860 — bounded repair b8fa53ff

## Frozen scope

- Issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `9f38570197acf981da0ffb5114c192807b66c64e` (verified); clean.
- Base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Process only the dispatched vulture failure and existing soak acceptance evidence.
- Candidate edit surfaces: this report; `quality/vulture-baseline.json` only if
  the mandated scan identifies reviewed retained debt. No speculative runtime edits.
- Read surfaces: repository instructions, relevant execution/release ADRs,
  `scripts/check-vulture-baseline.py`, existing soak runner/profile/tests,
  the supplied dispatch snapshot and prior failure/result artifacts.
- Current job directory has no driver `check-*.log` files. Prior result reports
  BLOCKED; its claims require fresh verification, not inheritance.
- Assumption: CI-repair permission authorizes ledger reconciliation, not weakening
  authorization gates or claiming a host preflight is an exact-RC production soak.

## Progress

- Mandated vulture command passed: 1,322 reviewed identities, 1,322 findings,
  zero unclassified/never-allowlist findings. No ledger amendment is justified.
- Referenced prior `check-3.log` is a schema-fence test failure (24 statements
  versus 21 expected), not a vulture failure. Current test already explicitly
  includes the three Gauntlet audit columns; fresh focused tests passed.
- Accepted ADR-081426-1f7c keeps physical identity at Attempt; ADR-081626-f383
  reserves reclaim authority rather than assuming timeout-based takeover.
  ADR-073126-c4e1 requires soaking the RC artifacts promoted unchanged. A local
  preflight cannot satisfy that contract; no alternate authority is introduced.

## Executed validation

All commands ran in the assigned worktree with 1,200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,322 findings exactly banked; arguments match `.github/workflows/quality.yml:1079` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,301 files already formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` | 109 passed, 6 skipped; no live production soak implied |

No production code, tests, inventory, baseline, or grants changed. Test inventory
has zero delta; no new tests are warranted for this report-only checkpoint.
The existing tests exercise the actual limiter middleware, CLI rejection of
otherwise-passing four-hour preflight evidence, process-group resource sampling,
and the schema fence's independently enumerated DDL body.

## Acceptance audit

| #860 criterion | Evidence and disposition |
| --- | --- |
| 1. Representative profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:152` lists missing user/Workspace population, fan-out, successful model/tool calls and Design/Canvas/Goal workloads. |
| 2. Production replicas | UNVERIFIED. `scripts/soak/run_soak.py:744` identifies the implemented topology as host-uvicorn preflight, not the promoted Compose deployment. |
| 3. Sustained load | UNVERIFIED. No long-running load executed in this repair; unit/regression tests cannot establish saturation, reclaim, retry or leaks. |
| 4. Physical-work uniqueness | UNVERIFIED. `scripts/soak/run_soak.py:1067` explicitly says the schedule race Run never executes; admission cardinality is not physical-work uniqueness. |
| 5. Replica-independent security/degraded enforcement | UNVERIFIED; counterevidence reproduced. `tests/test_soak_promotion_gates.py:439` passes for both identity classes because each middleware instance independently returns 200,200,429 for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:31` documents this process-local contract. No unapproved distributed limiter added. |
| 6. Production telemetry and thresholds | UNVERIFIED. `scripts/soak/run_soak.py:1433` samples driver-loop lag, not application-loop latency. Process-group sampler tests passed, but no new production telemetry collected. |
| 7. Kill/restart active-work recovery | UNVERIFIED. `scripts/soak/run_soak.py:1451` signals/restarts a process group and `:1540` counts terminal Runs; neither proves active physical-work fencing or absence of duplicate side effects. |
| 8. Exact-RC long soak | UNVERIFIED. Executed `test_four_hour_preflight_cannot_pass_cli` rejects missing/null/preflight artifact evidence. Runner emits `exact_rc_artifact.ok=false`; no designated RC soak performed. |
| 9. Findings disposition | UNVERIFIED. Local blockers documented here; complete earliest-invariant disposition not established. No GitHub mutations performed. |
| 10. Hash-bound machine/human evidence | UNVERIFIED at production grade. This report records the checked source head and commands, not exact-RC image/configuration/load evidence. |

## Handoff

Verdict: **BLOCKED**, not integration approval. The dispatched deterministic
failure does not reproduce, and the requested vulture reconciliation is already
satisfied. Changing a passing ledger would be speculative. Remaining work needs
an exact-RC production runner/profile and sustained evidence, plus resolution of
physical-work/recovery and replica-budget acceptance gaps through canonical
services. Repeating short preflight runs cannot discharge these requirements.

Progress: checked 1 issue, done 0 (issue acceptance), skipped 0, command errors 0.
Next: provide/design the missing production soak path and RC identity; do not
re-run this unchanged CI-repair lane expecting promotion evidence.


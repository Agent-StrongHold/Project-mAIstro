# Issue #860 — af93736f repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD verified: `79ec66f723de2b1a964c8045bafc89efae900892`.
- Assigned base: `00aafef9b75a1057edc2b03f2d6a71732ec9d880` resolves locally.
- Starting worktree clean; no incoming edits to salvage.
- Review set: repository instructions; canonical execution, fencing, recurrence,
  deployment and rate-limit ADRs; `scripts/soak/run_soak.py`, its adjacent
  `tests/test_soak_promotion_gates.py`; `docs/testing/soak/m3a-load-profile.md`,
  `m3a-soak-evidence.md`, and the four existing evidence JSON packs;
  production rate-limit middleware and its tests; task backpressure and PG
  learning-store tests; CI vulture command and ledger only if actual failures.
- Planned edit scope: this checkpoint; actual evidenced gate repairs only.
- Job directory snapshot contains no `check-*.log`: driver results unavailable,
  not assumed green. Prior result JSON read; its BLOCKED verdict is not reused
  as independently executed acceptance evidence.

## Ambiguity and assumption

This is a writer/CI-repair assignment, not a read-only verifier assignment.
No exact RC image/configuration is supplied in the assignment. Existing host
preflight evidence must not be promoted as an exact-artifact soak. Do not invent
an RC identity or weaken admission requirements to close #860.

## Progress

Snapshot complete. Exact required vulture command executed successfully:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
1342 reviewed identities / 1342 findings; zero unclassified. No ledger amendment
is warranted; the requested scanner failure does not reproduce. Prior H3 prose
is already corrected in the starting tree, so no cosmetic re-repair is needed.
Focused validation executed:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2876 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **80 passed, 5 skipped** (3.76s). All skips explicitly require a migrated
  `MAISTRO_TEST_PG_DSN`; no live PostgreSQL acceptance is inferred.
- CI workflows confirm the executed vulture arguments match the blocking gate.

Architecture reviewed: accepted ADR-081626-f383 assigns fencing to canonical
Attempt persistence; ADR-082826-d9f5 keeps RunStore the sole execution authority;
ADR-082126-f69c makes recurrence produce canonical Runs, not a second scheduler
runtime. ADR-085 requires per-principal rate limiting; it does not waive #860's
replica-selection acceptance. ADR-081 is Proposed, not an accepted waiver.
No change to `Goal -> Graph -> Run -> NodeRun -> Attempt` is proposed.

Production `RateLimitMiddleware` constructs its own `InMemoryRateLimiter` per
instance. Executed tests exercise that real middleware on two ASGI apps: the
same identity receives `[200, 200, 429]` on each replica, authenticated and
unauthenticated. This reproduces independent budgets, not cluster non-bypass.
The HTTP task-backpressure test exercises the real router/queue/canonical spine,
but uses an in-memory store and does not execute physical Attempts. Harness
sampler tests exercise a real uv child; HTTP probe oracle tests use mock
transports. None substitutes for a multi-replica deployed soak.

## Evidence evaluation

Executed the current `failed_promotion_checks` against the frozen four packs,
asserting each fails both `sustain_duration` and `exact_rc_artifact`:

| JSON under `evidence/` | Recorded top-level sustained seconds | Failed gates |
| --- | ---: | --- |
| m3a-soak-evidence.json | absent | rate_limit_enforced, lb_failover_bounded, nonterminal_runs_after_settle, task_admission_availability, sustain_duration, exact_rc_artifact, graceful_drain |
| m3a-round5-final.json | 90.17 | rate_limit_enforced, sustain_duration, exact_rc_artifact |
| m3a-round6-shakedown.json | 90.43 | sustain_duration, exact_rc_artifact |
| m3a-repair-validation.json | absent | exactly_once_task_admission, lb_failover_bounded, nonterminal_runs_after_settle, task_admission_availability, sustain_duration, exact_rc_artifact, graceful_drain |

The evaluation passed those rejection assertions. Also executed
`preflight_artifact_check()` and confirmed `ok` is false. Historical summary
booleans cannot prove today's six-path probes ran. Raw evidence unchanged.
`git diff --check` passed.

## Acceptance disposition

1. **Representative profile: PARTIAL.** Profile and thresholds exist, but
   `m3a-load-profile.md` explicitly lacks multiple users/Workspaces, fan-out,
   successful tools/models, Canvas/Design and sustained Goal/background work.
2. **At least two production replicas: UNVERIFIED.** Host preflight history is
   not execution of the immutable production images/configuration.
3. **Sustained saturation, queues, reclaim, retries and leaks: UNVERIFIED.**
   Executed evaluator rejects the historical durations; no new long soak ran.
4. **Physical-work uniqueness / Goal reconciliation: UNVERIFIED.** Admission
   probes and in-memory regression tests do not prove physical Attempt fencing
   across deployed replicas. Profile admits the scheduled probe is canceled
   before execution and sustained traffic includes no schedules.
5. **Replica-selection non-bypass: NOT MET.** Executed real middleware tests
   reproduce independent allowances. Full deployed security/degradation remains
   UNVERIFIED; six-path overload rejection is not a shared budget.
6. **Complete telemetry and explicit thresholds: UNVERIFIED.** Profile thresholds
   are incomplete for required observations; driver loop lag is not application
   lag. Historical wrapper-only RSS/FD evidence is explicitly invalidated.
7. **Active-work kill/restart, fencing/recovery: UNVERIFIED.** Historical process
   exit/rejoin does not correlate physical Attempts through loss/recovery.
8. **Long exact-RC soak: NOT MET.** All four evaluated packs fail duration and
   artifact checks. No immutable RC image/configuration supplied for this round;
   extending the host emulator cannot satisfy artifact equivalence.
9. **Findings filed/reclassified: PARTIAL.** Local F11/F12 records classify the
   earliest broken invariant as M3-A evidence validity. External filing remains
   UNVERIFIED; no GitHub mutations are permitted or performed.
10. **Hash-bound machine/human exact-RC evidence: UNVERIFIED.** Historical packs
    exist in both formats, but none is promotion evidence for this HEAD/config.

## Final handoff

**BLOCKED.** The requested CI failure does not reproduce, and repeated unit/gate
validation cannot replace the missing production-path workload and four-hour
exact-RC soak. Next owner must supply immutable RC images/configuration, resolve
cross-replica rate-budget acceptance, finish representative workload/telemetry,
and execute the actual soak with physical-work recovery correlation. Any runtime
or configuration change requires a new soak. No acceptance waiver is justified.

Only this checkpoint changed in this round. No runtime changes, ledger/grant
edits, test additions, or inventory delta. Existing branch work and raw evidence
are preserved. Local commit required; no push/PR/merge/issue mutation.

Progress: checked 1, done 0, skipped 0, errors 0, blocked 1. Next: provision and
run the exact-RC acceptance exercise; do not repeat a nonexistent ledger repair.

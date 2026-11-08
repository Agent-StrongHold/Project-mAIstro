# Issue #860 repair — job 16a31a98

## Frozen scope

- Issue #860 only; assigned branch `auto-860`, starting HEAD
  `e586df3f7bf9c536e1ff57ca1b286e7615ec3cbf`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean. No conflict or incoming edits to salvage.
- Inspect repository instructions, relevant ADRs, supplied dispatch and prior
  failure evidence, `scripts/soak/`, adjacent soak tests, production rate-limit
  wiring, and CI gate definitions. No GitHub mutations or new issue enumeration.
- Candidate changes limited to this report and evidence-backed repairs in the
  above soak scope or `quality/vulture-baseline.json` as explicitly authorized.
  Test changes, if needed, require an inventory note.
- No `check-*.log` files were present in this job directory at initial inspection.
  Run fresh validation rather than treating earlier reports as proof.
- Ambiguity: this is a writer repair (not the read-only verifier role). Exact RC
  artifact/configuration are not specified by the lane; do not invent them or
  represent host preflight as deployment acceptance.

## Progress

Requested vulture scan executed: exit 0, 1323 reviewed identities / 1323
findings, zero unclassified; provenance base `4aa68edc0b6b`. Log:
`/tmp/860-16a31a98-vulture.log`. No evidence supports a ledger amendment.

The cited historical `98a11313.../check-3.log` is a schema-fence test failure
(24 statements versus 21 expected), not a scanner failure. Fresh
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped; `/tmp/860-16a31a98-pg.log`. Historical failure is
not reproduced; skipped live-DB tests are not deployment evidence.

Fresh focused checks all exit 0 (1200-second command timeouts):

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run ruff check .` | all checks passed | `/tmp/860-16a31a98-ruff.log` |
| `uv run ruff format --check .` | 3270 files formatted | `/tmp/860-16a31a98-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed | `/tmp/860-16a31a98-tests.log` |
| `uv run python scripts/check-suite-inventory.py` | 17 suites match; no duplicate evidence | `/tmp/860-16a31a98-inventory.log` |

No test changes; inventory delta zero. No inventory note is required.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, accepted
ADR-081226-69ee (Graph execution), ADR-081626-f383 (fencing),
ADR-082526-b36a (renewal/reclaim), and ADR-085 (rate policy).
The later renewal/reclaim ADR extends the older lease boundary: the older
ADR's deferral cannot waive reclaim validation. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate scheduler,
execution authority, event store or authorization path is introduced.

- `packages/maistro-server/src/maistro_server/main.py:648` installs the
  production `RateLimitMiddleware`. Its constructor in `api/rate_limit.py:93`
  creates process-local limiter state. Executed
  `tests/test_soak_promotion_gates.py:439` uses that middleware with the same
  client and credential across two ASGI instances: each accepts two requests
  then returns 429. Replica selection increases aggregate allowance. This is
  documented process-local behavior, not proof of #860's non-bypass claim.
  The deployment-level policy needs reconciliation before promotion, not a
  speculative second authorization mechanism in a CI repair.
- `scripts/soak/run_soak.py:730` always returns `ok: False` for host-preflight
  artifact identity. Its fail-closed promotion tests passed, including the
  synthetic long-duration case; this is not an executed four-hour soak.
- `docs/testing/soak/m3a-load-profile.md:155` explicitly lists missing
  representative workloads and telemetry. Schedule admission racing does not
  execute the claimed physical work; process restart and terminal Run counts
  are not sufficient fencing witnesses.
- The executed server backpressure test uses the actual tasks router, queue
  wiring and Run spine; it proves 202/429/Retry-After and resumed admission
  after a slot frees. It intentionally starts no worker and therefore does
  not prove physical execution or crash recovery.

## Acceptance matrix

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: existing profile explicitly omits multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal/worker workloads; applicability requires selected RC configuration. |
| At least two application replicas | UNVERIFIED at deployment grade: exercised two ASGI middleware instances, not two deployed RC images. |
| Sustained saturation, queues, reclaim, retry and leaks | UNVERIFIED: focused sampler/gate tests passed; no sustained deployed load executed this round. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED: admission and receipt tests cannot establish physical-work uniqueness. |
| Rate/security/degraded non-bypass | UNVERIFIED at deployment grade; executed production-middleware regression reproduces independent replica allowances. Backpressure works in focused router tests. |
| Full telemetry and explicit thresholds | UNVERIFIED: profile defines thresholds, but no new RC telemetry captured; driver loop lag is not application loop lag. |
| Active-work replica restart, drain/fencing/recovery | UNVERIFIED: no deployed RC worker killed/restarted; unit boot cleanup is not active-work recovery proof. |
| Long exact-RC soak | BLOCKED / UNVERIFIED: no designated immutable artifact/configuration supplied; current runner expressly rejects host preflight as RC evidence. |
| Findings filed/reclassified before promotion | Local rate/security invariant gap documented above; external filing/reclassification UNVERIFIED, GitHub mutations prohibited. |
| Machine/human hash-bound RC evidence | UNVERIFIED: this report binds source checks to starting HEAD, not a completed soak of an immutable image/configuration. |

## Handoff and residual risks

Changed file: only this report. No production code, tests, inventory, ledger,
grant, or runtime configuration changed. The explicit vulture-ledger repair
exception requires evidence; the actual scan has no debt to amend. The cited
historical failure is not reproducible. Existing branch work is preserved;
these focused checks do not certify the whole branch or any deployment.

**BLOCKED** on exact-RC deployment evidence and unresolved representative
workload/rate-policy scope. Next: supply the designated immutable image,
normalized runtime configuration and workload applicability; validate the exact
topology with physical-work witnesses, complete telemetry, active-work recovery
and a minimum four-hour sustained soak. A longer host preflight cannot satisfy
this. No merge conflict exists and no fetch/merge or GitHub mutation was needed.

Progress: checked 1 issue, done 0 (acceptance incomplete), skipped 0,
validation errors 0. Local commit is a handoff only, not integration approval.
Run `git diff --check` before committing.

# Issue #860 — bounded repair d23fd2c5

## Frozen scope

- Only issue #860 in worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `5eb8524c328e69ba8fd1f472c25ede8d2c783e4b`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence snapshot: job `d23fd2c506474ee095957d292da59857/dispatch-context.json`;
  supplied previous result `231c402b758d41a6aedc5075a025f29a/result.json`.
- Processing list: reproduce the specified vulture CI gate; validate the existing
  soak admission tests and acceptance evidence; record remaining blockers.
- Candidate edit files: this report, and `quality/vulture-baseline.json` only if
  fresh scanner evidence identifies reviewed retained identities. No speculative
  runtime changes, new execution authority, or GitHub mutations.
- Current job directory contains no driver `check-*.log` files. Inspect the
  explicitly supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` instead.
- Ambiguity: writer/verifier template contains both roles. Proceed as writer,
  as the lane explicitly assigns repair and requires a local commit.

## Progress

Fresh vulture scan passed: 1323 reviewed identities / 1323 findings, zero
unclassified or never-allowlist findings. No ledger amendment is warranted.
`uv sync --locked --extra dev` passed. The supplied historical `check-3.log`
failed because the schema test expected 21 DDL statements and observed 24.
Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
-x -q` passed (37 passed, 6 skipped), so that failure is not reproducible here.
`uv run pytest tests/test_soak_promotion_gates.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
passed (66 tests). These are focused regression results, not a production soak.

The existing profile explicitly labels its runner a host-process preflight and
lists representative workload and physical-work recovery gaps. Production-path
inspection and the acceptance audit follow below.

## Architecture and production reachability

Read repository instructions, `docs/README.md`, and accepted ADR-085,
ADR-081626-f383, ADR-082126-f69c and ADR-082526-b36a. The canonical model remains
`Goal -> Graph -> Run -> NodeRun -> Attempt`: recurrence admits Runs, the Run
store owns fencing, and expired leases require explicit reclaim/liveness rules.
No alternate scheduler, execution owner, authorization path or store was added.

`deploy/docker-compose.prod.yml:27` defines the first server and line 79 the
second, with PostgreSQL, Redis, shared files and a required external model gateway.
This reference topology is not a selected immutable RC artifact. The existing
host-process driver cannot establish image/config equivalence; its
`preflight_artifact_check` at `scripts/soak/run_soak.py:730` explicitly refuses it.

ADR-085 keys rate limiting by principal. The production middleware constructs an
in-memory limiter per instance (`packages/maistro-server/src/maistro_server/api/
rate_limit.py:95`) and is installed on the production app (`main.py:648`).
The executed parametrized regression at `tests/test_soak_promotion_gates.py:439`
gets `[200, 200, 429]` independently from both instances for the same principal
or pre-auth client. This is evidence against a shared replica-independent budget,
not evidence that authentication is bypassed. The documented #842 process-local
semantics are preserved; this report does not reinterpret #860's stronger
non-bypass criterion as satisfied or invent a new security authority to fix it.

## Additional executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files already formatted.
- `uv run python -` imported the actual driver with `importlib`, loaded
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`, called
  `failed_promotion_checks`, and asserted that duration and artifact checks fail.
  Output: observed 420.09 seconds, required 14400 seconds, failed checks
  `sustain_duration` and `exact_rc_artifact`; current preflight artifact check
  also returns false. This reevaluates historical evidence; it is not a new soak.
- The historical schema test now explicitly includes all three validation-audit
  columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176`.
  Its fresh pass does not establish live PostgreSQL concurrency: six DB-dependent
  cases were skipped.

## Acceptance audit

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** Driver uses one key at line 1373; line 1381 mixes health, task admission, receipt reads and metrics. Profile gaps explicitly include users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background/Goal reconciliation. |
| At least two application replicas | **UNVERIFIED for RC.** Compose defines two, and focused tests use two ASGI instances. Neither is a fresh observed deployment of two selected immutable RC images. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leak/restart observations | **UNVERIFIED.** Reevaluated historical evidence is 420.09 seconds and fails the 14400-second requirement. No new load window executed. |
| Schedule/task/Run/Attempt admission, Goal reconciliation and physical-work uniqueness | **UNVERIFIED.** Driver line 1496 probes admission after sustain; receipt identities and one schedule race cannot demonstrate complete physical-effect accounting under sustained load. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED overall; contrary budget evidence reproduced.** Passing production-middleware regression at test line 439 observes fresh allowance after switching replica. Local 429s alone do not prove the requested property. |
| Complete PostgreSQL, application-loop, workers, RSS, fd, queue and error telemetry with thresholds | **UNVERIFIED.** Driver line 1410 measures its own loop lag, not the application loop. No complete exact-RC telemetry series was collected. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED.** Driver line 1427 signals/restarts a process; process rejoin and terminal Run counts alone do not prove no silent physical-work loss/duplication. No fresh active-work RC restart executed. |
| Long exact-RC/config soak, repeated after changes | **UNVERIFIED.** Executed evaluator rejects both duration and artifact identity. Running this host preflight longer cannot satisfy its artifact gate. |
| Load findings filed/reclassified to earliest broken invariant | **UNVERIFIED.** This report records blockers locally; snapshot comments/PR descriptions are not a complete finding-disposition audit. No GitHub mutations performed. |
| Publish machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Retained preflight evidence is not a current promoted-image proof. This report is validation/handoff evidence only. |

## Disposition and next step

**BLOCKED**, not merge-ready. The requested scanner has no unbanked findings and
the cited schema failure is stale. No source/test/ledger changes are warranted by
those checks. Only this report changes; no tests were added, so no inventory delta
is needed. The inherited branch diff is preserved, not approved by focused tests.

Unblock by selecting the actual RC artifact/configuration and applicable workload
surfaces, resolving the replica-budget acceptance mismatch through the existing
security owner, then executing a representative long multi-replica soak with
application telemetry and physical-effect/fencing accounting. Do not retry the
same ledger repair or label a longer host preflight promotion evidence.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected immutable RC and representative production soak"}`.

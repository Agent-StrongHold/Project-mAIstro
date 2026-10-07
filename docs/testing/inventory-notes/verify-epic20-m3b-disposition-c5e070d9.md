# verify-epic20-m3b-disposition-c5e070d9

> This note carries **no `inventory-delta:` block**: it adds and removes no
> tests, and the gate (ADR-082526-547c) reads an absent key as zero movement.
> An earlier draft recorded `docs/testing/inventory-notes: +1` — not a gated
> suite name, and written with a trailing comment the ledger parser rejects —
> which failed CI's suite-inventory step; see the second CI-repair addendum
> below.

Verification record for lane L20 (epic #20 — [EPIC M3-B] Close or explicitly
defer current v1.1 product gaps) at head `c5e070d97d07800464972ee2c026a4d525ffbb21`
(branch `auto-20`, develop base identical). The job's driver produced **no**
`check-*.log` files and `manifest.checks` was empty; the prior run
(`3a83078e`) died on a provider 429 before doing any work. Every claim below
was executed first-party at the exact head. This note moves no test counts.

## Verdict inputs (evidence, not claims)

### Unmet acceptance criteria

- **#1203 (provider-scoped circuit breakers) — NOT implemented.**
  `packages/maistro-core/src/maistro/agents/circuit_breaker.py:323` constructs
  one process-global `llm_circuit = circuit_breaker_from_settings()`, and
  `packages/maistro-core/src/maistro/agents/conductor.py:164-201`
  (`_run_with_retry`) gates *every* LLM call — any tier, any provider the
  gateway routes to — through that single breaker, recording failures into it
  on both retryable and non-retryable paths. No provider/routing-domain keyed
  breaker registry exists in any package; no source file references 1203. A
  flaky provider therefore still opens one breaker that blocks healthy
  providers — exactly the defect the epic's acceptance addition names.

- **#1183 ("explicit about dropped events") — partially met.** Keepalive is
  real (`packages/hive-conductor/backend/routes/dag_runs.py:138,158` — 15 s
  idle `: keepalive` SSE comment), streaming is live with buffered replay
  (`services/dag_run_store.py:398-409`). But fan-out drops are **silent**:
  `dag_run_store.py:364` wraps `q.put_nowait(ev)` in
  `contextlib.suppress(asyncio.QueueFull)` and the replay loop `break`s on
  `QueueFull` (`:408`). No `dropped`/`gap`/`resync` signal exists anywhere in
  the backend or `maistro-server`; a slow client is never told it missed
  events.

- **#355 (close DAG WebSockets/streams on unmount) — partially met.**
  `frontend/src/pages/DagRuns.tsx:163-165` closes its EventSource in the
  effect cleanup. `frontend/src/pages/DagBuilder.tsx` `handleRun` (line ~332)
  opens a run WebSocket and **never closes it** — `grep '\.close()'` on the
  file matches nothing; the socket leaks after the Run settles, on unmount,
  and on every re-run.

- **#358 (paginate/virtualize the audit log) — open.**
  `packages/hive-conductor/backend/routes/audit.py:53` `list_entries` exposes
  no limit/offset; `frontend/src/pages/AuditLog.tsx:113` fetches and renders
  the full array.

- **Epic children still open per KNOWN-GAPS.md at this head** (the explicit
  deferral record): task-queue recovery policy (#91), built-in Canvas job
  runner (#93), Canvas publish/export (#94), API-wide content negotiation
  (#96), complete degraded-mode operating state (#97). KNOWN-GAPS' schedules
  entry ("routes still write `stores.schedules`, which is in memory") is
  **stale** relative to code: `services/foundation.py:111-116`
  (`stores.configure_persistence`) persists and rehydrates the Hive rows, and
  the canonical definition is written before the row
  (`services/scheduler.py:230-251`).

### Met acceptance criteria (proven by execution at this head)

- **M1 #1199 + #92/#850/#1200 scheduling** — implemented and tested:
  - `maistro/scheduling/store.py`: two cursors (`last_fired_at`
    enumeration / `next_due_at` due), `record_fire` the one writer,
    `BEGIN IMMEDIATE` serialization, read-then-put cursor protection.
  - `maistro/scheduling/admission.py`: occurrence claim is the UTC instant,
    not wall-clock text (#850); bounded pre-horizon recovery walks
    (`_MAX_RECOVERY_PROBES`, `_MAX_TRUNCATED_CLAIM_PROBES`); cursor advances
    only after Runs exist.
  - `maistro/scheduling/engine.py:124-213`: catchup horizon partitions
    occurrences; enumeration lower-bounded — bounded under real load.
  - Executed: `pytest packages/maistro-core/tests/scheduling/test_store.py
    packages/maistro-core/tests/scheduling/test_engine.py -k "due or cursor
    or concurrent or writer"` → **32 passed, 14 skipped** (28 in `test_store.py`
    plus 4 in `test_engine.py`; skips are the Postgres parametrizations; no PG
    service was started); `pytest
    packages/hive-conductor/backend/tests/test_schedule_canonical_definitions.py`
    → **36 passed** (canonical definition bridge, drift reconciliation,
    cursor-keeping `put`).

- **#1180 (websocket task streaming off blocking I/O)** — behaviorally
  proven: `backend/tests/test_task_stream_event_loop.py` stands in a real
  stalling HTTP server; **3 passed** (loop stays responsive during the stall;
  cancel takes effect immediately).

- **#333/#1179 (no silent memory downgrade; durable write acknowledgement)** —
  `services/foundation.py:145-160` fails closed with `STATE_UNAVAILABLE`
  instead of serving an empty registry; `routes/health.py:115-119` reports
  per-store ack (`state-commit` vs `process-memory`) and an explicit
  `degraded` composition (`:147,177-193`).

- **#1181 (startup health-visible on partial failure)** — bridge failure
  binds `StubAgentPort` with a warning and `_configured=False`
  (`services/engine.py:172-179`), surfaced through `/health`'s degraded
  flags. *Caveat:* "atomic" startup is only partially evidenced — no
  behavioral test of a torn start was executed in this round.

- **#1184 (cycle/node-timeout config effective or dead contract removed)** —
  cycle config is effective (`maistro/graph/run.py:289` loops on
  `config.max_cycles`; `canonical_dag_runner.py:631`; DFS cycle validator
  `maistro/graph/dag_validator.py:221`); per-node timeout is a live parameter
  threaded through dispatch (`maistro/graph/node.py:289,313`). No dead
  node-timeout contract found in the reachable DAG surfaces. Issue text was
  not readable offline; **partially verified**.

- **#95** — done at this head (HEAD commit is the `/design-studio` cutover;
  KNOWN-GAPS records the IA cutover); **#440** — marked completed in the
  epic snapshot.

## Validation battery (executed)

- `uv run ruff check .` → All checks passed (exit 0).
- `uv run ruff format --check .` → 2638 files already formatted (exit 0).
- Targeted pytest runs as listed above (scheduling selection, hive canonical
  schedule definitions, task-stream event loop). The full-tree suite and the
  Postgres-parametrized scheduling tests were not run (no PG service started;
  ~34 known collection errors without services up).
- No driver `check-*.log` files existed to inspect.

## Disposition

Epic #20 is **not closable at this head**: the Core-final acceptance addition
through #1203 is unimplemented, #1183's dropped-event explicitness is unmet,
#355/#358 remain open in reachable code, and KNOWN-GAPS still defers
#91/#93/#94/#96/#97. Findings are concrete and file:line-addressable; repair
should start with provider-scoped breakers (#1203) and the silent
`QueueFull` suppression in `dag_run_store.py`.

## CI-repair addendum (head `9d6eb434064c`, supply-chain round)

The merge-queue evaluation at this head (docs-only delta over `c5e070d9`)
failed three jobs, all supply-chain — no product code changed:

- `security` + `Supply chain (pip-audit)`: `urllib3==2.7.0` CVE-2026-97687,
  CVE-2026-97688, CVE-2026-97689 (fixed in 2.8.0).
- `test`: the `npm audit --audit-level=high` step on
  `packages/maistro-canvas/frontend` failed on `brace-expansion 5.0.9`
  (GHSA-q2hr-2g5m-vwhr / GHSA-qhr7-859c-m2p7 / GHSA-6j4f-fj2g-mc7p, fixed in
  5.0.12) and `ip-address 10.7.0` (GHSA-j6r3-76f7-8jcv /
  GHSA-h3mg-xc3c-68pw, fixed in 10.7.2). Every pytest step in that job had
  already passed (10870+ passed across sessions; the `Event loop is closed`
  lines are aiosqlite worker-thread warnings, not failures).

Fixes applied (lockfiles only; no `package.json`, no source change):

- `uv.lock`: `urllib3 2.7.0 -> 2.8.0` via `uv lock --upgrade-package urllib3`.
- `packages/maistro-canvas/frontend/package-lock.json`: `npm audit fix` →
  `brace-expansion 5.0.12`, `ip-address 10.7.2`.
- `packages/hive-conductor/frontend/package-lock.json`: same `npm audit fix`
  → `brace-expansion 5.0.12` / `1.1.21` (that frontend's audit is not
  currently a CI step; the same high-severity advisory was present, so it was
  fixed while in scope rather than left latent).

Gates re-executed first-party at `9d6eb434064c` after the bump:

- `uv sync --locked --extra dev` → urllib3 2.8.0 installed; `uv pip freeze`
  + `pip-audit --strict` + `uv run python scripts/pip_audit_gate.py` →
  **exit 0** (`pip-audit OK (1 known, all triaged in ALLOWED)`; the two
  remaining ecdsa advisories are the pre-triaged ALLOWED entries).
- `npm ci && npm audit --audit-level=high` in both frontends → **found 0
  vulnerabilities**, exit 0.
- Canvas frontend `npm run test:ci` → **5 files / 79 tests passed**;
  `npm run lint` → 0 errors (13 pre-existing warnings); `npm run build` →
  success (pre-existing >500 kB chunk warning only).
- `uv run ruff check .` → All checks passed; `ruff format --check .` →
  2638 files already formatted.
- `uv run pytest packages/maistro-core/tests -q` → **10835 passed,
  735 skipped, 1 xfailed** (with urllib3 2.8.0).
- Vulture per-identity ledger (CI-repair round check):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1402
  reviewed identities matched, `unclassified: 0`, `never_allowlist: 0` —
  no ledger amendment required and none made.

The scheduling command record above was corrected in this round: the
`test_engine.py` path in the executed selection is now written in full, and
the recorded count reflects the two-file run (**32 passed, 14 skipped**;
store-only is 28).

## CI-repair addendum 2 (head `29c11533d6b5`, suite-inventory ledger round)

The merge-queue evaluation of this head failed exactly one step: the `test`
job's *Suite inventory matches collected node IDs (C1/#286)*
(`scripts/check-suite-inventory.py`, exit 2). Every pytest step in the job
had already passed, and `security`, `npm audit`, lint/typecheck, docker,
e2e, and the pg17/pg18 matrix were all green — the supply-chain fixes from
addendum 1 held.

Root cause (this file, fixed in place): the front matter recorded
`docs/testing/inventory-notes: +1` under `inventory-delta:`. Two defects in
one line — `docs/testing/inventory-notes` is not a suite in the gate's
`RECIPES` (it would have been rejected next as "recorded suites with no
collection recipe"), and the trailing `#` comment is outside the
`<suite>: <±count>` grammar, so the parser raised `cannot read … as
`<suite>: <±count>`` before either mattered. A verification note that moves
no test count records no delta at all; the gate documents the absent key as
the normal zero case, so the block was removed rather than rewritten.

Re-executed at the repaired tree:

- `uv run python scripts/check-suite-inventory.py` → collected every suite
  and compared against baseline + unfolded deltas → **ok: 14 suite(s) match
  the recorded inventory**, exit 0.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1402 reviewed
  identities matched, `unclassified: 0`, `never_allowlist: 0` — no ledger
  amendment required and none made.
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → all files already formatted (exit 0).

# Issue #860 repair — dadc8389

## Frozen scope

One assigned item: #860, branch `auto-860`, starting HEAD
`6a9a2d4b860f58c06c4a9e87e58ad261dcb4f279`, supplied base
`34795962548a33f6b6f7e1234dcea201a9df96ef`. Initial worktree clean.
No GitHub mutations or issue/PR enumeration.

Repair candidates frozen to `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
its adjacent `tests/persistence/test_pg_learnings.py`, `quality/vulture-baseline.json`
(explicit ledger-repair permission), this note, and a matching inventory note only
if tests change. Inspect existing soak harness, promotion tests, load profile,
evidence, repository instructions and relevant ADRs for acceptance verification.

## Initial evidence / assumptions

- Supplied prior `check-3.log` reports 24 schema statements versus 21 expected
  in `test_ensure_schema_fences_ddl_behind_advisory_lock`; reproduce before editing.
- Supplied prior result is BLOCKED on production acceptance, not merge conflict.
  Starting tree is clean; no salvage or develop merge indicated.
- Current job directory has no `check-*.log` files in its initial listing.
- CI ledger request is authorization to review actual scanner findings, not to
  guess debt or weaken promotion gates.

## Validation

- Requested exact vulture command: PASS, 1,326 findings, zero unclassified or
  never-allowlist. No evidence for changing the ledger.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed, 6 skipped. Historical mismatch not reproduced on assigned HEAD.
  Skips are not live PostgreSQL acceptance evidence.
- Read repository instructions, documentation authority map, load profile and
  previous handoff. Profile explicitly says host preflight is not the promoted
  artifact and lists missing representative workload and telemetry coverage.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 66 tests. Includes real production middleware instances demonstrating
  independent per-replica allowances for the same identity; not a cluster soak.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,170 files.
- `uv run python scripts/check-deployment-claims.py`: PASS (static claims only).

## Architecture review

Read accepted ADR-081226-a66b, ADR-081626-f383, ADR-082526-b36a and ADR-085,
and proposed ADR-081. Preserve canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
authority and lease reclamation/renewal semantics. Admission uniqueness does not
prove physical-effect fencing. Proposed deployment language cannot waive exact-RC
acceptance; ADR-085's principal-based limit is not proof of a shared replica budget.
No competing scheduler, persistence authority or authorization path is introduced.

The reported schema failure is stale: the independent expected DDL list already
includes `validated_evaluator_version`, `validation_run_ids` and
`validation_content_hash` (`test_pg_learnings.py:171-176`), matching production's
`_EPISTEMIC_COLUMNS`. No code/test/ledger repair is justified by executed checks.
No tests added or changed, so no inventory delta is required.

## Final acceptance evidence

Executed `uv run python` importlib evaluation of the current harness against
`docs/testing/soak/evidence/m3a-round30-shakedown.json`: rejected exactly
`sustain_duration` and `exact_rc_artifact`. Asserted both failures and the current
artifact check's `ok: false`. This re-evaluates historical evidence; it does not
constitute a fresh soak. `uv run python scripts/check-backlog-consistency.py`
passes (168 items). `git diff --check` passes. Commands used 1,200-second timeouts.

| Acceptance criterion | Disposition / evidence |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED** completeness. `m3a-load-profile.md:147` records missing users/Workspaces, fan-out, successful tools/models, Design/Canvas and reconciliation coverage. |
| At least two supported production replicas | **UNVERIFIED** execution. `deploy/docker-compose.prod.yml:26,77` defines two services; no production topology was deployed this round. |
| Sustained saturation, queue growth, expiry/reclaim, retry, leaks and restart | **UNVERIFIED**. Historical evidence fails duration; no new sustained load executed. |
| No duplicate physical work / fenced admission and reconciliation | **UNVERIFIED**. `test_tasks_concurrency_backpressure.py:11` explicitly starts no runner; schedule probe cleanup cannot establish physical-effect uniqueness. |
| Concurrent security/degraded behavior, no replica-selection bypass | Local enforcement/backpressure tests pass, but cluster non-bypass **not proven**: `test_soak_promotion_gates.py:439` reproduces separate `[200,200,429]` allowances for the same identity. Production installs this middleware at `main.py:648`, whose limiter is process-local (`api/rate_limit.py:93`). |
| PostgreSQL, app-loop, worker, RSS, descriptor, queue and error telemetry with thresholds | **UNVERIFIED** completeness. `run_soak.py:1410` samples driver loop latency, not application loop latency; profile acknowledges incomplete worker and long-window evidence. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Rejoin/terminal counters and unit tests are not physical-work restart evidence. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED**. Current `run_soak.py:730` deliberately rejects host preflight; historical JSON fails both artifact and duration checks. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** completeness. Existing findings and fresh blockers are documented; GitHub mutation is prohibited. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED** for this candidate. Historical artifacts are not evidence for this HEAD; this note is local validation only. |

## Handoff / stop condition

Verdict: **BLOCKED**, not integration approval. Only this report changes in this
round; production, tests, inventory and quality ledgers are unchanged. All
focused checks passed; no scanner-evidenced CI repair remains to perform.

The assignment supplies source refs, not an immutable promotion deployment
identity. Do not manufacture one or relabel the host emulator as production.
Next: select the exact promotion artifact/configuration, complete the missing
production-path workload, telemetry and physical-effect/recovery probes, resolve
the replica-budget contract through existing governance, then run and publish
at least four hours of hash-bound production soak evidence. Repeating these
passing CI checks cannot resolve those acceptance blockers.

Checkpoint: checked 1; done 0 (issue acceptance); skipped 0; errors 0 (executed
validation); blocked 1. Local commit records this handoff; no push or GitHub
mutation performed.

# #860 round-156 validation

**Disposition: NEEDS-REPAIR; the promotion-grade soak still does not exist.**
This round re-derived acceptance from the issue text and re-executed every check
live at merge-head `43c333e5d95bf509a664d98e53e80ed9083b193e` (develop base
`2ac96061` already merged; the prior round's BLOCKED was not a sync conflict —
the worktree was clean at the exact head). The previous result was not treated
as proof.

## Independent evidence scan (repo's own gate function)

- Ran `failed_promotion_checks()` from `scripts/soak/run_soak.py` over **all 20**
  JSONs in `docs/testing/soak/evidence/`: **zero documents pass**. Every
  shakedown record fails `sustain_duration` (observed 420.04–420.10 s against
  the 14,400 s minimum, `ok: false`) and `exact_rc_artifact` (`ok: false`);
  `m3a-round5-final.json` additionally fails `rate_limit_enforced`;
  `m3a-round8-prodstack-extended.json` fails all ten gates.
- `preflight_artifact_check()` returns `ok: false`,
  `topology: host-uvicorn-preflight` — the driver boots host Uvicorn processes,
  never the promoted Compose artifact, and exposes no override by design.

## Live checks executed this round

- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_rate_limit.py
  packages/maistro-core/tests/scheduling/test_pg_admission.py
  packages/maistro-core/tests/persistence/test_pg_learnings.py -q`
  — **147 passed, 8 skipped**, one pre-existing Starlette deprecation warning.
- `uv run ruff check .` — clean; `uv run ruff format --check .` — 3,471 files
  already formatted.
- Driver `check-*.log` files were present in this round's job directory and all
  green: ruff, format, lane tests (63 passed, 6 skipped), suite inventory
  (maistro-core 17,628 and maistro-server 628 node IDs, zero duplicates).
- Closure-keyword review: PR #1672 body says "Refs #860" (draft; no
  fixes/closes/resolves). A keyword scan over every commit message in
  `2ac96061..43c333e5` matched only `fc6a7eb` ("fix(builders): fix 4
  canonical-vs-legacy parity defects (#1067) (#1536)"), where the keyword is
  separated from the parenthesized issue ref by intervening text — no GitHub
  auto-close of an open issue is triggered.
- Branch-only production diffs reviewed: `api/tasks.py` 429 backpressure on
  `RunConcurrencyExceeded` (no invented 202 receipt) and
  `persistence/pg_learnings.py` transaction-scoped advisory lock serializing
  concurrent two-replica schema boot (`#860 F7`, observed live) — both carry
  focused tests in this diff. Neither weakens a gate.
- `deploy/docker-compose.prod.yml` confirms the supported production profile is
  two `maistro-server` replicas behind nginx, so the multi-replica criterion
  applies; `packages/maistro-server/src/maistro_server/api/rate_limit.py`
  documents and constructs a **process-local** limiter (aggregate budget
  N × configured). `tests/test_soak_promotion_gates.py` parametrizes
  `second_replica_limited in [True, False]` and asserts
  `enforced_everywhere is second_replica_limited` — it characterizes the
  replica-selection bypass rather than preventing it.
- `docs/testing/soak/m3a-load-profile.md` self-declares the remaining
  representative-profile gaps (single API key, no Graph fan-out / tool-model /
  Canvas / Goal reconciliation coverage, long-window leak observations) as
  "blockers, not acceptance waivers", and round-153/154/155 records remain
  accurate.

## Acceptance disposition (issue #860 checkboxes)

- Representative RC load profile: **PARTIAL / UNVERIFIED** — profile documented,
  gaps self-declared as blockers, no RC configuration selected to justify them.
- Two replicas exercised: **PARTIAL** — harness runs two replicas, but as host
  processes, not the supported Compose artifact.
- Sustained load (pool saturation, lease reclaim, memory/descriptor growth,
  shutdown/restart) with thresholded telemetry: **NOT MET** — 420 s retained
  evidence vs the 14,400 s promotion window.
- Exactly-once/fenced work across replicas on the RC: **UNVERIFIED**.
- Rate limiting effective under concurrency and not bypassable by replica
  selection: **NOT MET** — process-local limiter by design.
- Kill/restart with graceful drain/fencing during active work: **PARTIAL** —
  kill/rejoin phase exists in shakedown evidence, not at promotion grade on the
  RC.
- ≥ 1 long-running soak of the exact RC artifact (#89 promotion candidate):
  **NOT MET** — no RC designated; `exact_rc_artifact` fails for all evidence.
- Findings filed/reclassified from load: **PARTIAL** — the two-replica boot race
  (`pg_learnings.py` F7) was fixed with tests; full classification awaits a
  qualifying soak.
- Machine- and human-readable hash-tied evidence for the promoted artifact:
  **NOT MET**.

## Verdict rationale

NEEDS-REPAIR, not BLOCKED: the repository state is sound and accurately
self-reporting (gates fail closed, docs truthful, tests/lint/inventory green),
so there is nothing blocked about *verifying* it — what is missing is the
operational acceptance work itself. The next step is unchanged and concrete:
designate and build the immutable RC image/configuration per
ADR-073126-c4e1 §6, close the documented workload/telemetry gaps, run the full
two-replica soak against that exact artifact, and publish hash-tied evidence.
No acceptance waiver is claimed and no gate was modified.

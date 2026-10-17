# Issue #860 — round 132 (job a4c4ad37) repair validation at the dispatched head ba390f718

**Not promotion evidence or integration approval.** This round independently
re-verified the round-131 disposition at the freshly dispatched head rather
than trusting it: every deterministic gate was re-run fresh, the promotion-gate
evaluation and evidence-pack hashes were re-derived in-process, the two
deep-review findings were re-inspected at gate source, the stale verifier
failure was re-tested a fifth time, and the external blockers were re-derived
from this job's own capture. The driver ran no checks for this job
(`manifest.json` `checks: []`; the job directory contains no `check-*.log`);
everything below was executed by the worker.

## Snapshot

- Start head `ba390f718b3bc746c735aaecf72d1c8210076a22` — exactly the
  dispatched head; `git status --porcelain` empty at start and at end.
- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0) and equals `refs/remotes/origin/develop`
  (`ab8b3737fa64f8d840f421ef87ca506c509444ff`): **no develop drift, no sync
  conflict.** (The stale local `refs/heads/develop` at `9fe61e216` is not the
  lane base and is irrelevant to the merge-base check.)
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md' ':!quality'` is **0 rows** and
  `git diff --numstat 5a59c724a..HEAD -- scripts/soak/` is **0 rows** —
  production and soak-gate code are byte-identical to the soaked head
  `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 evidence pack
  remains hash-bound at this head. Only round-record documentation differs
  from the pack head.
- Relative to the develop base, `git diff --numstat ab8b3737fa64..HEAD --
  quality/` is **0 rows**: the vulture ledger is untouched this round.

## Prior-run failures re-tested at this head — none reproducing

1. **Stale verifier failure (5th consecutive non-reproduction).**
   `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`
   (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`,
   recorded at ancestor `872fd2ce`) re-executed fresh at `ba390f718`:
   - `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
     packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
     -q` → **38 passed, 6 skipped** (rc=0).
   - By name: `test_ensure_schema_fences_ddl_behind_advisory_lock` → **1 passed**.
   Stale, not a live defect at this head.
2. **Prior job `70373d27` provider timeout** — `result.json` shows
   `failure_kind: provider_error`, `checks: []`: the worker died before any
   state change. Nothing to salvage; this round performs the intended
   validation from the same dispatched head.

## Deterministic battery at `ba390f718` (all green, run fresh this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed (rc=0) |
| `uv run ruff format --check .` | 3,301 files already formatted (rc=0) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** in 2.29s |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q` | **26 passed** in 2.23s |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings; base `ab8b3737fa64`, candidate `ba390f718b3b`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 backlog items parse, statuses/gaps/citations resolve (rc=0) |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves (rc=0) |
| `uv run python scripts/check-promotion-surface.py` | promotion surface: ok (rc=0) |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (re-derived live, this round)

`failed_promotion_checks` (imported in-process from `scripts/soak/run_soak.py`
at this head) applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json`
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical to
rounds 109–131. Both failures re-verified as correct-by-design at gate source:

1. `scripts/soak/run_soak.py:69` — `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`;
   the gate compares at `run_soak.py:1629`. Pack `sustain_seconds = 420.05`
   (intentional round-109 shakedown) → fails correctly; the ≥4 h sustained
   soak has not been run.
2. `scripts/soak/run_soak.py` `preflight_artifact_check()` deliberately
   hard-codes `ok: false` (docstring: "This driver boots host processes,
   never the promoted Compose artifact … There is deliberately no CLI
   override"). Not a gate bug: weakening it would falsify the release
   requirement this issue enforces.

Field-by-field pack re-check (raw JSON, this round): `hashes.git_head =
5a59c724a20e…`, `git_clean = true`, `git_status_sha256`/`git_diff_sha256` =
`e3b0c442…` (sha256 of empty input — verified by recomputation); production
tree byte-identical to that head (0 diff rows above), so the binding holds at
this head. Functional gates all hold: `exactly_once_task_admission = true`
(12 concurrent duplicate `Idempotency-Key` submissions → 12×202, 1 distinct
run id), `exactly_once_schedule_occurrence = true` (0 occurrences with
multiple runs), `rate_limit_enforced = true` (6-path probe: both replicas
direct auth/unauth + LB auth/unauth all 429 under 800-request bursts;
`enforcement_scope` honestly records the process-local aggregate-budget
limitation tracked against #842), `replica_2_rejoined = true`,
`nonterminal_runs_after_settle = 0`, `graceful_drain` (SIGTERM, `drained:
true`, `escalated: false`, 0 drain 5xx / conn errors, exit 143),
`lb_failover_bounded` (0 observed ≤ budget), `task_admission_availability`
ratio 1.0 over 2,764 submissions outside the kill window.

## External blockers (re-derived from this job's dispatch-context.json, captured 2026-10-17T16:03Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89 is
   **open with 0 comments** in this capture — no RC candidate commit has been
   designated. RC PR #1672 is **open, `draft: true`, `merged: false`**, head
   `15ce4681c4d9` — not a promotable artifact. Issue #860 has no sub-issues
   and no `blocked_by` links in the capture. Designating an RC is a
   release-owner GitHub action this worker must not perform (no GitHub
   mutations).
2. **`sustain_duration` — no authorized ≥4 h production window.** The
   promotion floor is a ≥4 h sustained soak of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited; job budget 5,400 s), and the soak target itself does
   not exist until blocker 1 clears.

## Acceptance-criteria disposition (issue #860, 10 criteria)

| # | Criterion | Status at this head |
| --- | --- | --- |
| 1 | Representative load profile defined | **MET** — `docs/testing/soak/m3a-load-profile.md` (topology, thresholds H1–H6/S1–S5, evidence contract); driver enforces mechanically |
| 2 | ≥2 application replicas | **MET** (preflight topology) — round-109 pack boots/measures replicas :18201+:18202 behind an nginx LB |
| 3 | Sustained load observing pools/queues/leases/RSS/FD/shutdown | **PARTIAL by design** — 420.05 s shakedown with mid-load kill, drain, RSS/FD sampling; ≥4 h floor unmet (blocked, criterion 8) |
| 4 | Exactly-once across replicas | **MET at the admission tier** — H1/H2 gates pass, 0 nonterminal runs; physical-execution dedup for schedules remains admission-only per the evidence doc |
| 5 | Rate limiting effective under concurrency | **PARTIAL** — all 6 paths enforce 429 under burst; cluster-wide allowance cannot be proven with process-local limiter state (#842 mismatch documented, not silently passed) |
| 6 | Metrics with explicit pass/fail thresholds | **MET** — `thresholds.checks` with per-check `ok`, p95 latency, RSS/FD growth, status/error counts |
| 7 | Kill/restart during active work | **MET** (preflight) — SIGTERM mid-load, drained without escalation, replica rejoined, failover bounded |
| 8 | ≥4 h soak of the exact RC artifact | **UNMET — externally blocked** (blockers 1+2 above); both gates fail correctly |
| 9 | Findings filed/reclassified to earliest broken invariant | **MET within lane constraints** — F1–F12 recorded with invariant mapping in `m3a-soak-evidence.md`; harness defects repaired; external filing prohibited |
| 10 | Machine + human-readable evidence tied to hashes | **MET** for existing evidence — hash-tied packs under `evidence/` + `m3a-soak-evidence.md`; binding re-verified live this round |

## Disposition

Round 130's NEEDS-DEEP-REVIEW remains resolved (round 131); this round
re-verified that resolution independently at the new dispatched head and found
no new defect. Every deterministic gate is green, the evidence pack is intact
and hash-tied, production and soak-gate code are byte-identical to the
pack-bound head, and the two failing promotion checks fail correctly against
external prerequisites no in-repo change can satisfy: (a) a
release-owner-designated RC under #89, and (b) an authorized ≥4 h production
observation window for that artifact. Verdict: **externally BLOCKED**, not
repairable here. A "repair" that weakened either gate or fabricated a pass
would violate the issue's own stop condition.

No code changes this round; this record is the only file touched.

Progress: `{checked: 13, done: 13, skipped: 0, errors: 0}` — snapshot +
binding checks, 2 prior-run failures re-tested, 9 deterministic gates green,
promotion-gate evaluation + pack hashes re-derived live, 2 deep-review
findings re-inspected at gate source, external blockers re-derived from this
job's own capture.

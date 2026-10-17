# #860 round 136 — fresh battery, gate re-derivation, and external-blocker re-verification

- Dispatched head: `cff4e6489b22a3a7df969922cd261ac59c702a8c` (branch `auto-860`,
  base `ab8b3737fa64f8d840f421ef87ca506c509444ff`); `git status --porcelain`
  empty at start and at end.
- Job: `/home/dev/maistro/jobs/6ca8cff4e99c4e139e60372e50d52215` (dispatch
  capture `2026-10-17T17:34:09Z`, served from cache; `checks` executed by the
  driver: none — **no `check-*.log` files exist in the job directory**), so
  every check below was executed by the worker at this head.
- Previous block to resolve: rounds 132–135 **BLOCKED** (external
  prerequisites for criterion 8); round 135's attempt chain also included a
  provider-timeout death (`9e0fff84`) and a stale verifier failure reference
  (`98a11313/check-3.log`). Nothing was taken on trust: every deterministic
  check, both gate evaluations, the pack binding, and both external blockers
  were re-derived this round.

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — 6th consecutive non-reproduction at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint / format | `uv run ruff check .` + `uv run ruff format --check .` | **clean** (all checks passed; 3301 files already formatted) |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |

## Structure checks

- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0) and equals
  `refs/remotes/origin/develop` (`ab8b3737fa64f8d840f421ef87ca506c509444ff`):
  **no develop drift, no sync conflict.**
- `git diff --numstat ab8b3737fa64..HEAD -- quality/` is **0 rows**: the
  vulture ledger is untouched (no CI-repair amendment needed or made).
- `git diff 5a59c724a..HEAD -- packages/ scripts/soak/` is **0 rows**:
  production and soak-gate code are byte-identical to the evidence-pack-bound
  head `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 pack
  remains a valid observation of the code at this head. Only round-record
  documentation differs.

## Promotion gates re-derived live (not read from any doc)

`failed_promotion_checks(m3a-round109-shakedown.json)` executed at this head
via `importlib` load of `scripts/soak/run_soak.py`:

- Result: `['sustain_duration', 'exact_rc_artifact']` — exactly the two
  externally blocked gates, nothing else.
- `sustain_duration`: `{"minimum_seconds": 14400, "observed_seconds": 420.05,
  "ok": false}` — fails correctly against the ≥4 h promotion floor
  (`PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`, `run_soak.py:69`).
- `exact_rc_artifact`: `{"ok": false, "topology": "host-uvicorn-preflight",
  "reason": "not the exact production Compose image and configuration"}` — the
  deliberate preflight limitation (`run_soak.py::preflight_artifact_check`,
  which returns `ok: false` unconditionally by design).
- CLI hardening re-read at `scripts/soak/run_soak.py::main` (line 1760):
  `failed = failed_promotion_checks(evidence)`; non-empty → `sys.exit(1)`.
  There is no CLI override; a run cannot report success with a failing gate.

## External blockers (re-derived from this job's own capture, 2026-10-17T17:34Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comments** (updated 2026-09-22) — no RC candidate designated. RC PR #1672
   is **open, `draft: true`, `merged: false`, `merged_at: null`**, head
   `15ce4681c4d9` — not a promotable artifact. Issue #860 has **no sub-issues
   and no `blocked_by` dependencies** in this capture. All 11 comments on
   #860 after 16:00Z today are maistro-progress bot markers (started/blocked);
   zero non-bot comments — no release-owner action. Designating an RC is a
   release-owner GitHub action; GitHub mutations are prohibited for this lane.
2. **`sustain_duration` — no authorized ≥4 h production window.** The floor is
   14,400 s of sustained observation of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited), and the soak target does not exist until blocker 1
   clears. Even an arbitrarily long run of this host-process driver still
   fails `exact_rc_artifact` by design.

Both gates fail correctly; weakening them or fabricating a pass would violate
the issue's own stop condition ("Do not convert this into a benchmark vanity
number") and the lane's no-gate-weakening rule.

## Acceptance-criteria disposition (re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented #842
limitation); 8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two
gates above. Full per-criterion evidence table:
`m3a-round132-validation.md`. This round additionally spot-checked the pack
contents against that table (replica boot `:18201`+`:18202` behind nginx,
SIGTERM mid-load kill with drain/rejoin, exactly-once admission probes with 0
duplicate runs and 0 nonterminal runs, rate-limit 429 across 6 paths, hash
block) — all consistent.

## Disposition

Rounds 132–135's BLOCKED verdict stands. Every deterministic gate is green at
this head, the stale verifier failure is confirmed non-reproducing (6th
consecutive time), the two promotion failures fail correctly against external
prerequisites no in-repo change can satisfy, the evidence pack remains
hash-bound to byte-identical code, and the develop base is exact. Verdict:
**externally BLOCKED**, not repairable here. No code changes this round; this
record is the only file touched.

Progress: `{checked: 11, done: 11, skipped: 0, errors: 0}` — 6-check fresh
battery, 3 structure checks, live promotion-gate re-derivation, CLI-exit
hardening re-read, external blockers re-derived from this job's own capture,
pack contents spot-checked, round-135 disposition re-confirmed.

# #860 round 134 — fresh battery and external-blocker re-verification

- Dispatched head: `bc196f3b8d3818be18f91a2dbac9cf7b256a5d64` (branch `auto-860`,
  base `ab8b3737fa64f8d840f421ef87ca506c509444ff`); worktree clean at start.
- Job: `/home/dev/maistro/jobs/bb04c6a0812948f9bf2b9ff8a7b3eea2` (dispatch
  capture `2026-10-17T16:48:30Z`, 0 API calls — served from cache).
- Previous block to resolve: the round-133 attempt (`979c7c50`) died on a
  provider timeout before doing any work; the standing verdict to re-derive is
  round-132/133 **BLOCKED** (external prerequisites for criteria 3/8). This
  round re-derives every deterministic check and both external blockers from
  scratch — no prior claim taken on trust.

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the failure does not reproduce at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint / format | `uv run ruff check .` + `uv run ruff format --check .` | **clean** (all checks passed; 3301 files formatted) |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |

## Promotion gates re-derived live (not read from any doc)

`failed_promotion_checks(m3a-round109-shakedown.json)` executed at this head:

- Result: `['sustain_duration', 'exact_rc_artifact']` — exactly the two
  externally blocked gates, nothing else.
- `sustain_duration`: `{"minimum_seconds": 14400, "observed_seconds": 420.05,
  "ok": false}` — fails correctly against the ≥4 h promotion floor.
- `exact_rc_artifact`: `{"ok": false, "topology": "host-uvicorn-preflight",
  "reason": "not the exact production Compose image and configuration"}` — the
  deliberate, undocumented-override-free preflight limitation
  (`run_soak.py::preflight_artifact_check`). A host-process driver cannot
  establish artifact equivalence, so this gate can never pass here.
- CLI hardening re-read at `scripts/soak/run_soak.py::main`: exits 1 whenever
  `failed_promotion_checks(evidence)` is non-empty — a run cannot report
  success with a failing gate, and there is no CLI override to suppress it.

## External blockers (re-derived from this job's own capture, 2026-10-17T16:45Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comments** (updated 2026-09-22) — no RC candidate designated. RC PR #1672
   is **open, `draft: true`, `merged: false`, `merged_at: null`**, head
   `15ce4681c4d9` — not a promotable artifact. Issue #860 has **no sub-issues
   and no `blocked_by` dependencies** in this capture. The only #860 comments
   since round 132 are maistro-progress bot posts (started/blocked notices) —
   no release-owner action. Designating an RC is a release-owner GitHub
   action; GitHub mutations are prohibited for this lane.
2. **`sustain_duration` — no authorized ≥4 h production window.** The floor is
   14,400 s of sustained observation of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited), and the soak target does not exist until blocker 1
   clears. Even an arbitrarily long run of this host-process driver still
   fails `exact_rc_artifact` by design.

Both gates fail correctly; weakening them or fabricating a pass would violate
the issue's own stop condition ("Do not convert this into a benchmark vanity
number") and the lane's no-gate-weakening rule.

## Evidence-pack binding re-verified

- Pack: `docs/testing/soak/evidence/m3a-round109-shakedown.json`,
  `hashes.git_head = 5a59c724a20ef1241d57c048df90758f2c2e1e25`.
- `git diff 5a59c724a..HEAD -- packages/ scripts/soak/` → **0 diff rows**:
  production and soak-gate code is byte-identical to the pack-bound head, so
  the round-109 pack remains a valid observation of the code at this head.
- `failed_promotion_checks` is pure and re-runs from the pack document; no
  doc re-derivation depends on stale process state.

## Acceptance-criteria disposition (unchanged from round 133; re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented #842
limitation); 8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two
gates above. Full per-criterion evidence table: `m3a-round132-validation.md`
(`git diff 5a59c724a..HEAD -- packages/ scripts/soak/` is empty, so production
code is byte-identical since that table was written; this round re-ran the
deterministic subset that can drift).

## Disposition

Rounds 132/133's BLOCKED verdict stands. Every deterministic gate is green at
this head, the stale verifier failure is confirmed non-reproducing, the two
promotion failures fail correctly against external prerequisites no in-repo
change can satisfy, and the evidence pack remains hash-bound to byte-identical
code. Verdict: **externally BLOCKED**, not repairable here. No code changes
this round; this record is the only file touched.

Progress: `{checked: 10, done: 10, skipped: 0, errors: 0}` — 6-check fresh
battery, live promotion-gate re-derivation, CLI-exit hardening re-read,
external blockers re-derived from this job's own capture, pack binding
re-verified, round-133 disposition re-confirmed.

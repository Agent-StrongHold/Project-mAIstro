# #860 round 139 — fresh battery, upstream-state re-derivation (incl. merged PR #2100), and external-blocker re-verification

- Dispatched head: `fed0a288a8fe3f71d516e79b510706c8bdc6115e` (branch
  `auto-860`, base `ab8b3737fa64f8d840f421ef87ca506c509444ff`);
  `git status --porcelain` empty at start and at end.
- Job: `/home/dev/maistro/jobs/ceaac5d29d8848beaa67bdf84e8573e0`
  (**no `check-*.log` files exist in the job directory** — the driver executed
  no deterministic checks), so every check below was executed by the worker at
  this head. Nothing was taken on trust: the battery, both gate evaluations,
  the pack binding, the raw pack contents, the upstream issue/PR state, and the
  develop-drift disposition were all re-derived this round.
- Previous block to resolve: round 138 **BLOCKED** (external prerequisites for
  criterion 8). Resolution attempt below — the block is external and stands;
  two new external facts were derived and dispositioned (develop ref-state and
  the now-merged PR #2100).

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — 9th consecutive non-reproduction at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint | `uv run ruff check .` | **clean** (all checks passed) |
| Format | `uv run ruff format --check .` | **3301 files already formatted** |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |
| Vulture per-identity ledger (CI's exact arguments) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **rc=0: 1322 reviewed identities = 1322 findings, base `ab8b3737fa64`, candidate `fed0a288a8fe`, ledger unamended** |

## Structure checks

- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0).
- `git diff --numstat ab8b3737fa64..HEAD -- quality/` is **0 rows**: the
  vulture ledger is untouched (confirmed by the rc=0 gate above; no
  CI-repair amendment needed or made).
- `git diff 5a59c724a..HEAD -- packages/ scripts/soak/` is **0 rows**:
  production and soak-gate code are byte-identical to the evidence-pack-bound
  head `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 pack
  remains a valid observation of the code at this head. Only round-record
  documentation differs.

### New this round: develop ref-state re-derived (no new drift)

A bare `git rev-parse origin/develop` resolves **ambiguously** in this clone
(hundreds of `origin/gh-readonly-queue/develop/pr-*` refs share the namespace)
and can print the base. Using the explicit ref:
`refs/remotes/origin/develop` =
`369ab9adde2eb66c105ca4ea950795df8192eb3f` — unchanged since round 138's
finding, still exactly one docstring-only commit (`#2140`) on top of the lane
base, still **not contained in HEAD**. Disposition unchanged from round 138:
not merged, to preserve the round-109 pack byte-identity binding; flagged for
the release integrator.

### New this round: PR #2100 merged — verified already incorporated

`fix(security): recognize historical soak fixture fingerprints` (#2100,
`merged: true`, `merged_at: 2026-10-10T02:09:32Z`, merge commit
`7ffedbb4314fcbd10dd7b08db31536bc2d517613`) adds two scoped `.gitleaksignore`
rows for this lane's historical soak-fixture fingerprints
(`8185c1d0…:scripts/soak/run_soak.py:generic-api-key:51` and
`88edcc7e…:docs/testing/soak/evidence/m3a-round7-prodstack-quick-probes.json:
generic-api-key:13`), so protected-branch `--all` scans that fetch this
unmerged lane stop re-reporting them. `git merge-base --is-ancestor
7ffedbb4314 HEAD` → **exit 0**: the merge is part of this lane's history and
its rows are present in this branch's `.gitleaksignore`. No action needed; the
lane's own ignore contract (`tests/test_gitleaksignore_contract.py`, 16
passed above) remains green.

## Promotion gates re-derived live (not read from any doc)

`failed_promotion_checks(m3a-round109-shakedown.json)` executed at this head
via `importlib` load of `scripts/soak/run_soak.py`:

- Result: `['sustain_duration', 'exact_rc_artifact']` — exactly the two
  externally blocked gates, nothing else.
- `sustain_duration`: observed 420.05 s vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`scripts/soak/run_soak.py:69`) — fails correctly against the ≥4 h
  floor.
- `exact_rc_artifact`: `preflight_artifact_check`
  (`scripts/soak/run_soak.py:744`) returns
  `{"ok": false, "topology": "host-uvicorn-preflight", "reason": "not the
  exact production Compose image and configuration"}` — `ok: false`
  unconditionally by design; there is deliberately no CLI override.
- CLI hardening re-read: `sys.exit(1)` on any failed gate
  (`scripts/soak/run_soak.py:1763`). A run cannot report success with a
  failing gate.
- Raw pack contents re-inspected from
  `docs/testing/soak/evidence/m3a-round109-shakedown.json` (round-138 summary
  named the criteria keys loosely; the precise locations are): gate booleans
  live under `thresholds.checks` — `exactly_once_task_admission: true`,
  `exactly_once_schedule_occurrence: true`, `rate_limit_enforced: true`,
  `replica_2_rejoined: true`, `nonterminal_runs_after_settle {count: 0,
  ok: true}`, `lb_failover_bounded {observed_5xx_and_conn_errors: 0,
  observed_window_seconds: 6.58, upper_bound_kill_window: 27.0, ok: true}`,
  `graceful_drain {required: true, signal: SIGTERM, drained: true,
  drain_seconds: 1.0, drain_5xx: 0, drain_conn_errors: 0, escalated: false,
  ok: true}`, `fd_growth` 30→36 (max 41) / 29→34 (max 39), `rss_growth`
  9.0% / 7.7%, `task_admission_availability {ratio: 1.0, ok: true}`; probe
  detail under `exactly_once_tasks {12 submissions → 1 distinct run id,
  ok: true}` and `exactly_once_schedule_claim {runs_created_for_occurrence:
  1, duplicate_claims_reported: 1, occurrences_with_multiple_runs: 0,
  ok: true}`; `final_runs_by_status {completed: 2796, cancelled: 1}`;
  `hashes.git_head = 5a59c724a…`, `git_clean: true` — all consistent with the
  round-132 per-criterion table and the two failing gates above.

## External blockers (re-derived from this job's own capture, 2026-10-17T18:44–18:45Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comment objects** (updated 2026-09-22) — no RC candidate designated. RC
   PR #1672 is **open, `draft: true`, `merged: false`**, head `15ce4681c4d9` —
   not a promotable artifact. Designating an RC is a release-owner GitHub
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

## Acceptance-criteria disposition (re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented #842
limitation); 8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two
gates above. Full per-criterion evidence table:
`m3a-round132-validation.md`, spot-checked against the raw pack this round
(see above). No in-repo change can move criterion 8.

## Disposition

Rounds 130–138's BLOCKED verdict stands. Every deterministic gate is green at
this head (8-check battery, suite inventory, vulture ledger with CI's exact
arguments), the stale verifier failure is confirmed non-reproducing (9th
consecutive time), the two promotion failures fail correctly against external
prerequisites no in-repo change can satisfy, the evidence pack remains
hash-bound to byte-identical code, and both new external facts (develop
ref-state, merged PR #2100) are derived and dispositioned rather than acted
on. Verdict: **externally BLOCKED**, not repairable here. No code changes this
round; this record is the only file touched (docs-only, no test additions —
no inventory delta required; the suite-inventory gate above confirms 17
suites unchanged).

Progress: `{checked: 14, done: 14, skipped: 0, errors: 0}` — 8-check fresh
battery, 3 structure checks + develop ref-state re-derivation + PR #2100
ancestry verification, live promotion-gate re-derivation with CLI-exit and
preflight re-reads plus raw-JSON pack verification under exact key paths,
external blockers re-derived from this job's own capture, round-138
disposition re-confirmed.

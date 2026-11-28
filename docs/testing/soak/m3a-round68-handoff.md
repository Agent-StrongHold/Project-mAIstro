# Issue #860 — round 68 (job f8121790) independent re-validation at 390060aee → merge 070727f936

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `390060aee2eff73e3f2227d0c140a0cfe00888fb`
(working tree clean on arrival, exactly the dispatch head — HEAD is the prior round
f8980532's own `end_head`, so nothing to salvage), then — for the first time in the
lane — resolves a **real develop sync conflict in place** per the dispatch rule, and
re-runs the battery at the merge head `070727f936c6ba076b57b507671bdd1f6748e8ab`. The
round-53 escalation (NEEDS-DEEP-REVIEW) remains **external and unchanged**: acceptance
rows 3 and 8 require a release-owner RC designation under parent #89 plus a
release-owner-hosted ≥14,400 s soak of the exact production Compose artifact, neither
of which any repair worker can supply.

## Why a merge was mandated this round (reconciliation with rounds 57–67)

Rounds 57–67 recorded "failures were never sync conflicts so no merge mandated":
their dispatch base stayed `1f328be9` and no validation failure traced to the
diverged batch. This round the campaign advanced the dispatch base to `4aa68edc`,
and a fresh fetch shows `origin/develop == 4aa68edc` (13 develop-side commits:
#2094 M9-B WIP, #1712 M1 closeout WIP, #2074 research WIP, security fixes #2106
/#2104/#2105/#2103/#2101/#2098/#2100, #1729/#1742/#2006 WIP). `git merge-tree
--write-tree HEAD origin/develop` reports a **content conflict in
`.gitleaksignore`** — the first true sync conflict of the lane — because develop
side (#2100, commit 7ffedbb43) appended its own copy of the #860 soak fingerprints
while the lane had evolved the same entries with re-keying/dedup commentary. Per
the dispatch rule ("fetch origin, merge origin/develop into the branch, resolve
every conflict in place, and commit the resolution") the merge was executed:

- **Resolution:** `.gitleaksignore` → the lane's stage-2 blob (8a0ff7d5),
  verified by fingerprint multiset comparison **before** resolving: OURS 34
  fingerprints / THEIRS 34 fingerprints, `Counter` equality exact — the lane's
  version is the strict union (it carries the 8185c1d0 + 88edcc7e entries develop
  re-added, plus the re-keyed 77c17b9b block and the dedup note keeping
  `test_gitleaksignore_contract.py::test_fingerprints_are_unique` meaningful).
  No fingerprint from either side was dropped; no new suppression was added.
- **Ledger safety (quality/*.json row-loss hazard):** the lane branch carried
  **zero** quality/ changes vs merge-base `cc6e4899` (`git diff --numstat
  cc6e4899 390060aee -- quality/` empty); the merge result's quality/ tree is
  byte-identical to `origin/develop`'s (17+17+17 ac-state rows, frontend-typed-client
  2/4, shipped-surface 60 — all develop's own additions). `vulture-baseline.json`
  and `promotion-surface-baseline.json` blobs identical across base/lane/develop/merge.
- Post-merge `tests/test_gitleaksignore_contract.py` green (below), and
  `grep -c '<<<<<<<\|>>>>>>>\|======' .gitleaksignore` → 0.

## Deterministic battery executed (driver `checks` list empty again — no `check-*.log` files exist for this job; full battery run directly)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Stale `98a11313/check-3.log` failure re-run: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-core/tests/persistence/test_pg_sessions_concurrency.py` against a **freshly migrated** database (created `m3a860` in `maistro-postgres`, `alembic upgrade head` 058→062; the long-lived shared dev DB has drifted and lacks `quota_invocation_evidence`, which is what the stale round-44 DDL-fence failure actually was) | **46 passed** (37 pg_learnings + 9 pg_sessions_concurrency), 0 skipped |
| Soak/contract/release-guard/concurrency set (13 files: `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_check_release_consistency.py`, `tests/test_check_promotion_surface.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py`) | **492 passed, 16 skipped** in 11.79 s |
| Merge-resolution + develop-side rsi promotion tests: `tests/test_gitleaksignore_contract.py` + 5 `packages/maistro-rsi/tests/test_promotion_*/review/evolve` files | **60 passed** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (base `4aa68edc` = dispatch base, candidate = merge head) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-shipped-surface-truth.py` | Matrix complete |
| `scripts/check-doc-links.py` | Every relative markdown link resolves |

mypy intentionally not run: the merge resolution touched zero Python files, so the
type state is exactly develop's own CI-validated state.

## Promotion replay (live gate code, this round, at merge head)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['exact_rc_artifact', 'sustain_duration']`:

- `sustain_duration`: observed `420.09 s` vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`, read at `:1601-1602`). No env/CLI override exists.
  The 14,400 s continuous floor exceeds this lane's 5,400 s job budget with
  background execution prohibited — **no in-lane run can flip this row**.
- `exact_rc_artifact`: `{'ok': False, 'reason': 'not the exact production Compose
  image and configuration', 'topology': 'host-uvicorn-preflight'}` — deliberate
  refusal of the host-uvicorn-preflight topology (`run_soak.py:729-743`).
- All 8 correctness gates `ok=true`: `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `graceful_drain` (SIGTERM required, drained,
  not escalated, `drain_5xx=0`, `drain_conn_errors=0`).
- Pack provenance re-verified: added once by `215bdec8a` whose parent ==
  recorded `hashes.git_head 3da4e035eb1f46093d507db0f90b131a3a8d6dbe`, never
  modified since, ancestor of HEAD. `m3a-load-profile.md` present (row 1 of the
  issue's acceptance list).
- Zero drift since the evidence head: `git diff 3da4e035eb HEAD -- scripts/soak/
  deploy/nginx.conf tests/test_soak_promotion_gates.py
  tests/test_gitleaksignore_contract.py` is empty post-merge (develop's only
  deploy-side change, `backup.sh` +12/−1 from #2105, is referenced by neither
  `run_soak.py` nor `test_soak_promotion_gates.py` — grep count 0 in both).

## External pair re-derived from this round's own 69-source capture (2026-10-10T10:03Z)

- Issue #860 open, 401 comments, updated 2026-10-10T09:46:57Z; body unchanged
  (acceptance list identical).
- Parent-endpoint entry in this capture returned `data: null` (empty body);
  rounds 57–67 consistently captured parent #89 **open / 0 comments / updated
  2026-09-22** — no release-owner RC designation exists there, unchanged.
- Linked PR heads unchanged: **#1672 open draft** at `16b244414b01`;
  #1567 (`d2237879`), #1602 (`927a9c3c`), #2100 (`b950e593`) closed/merged with
  no RC designation (#2100 is the develop-side soak-fingerprint entry itself).
- Designation-regex sweep over all comment/timeline records: **1 hit**, and it
  is the issue body's own prose ("Promote a release candidate through the exact
  shipping pipeline…") — no designation.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows
`load profile / two replicas / exactly-once / rate limiting / kill-restart /
metrics-thresholds` are proven by the round-43 pack (8/8 correctness gates) and
re-proven by the green battery at the merge head; rows `sustained soak of the
exact RC artifact` remain **UNVERIFIED pending release-owner action** (RC
designation under #89 + release-owner-hosted ≥14,400 s production-Compose run).
Gate weakening is prohibited; no in-lane action can advance them further.

Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` 17/17 green confirms). The only tree change this
round is the develop sync merge (conflict-free except `.gitleaksignore`,
resolved as above) plus this handoff note.

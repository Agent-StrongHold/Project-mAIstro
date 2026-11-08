# Issue #860 — round 58 (job 050a5645) independent re-validation at 3336e157

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `3336e157366d1132d29a0c6e546d9d251b1024fe`
(working tree clean on arrival, exactly the dispatch head) and re-derives the
terminal external pair from this round's own 69-source capture
(2026-10-10T06:03–06Z, sha256 `43347dc8b707f2bc…`). The round-53 escalation
(NEEDS-DEEP-REVIEW) remains **external and unchanged**: rows 3 and 8 require a
release-owner RC designation under parent #89 plus a release-owner-hosted
production soak, neither of which any repair worker can supply.

Two prior-run facts resolved this round: the immediately preceding job
`7fc37538` died on a **provider timeout** (`failure_kind: provider_error`,
`checks: []`) before touching the tree — its head was this same `3336e157`,
so nothing was lost or salvaged; and this round's driver manifest again
carried an **empty `checks` list** (no `check-*.log` files exist for job
`050a5645`), superseded by direct full-battery execution below. The prompt's
"Validation failed" pointer again referenced job `98a11313`'s `check-3.log` —
the same **stale round-44 artifact** whose DDL-fence failure predates the
current head and was re-executed green this round (below). No source, test,
gate, ledger, or inventory file changed; the only artifact is this handoff
note. Inventory delta: 0 (no collected tests added or removed).

## Deterministic battery executed at `3336e157` (all green, this round)

| Gate | Result |
| --- | --- |
| `git fetch origin` + `rev-parse origin/develop` | `1f328be9` == this round's dispatch base — no sync conflict, no merge mandated (HEAD already contains the prior develop tip `ed5613457` as an ancestor; the 12 new develop commits are security/WIP batch `7ffedbb43..1f328be96`, not a lane conflict) |
| Evidence-head ancestry `git merge-base --is-ancestor 3da4e035 HEAD` | true |
| Soak-path drift `git diff --name-only 3da4e035..HEAD -- scripts/soak/ deploy/` | empty — runtime/gate/deploy trees byte-identical since the evidence head; 21 drifted files all under `docs/testing/soak/`, plus 5 unrelated test files |
| Stale `check-3.log` failure file: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 37 passed, 6 skipped — the round-44 DDL-fence failure does not reproduce at this head |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py tests/test_release_guard.py -q` | 105 passed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1057) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run radon cc packages/*/src -i third_party --min B --total-average` (quality.yml:834) | 12,732 blocks, average A (2.968) |
| `scripts/check-doc-links.py` | Every relative markdown link resolves |

## Promotion-gate replay (executed this round, live module import)

`failed_promotion_checks()` loaded from `scripts/soak/run_soak.py` and run
against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:
fails **exactly** `['sustain_duration', 'exact_rc_artifact']`.

- 8/8 correctness gates ok: `exactly_once_schedule_occurrence`,
  `exactly_once_task_admission`, `graceful_drain` (`drain_5xx: 0`),
  `lb_failover_bounded`, `nonterminal_runs_after_settle`,
  `rate_limit_enforced`, `replica_2_rejoined`,
  `task_admission_availability`; two-replica evidence in
  `m3a-round43-shakedown-replica-1820{1,2}.log`; pack hashes bind
  `git_head 3da4e035eb`, nginx/rendered conf, soak env, git-status digest,
  and postgres image digest.
- `sustain_duration`: observed 420.09s vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`). The job budget is 5,400s (manifest
  `timeout_s`), background commands are prohibited, and no environment
  override exists for the floor (the only `os.environ` uses in `run_soak.py`
  are subprocess env plumbing at lines 197/221) — **no in-lane run can flip
  this row**.
- `exact_rc_artifact`: `preflight_artifact_check()` (`run_soak.py:730-742`)
  deliberately returns `ok=False` for the host preflight topology with
  **no CLI override**; parent #89 is open with **0 comments** in this
  round's 06:03Z capture and the capture's 5 designation-language hits are
  all requirement text or explicit negations inside #1672 diff hunks — no
  release candidate is designated, so there is no exact-RC artifact to
  soak. **Externally gated on a release-owner action.**

## External pair re-derived from this round's own capture

- Parent #89 ("M3-A7 — Run RC soak and byte-equivalent final promotion"):
  open, 0 comments — no RC designation exists (69 sources, captured
  2026-10-10T06:03–06Z).
- Linked PRs unchanged: #1567/#1602 closed (merged ancestors verified in
  prior rounds), #1672 open **draft** whose diff hunks only ever state the
  *absence* of a designation, #2100 develop-side with fingerprints carried
  at `.gitleaksignore:69/:96`.
- `origin/develop` at fetch time equals this round's dispatch base
  `1f328be9`; the branch is not in a sync conflict, so no merge is mandated.

## Acceptance disposition (unchanged)

| #860 criterion | Disposition |
| --- | --- |
| Load profile, ≥2 replicas, exactly-once fencing, rate-limit under concurrency, kill/drain/recovery, metrics with thresholds, findings filed, machine+human evidence | Evidenced by the round-43 pack and `m3a-load-profile.md`; gate replay green on all 8 functional rows |
| Sustained soak ≥4 h of the exact RC artifact/configuration | **BLOCKED (external):** 420.09s functional shakedown banked; the ≥14,400s row needs a release-owner-hosted run exceeding any in-lane budget |
| Exact-RC artifact identity | **BLOCKED (external):** no RC designated under open parent #89; the harness correctly refuses to sign artifact equivalence by design |

Next owner action: designate the immutable promotion RC/configuration under
#89 and host the ≥14,400s production soak; until then every lane round
converges on the same two terminal rows.

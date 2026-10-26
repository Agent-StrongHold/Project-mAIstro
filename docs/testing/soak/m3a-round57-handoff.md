# Issue #860 — round 57 (job 62621b14) independent re-validation at 34d786ad0

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `34d786ad0d23e529827f957d1621920fba4d1989`
(working tree clean on arrival, exactly the dispatch head) and re-derives the
terminal external pair from this round's own 69-source capture
(2026-10-10T05:40Z, sha256 `56bb9e07…`). The round-53 escalation
(NEEDS-DEEP-REVIEW) remains **external and unchanged**: rows 3 and 8 require a
release-owner RC designation under parent #89 plus a release-owner-hosted
production soak, neither of which any repair worker can supply.

The driver manifest for this round again carried an **empty `checks` list**
(no `check-*.log` files exist for job `62621b14470e4cfcb6e2d5707b2c4dcf`),
and the prompt's "Validation failed" pointer again referenced job `98a11313`'s
`check-3.log` — the same **stale round-44 artifact** whose DDL-fence failure
(`test_ensure_schema_fences_ddl_behind_advisory_lock`, 24 != 21) predates the
current head and was re-executed green this round (below). No source, test,
gate, ledger, or inventory file changed; the only artifact is this handoff
note. Inventory delta: 0 (no collected tests added or removed).

## Deterministic battery executed at `34d786ad0` (all green, this round)

| Gate | Result |
| --- | --- |
| `git fetch origin` + `rev-parse origin/develop` | `ed5613457` == dispatch base — no sync conflict, no merge mandated |
| Evidence-head ancestry `git merge-base --is-ancestor 3da4e035 HEAD` | true |
| Stale `check-3.log` test alone: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock -q` | 1 passed — the round-44 failure does not reproduce at this head |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1057) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run radon cc packages/*/src -i third_party --min B --total-average` (quality.yml:834) | 12,732 blocks, average A |
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
  `m3a-round43-shakedown-replica-1820{1,2}.log`.
- `sustain_duration`: observed 420.09s vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`). The job budget is 5,400s
  (manifest `timeout_s`), background commands are prohibited, and no
  environment override exists for the floor (the only `os.environ` uses in
  `run_soak.py` are subprocess env plumbing at lines 197/221) — **no in-lane
  run can flip this row**.
- `exact_rc_artifact`: `preflight_artifact_check()`
  (`run_soak.py:729-742`) deliberately returns `ok=False` for the host
  preflight topology with **no CLI override**; parent #89 is open with
  **0 comments** in this round's 05:40Z capture — no release candidate is
  designated, so there is no exact-RC artifact to soak. **Externally gated on
  the release owner.**

## Evidence-pack provenance re-verified (this round, strengthened)

- The pack was added exactly once by commit `215bdec8a`
  (`git log --diff-filter=A`) and **never modified afterward** — no post-hoc
  tampering.
- `215bdec8a`'s direct parent is `3da4e035eb1f…`, byte-equal to the pack's
  recorded `hashes.git_head`.
- The pack recorded `git_diff_sha256 = e3b0c442…` (the empty-input digest):
  the tracked tree at run time was byte-identical to `3da4e035`; only
  untracked status noise differed (`git_clean: false`,
  `git_status_sha256: 0c4ad4fc…`).
- Zero commits in `3da4e035..HEAD` touch `scripts/soak/`, `deploy/`,
  `tests/test_soak_promotion_gates.py` — **zero soak-path runtime/gate/test
  drift** since the evidence head. (Broader branch drift of 186 files since
  `3da4e035` — hive-conductor RUM, research harnesses, extension packages —
  touches none of the soak-relevant paths above.)

## Verdict carried forward

Rows 1, 2, 4, 5, 6, 7, 9, 10 evidenced (round-43 pack + live gate replay +
zero soak-path drift). Rows 3 and 8 are UNVERIFIED/EXTERNAL and cannot be
satisfied inside a bounded 5,400s repair attempt by design of the promotion
floor and the absent RC designation. Escalation to the release owner under
#89 stands.

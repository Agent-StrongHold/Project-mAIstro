# Issue #860 — round 87 (job c66a5b75df0e4327b63fff0b0e3d47d3) independent re-validation at 47d5090f4

**Not promotion evidence or integration approval.** This round re-executes the
full deterministic battery at the dispatch head
`47d5090f4a5912f37941dbc0c99aae40d04888e4` (working tree clean on arrival,
exactly the dispatch head — the round-86 handoff commit itself). The driver
ran zero deterministic checks this round (`checks: []` in the job manifest and
no `check-*.log` files), so every gate below was executed directly at HEAD.
Content delta from round 86 is nil (docs-only rounds; `git diff` between the
validated round-85 tree and HEAD adds only round 86's handoff file), and every
gate reproduced rounds 72–86 exactly.

## Deterministic battery executed (all green at HEAD 47d5090f4)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Reconciled: uninstalled a leftover `maistro-bootstrap` editable (bootstrap is a separate extra, `pyproject.toml:120-122`; `maistro_server` resolves via pytest `pythonpath`, `pyproject.toml:294-305`) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| 13-file soak/contract/release-guard/concurrency set (same composition as rounds 72–86) | **308 passed, 16 skipped** |
| Drain + rate-limit set (`test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `security/test_rate_limiter.py`) | **38 passed** |
| Promotion-surface/governance/release set (6 files) | **283 passed** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| PG live set (`test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 14 h, `127.0.0.1:18433`, credentials from the container's own env), alembic head verified `062 (head)` | **46 passed, 0 skipped**; DDL-fence test `::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure (assert 24 == 21) does not reproduce at this head |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory (delta 0) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `git diff --check` | Matrix complete / every relative markdown link resolves / clean |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `vulture-ratchet.yml:81-86`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `47d5090f4a59`) — no ledger amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** |

## Develop drift (unchanged; not a sync conflict)

`git fetch origin develop` at round start: `origin/develop` is `435dc1937e04`
— exactly this round's manifest base; merge-base `4aa68edc0b6b` unchanged.
`quality/` numstat vs `origin/develop` shows only the develop-side additions
(`durable-table-retention.json` +24, `shipped-surface-truth.json` +10) made by
`435dc1937` on files this branch never touched. Validated at the contractual
head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`; `preflight_artifact_check()`
returns `ok: False, topology: host-uvicorn-preflight` and
`PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` read live.

- `sustain_duration`: pack observed `420.09 s` vs floor `14,400 s`
  (`run_soak.py:67`, compared at `:1601-1602`). A grep across every committed
  evidence pack shows the best observed sustain anywhere is `420.1 s`
  (round-29) — no pack approaches the floor. The floor exceeds this job's
  `timeout_s = 5400` (read from the manifest), and background commands are
  prohibited, so no in-lane run can flip this row.
- `exact_rc_artifact`: hardwired to `preflight_artifact_check()`
  (`run_soak.py:1552`), which refuses host topology deliberately ("There is
  deliberately no CLI override", `run_soak.py:730-743`). No RC
  artifact/configuration is designated upstream (see external pair), so there
  is nothing to soak against.
- All other gates re-read ok from the pack: `graceful_drain` ok=True
  required=True, `lb_failover_bounded`, `exactly_once_schedule_occurrence`,
  `exactly_once_task_admission`, `rate_limit_enforced`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle` (count 0), `task_admission_availability`
  (ratio 1.0); `duplicate_evidence.runs_sharing_one_task_run_identity` = 0.
- Pack provenance re-verified: recorded `hashes.git_head` `3da4e035eb1f` is an
  ancestor of HEAD (`git merge-base --is-ancestor`), and
  `git diff 3da4e035..HEAD -- scripts/soak/` is empty — zero gate-code drift
  since the evidence head, so the replay is faithful.

## External pair (this round's 18:22Z capture, 69 sources)

Issue #860 open, **450** comments (delta +3 vs round 86), all 10 acceptance
checkboxes unchecked. The three newest comments are lane progress markers only
(`maistro-progress:…:blocked` / `:started` for jobs `7c7633858`, `0eeb29bbf`,
`da99f94c6`) — zero RC-designation tokens. Parent #89 open, 0 comments.
Linked PRs unchanged: #1672 open draft (`16b244414b`, unmerged); #1567, #1602,
#2100 closed and merged.

## Verdict

**NEEDS-DEEP-REVIEW carried forward — the blocker is external to the lane and
unchanged.** Every deterministic gate is green at the contractual head; the
promotion replay fails on exactly the two rows an in-lane run provably cannot
flip (≥4 h continuous soak, floor 14,400 s > lane timeout 5,400 s with
background prohibited; exact-RC soak with no RC artifact designated upstream
and no harness override by design). Resolution requires an upstream decision —
designate the RC artifact/configuration that #89 would promote and run the
≥4 h soak outside lane constraints — not further code repair. Inventory delta:
0 (no tests added or removed; this round adds only this handoff doc).

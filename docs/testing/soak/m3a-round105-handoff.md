# Issue #860 — round 105 (job c86b6368) independent re-validation at 7164c97f

**Not promotion evidence or integration approval.** The previous block was
again "worker requested attention: NEEDS-DEEP-REVIEW" caused by a
provider-timeout job (`dbab5bd7…`, `failure_kind: provider_error: Request
timed out`, `checks: []` — zero checks executed). This round resolves the
block by re-executing the full deterministic battery at the current head
without taking any prior round's claims on trust, and makes exactly one
repair: the dangling run-1 machine-evidence pointers in
`m3a-soak-evidence.md` (see below).

## Snapshot

- Head `7164c97f0b8a6eb56f33bcc947243589b1009612` (round-104 handoff commit),
  tree clean before this round's edits; base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- `git diff --name-only ed0fe24a07a0..HEAD -- packages scripts tests deploy`
  is empty: production source is byte-identical to the round-100 soak head,
  so the round-100 evidence binding (`hashes.git_head = ed0fe24a0…`,
  `git_clean = true`) remains valid at this head.
- This job directory contains no `check-*.log` files. The historical
  validation failure `98a11313/check-3.log`
  (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`)
  was captured at a verify head predating the F7 advisory-lock fix and the
  develop merge; re-executed below at this head and it does not reproduce
  (the test now expects and finds the full fenced DDL body).

## Re-executed deterministic battery at `7164c97f` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the `98a11313` failure does not reproduce |
| `uv run pytest packages/maistro-core/tests/persistence -q` | **616 passed, 294 skipped** |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **66 passed** |
| `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| `uv run mypy <ci.yml's ten package srcs>` (exact CI arguments) | **Success: no issues found in 1050 source files** |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,277 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) | rc=0: **1,323 reviewed identities → 1,323 findings** (base `3c761d14db94`, candidate `7164c97f0b8a`) — no ledger amendment |
| `uv run python scripts/check-radon-baseline.py` | rc=0: **137 → 137** C-or-worse blocks |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `scripts/check-promotion-surface.py` / `check-ratchet-provenance.py` / `check-backlog-consistency.py` | ok / OK: 53 quality-JSON consumers have provenance, 0 lifecycle violations / OK: 168 items |
| `check-shipped-surface-truth.py` / `check-release-consistency.py` / `check-merge-markers.py` / `check-doc-links.py` / `check_enumerations.py` / `check-workspace-retirement.py` / `bump_version.py --check` | Matrix complete / released none, shipping 0.9.0 / no conflict markers / 0 broken links / no new enumeration gaps / 89 ledger entries match the tree / 42 sites agree on 0.9.0 |

## Round-100 evidence pack re-verified from the harness code, not the prose

`failed_promotion_checks()` was imported from `scripts/soak/run_soak.py` at
this head and applied to the committed packs:

- `evidence/m3a-round100-shakedown.json` → exactly
  **`['sustain_duration', 'exact_rc_artifact']`**;
  `hashes.git_head = ed0fe24a07a0…`, `git_clean = true`.
- `evidence/m3a-round44-shakedown.json` → the identical failing pair
  (historical `git_clean=false` at its own pre-commit head, documented).
- `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`scripts/soak/run_soak.py:67`).

## Repair this round (docs-only, evidence-accuracy)

`docs/testing/soak/m3a-soak-evidence.md`'s run-1 section pointed at machine
files that no longer exist in the tree:
`evidence/m3a-soak-evidence.json`, `evidence/metrics.jsonl`,
`evidence/replica-1820{1,2}.log`. Verified: the files were present at
`e63e820c1^` and deliberately archived out by the round-44 evidence
re-prefixing (commit message: "Replaces stale un-prefixed evidence copies
(recoverable at HEAD^ via git history) with round-44-prefixed archives per
directory convention"), but the prose was never updated. Both pointers now
record the archival commit and the recovery ref, and point readers at the
current hash-tied round-prefixed packs. No historical claim or raw evidence
value was changed. No tests added; no inventory delta (docs-only change).

## Terminal blockers unchanged and external — verified by construction

- **`sustain_duration`**: `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (`scripts/soak/run_soak.py:67`) vs the 5,400 s lane timeout, with
  background execution prohibited. Not reachable from any in-lane round.
- **`exact_rc_artifact`**: `preflight_artifact_check()`
  (`scripts/soak/run_soak.py:730`) returns `ok: false` for the
  host-uvicorn-preflight topology with "deliberately no CLI override". No RC
  designation exists: parent #89 is open, #1567/#1602 are closed and #1672
  is an open draft.

Escalation to the release owner under parent #89 is unchanged (RC freeze,
production Compose runner, ≥ 4 h soak window, provider keys, rate-limit
ownership decision). Acceptance rows 1–2 and 4–7 and 10 carry fresh,
re-verified machine evidence at the soak head; row 3 (sustained duration)
and row 8 (exact-RC soak) remain the externally blocked pair; row 9 findings
are documented in-lane (F1–F12 with earliest-broken-invariant mapping;
GitHub filing prohibited in this lane).

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced fresh and re-verified, 2 externally blocked); skipped 0; validation
errors 0; escalated 1 (RC designation under parent #89); inventory delta 0;
repairs 1 (stale run-1 evidence pointers annotated).

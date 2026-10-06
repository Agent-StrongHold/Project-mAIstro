---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: develop's 058 Gauntlet provenance wins, backlog work source re-parents onto 058 as 059

Sync round merging `origin/develop` (`a8258ee24`, nine commits: the M9-A1/C2/D2/D3/E1/F3
series, M4-B2's `058_learning_validation_provenance`, and the mako 1.4.2 /
source-map-js dependency bumps) into auto-82 at `5071e953f`. Merge committed as
`cfefa2b13`. No tests were added or removed by this branch;
`scripts/check-suite-inventory.py` reports both changed suites matching the
recorded baseline (develop's incoming suite rows arrived with its own
`docs/testing/inventory/baseline.json` row).

## Conflicts resolved

- **Migration chain — develop's 058 wins, the backlog revision re-parents past
  it as 059.** The previous sync (`56332162c`, recorded in
  `auto-82-develop-sync-058-head.md`) had re-parented the branch's backlog work
  source onto develop's `057_run_store_planner_stability` tip as
  `058_backlog_work_source`; this round develop landed its own
  `058_learning_validation_provenance` (Gauntlet audit trail, M4-B2 #118) onto
  the same `057` parent — a fourth `id` collision. Per the convention every
  prior round recorded (branch-side trailing revision re-parents onto the
  incoming develop tip): `058_backlog_work_source.py` renamed to
  `059_backlog_work_source.py`, `revision = "059"`, `down_revision = "058"`,
  docstring history extended. `alembic heads` → single `059`.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  collision narratives from both sides merged into one chronology; the walk
  target is `059` (058 now resolves to develop's learning-validation
  provenance), `get_heads() == ["059"]`, and `assert "059" in walked` added.
- `tests/migrations/test_task_admission_generation_upgrade.py`: develop's
  dynamic resolution adopted — the refused-downgrade stamp assertion now reads
  `_stamped_version() == _chain_head()` (head resolved from the version files)
  instead of a literal, so this is the last round a collision can rot that
  line; this round's collision is recorded in the narrative comment.
- `quality/vulture-baseline.json`: rule ids and match fields are identical on
  both sides; as multisets the sides differ by exactly seven rows — develop
  fixed four identities (`capabilities/invocation.py::observed_at`,
  `providers/registry.py::mark_available`/`mark_unavailable`,
  `maistro_turing/runtime/__init__.py::litellm_base_url` — fixes this merge
  takes verbatim) and added three (`personas/model.py` and
  `workspaces/model.py::_require_non_blank_identity`,
  `workspaces/model.py::_normalize_timestamps`). Resolved to develop's ledger,
  which is the exact merged multiset before the post-merge scan.

## Post-merge vulture ledger prune (the lane-authorized exact-debt-ledger repair)

The merged tree's CI-exact scan finds **1329** findings against the resolved
1332-row ledger: the three develop-added rows no longer occur, because the
branch's already-banked `_vulture_whitelist.py` entries for its own backlog
model validators (`BacklogClaim._require_non_blank_identity`,
`BacklogClaim._normalize_timestamps`, `BacklogEvent._require_non_blank_identity`,
`packages/maistro-core/src/_vulture_whitelist.py:314-316`) mark those names
used tree-wide under vulture's name-matching semantics, consuming the
same-named personas/workspaces findings. Per the gate's own instruction
("fixed debt must be pruned from the candidate ledger") and this round's lane
brief, `check-vulture-baseline.py --update` under CI's exact scan arguments
(`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) pruned
exactly those three rows (diff: 1 insertion, 4 deletions — the two long rows
re-wrap). Re-run: **exit 0**, 1329 findings, `unclassified: 0`,
`never_allowlist: 0`, no unbanked identities.

## Supply chain (pip-audit — the named CI failure this round)

Reproduced CI's exact pipeline locally: `uv sync --locked --extra dev`, `uv pip
install pip-audit`, `uv pip freeze --exclude-editable` (215 requirements),
`pip-audit --strict --format=json` (audit exit 1: `ecdsa==0.19.2
PYSEC-2026-1325`, two findings), then `scripts/pip_audit_gate.py` → **exit 0**
("1 known, all triaged in ALLOWED"; direct-dependency usage OK). No lockfile
change was needed this round — the mako/source-map-js bumps came in from
develop already triaged by their own rounds.

## Executed evidence (local PostgreSQL 18.6, CI-shaped env)

- `pytest tests/migrations/test_migration_chain.py
  test_single_migration_head.py test_capability_invocation_effect_index_migration.py
  test_task_admission_generation_upgrade.py` — **32 passed** (1:25), including
  the chain walk on a pristine database through the renumbered
  `059_backlog_work_source` and the two resolved files.
- `alembic upgrade head` on a fresh database walked `… 056 → 057 → 058 →
  059`, creating `backlog_items`/`backlog_events`/`backlog_claims` last.
- `pytest packages/maistro-core/tests` — **13479 passed, 883 skipped, 1
  xfailed, 0 failed** (4:25), including the 38-test backlog suite and the
  SQLite/Alembic schema-parity pair against the migrated head.
- `pytest packages/maistro-core/tests/backlog` — 38 passed, 16 skipped.
- ruff `check` + `format --check` — clean (3044 files).
- `check-shipped-surface-truth.py` exit 0; `check-reachability.py` (175
  unreachable of 1312, all disposed) and `check-reachability-dispositions.py`
  (50 groups) exit 0; `check-suite-inventory.py` — both suites match.
- `check-vulture-baseline.py` (CI-exact args) exit 0 after the prune.

## Residual (unchanged, two-merge — not branch-repairable)

`maistro.backlog.{__init__,model,pg_store,sqlite_store,store}` remain
unreachable pending the #99/#102 Conductor-UI/authority cutover. The
trusted-base provenance gates (`check-reachability-provenance.py`,
`check-reachability-dispositions-provenance.py`, aggregated
`check-ratchet-provenance.py`) exit 1 on exactly those five modules: the
candidate carries the dispositions and the `ratchet-authorizations.json`
grants, but `ratchet_provenance.load_authorizations` reads authorizations
**from the merge base** (`scripts/ratchet_provenance.py:478`, #534) — now
`a8258ee24` — and develop still carries zero `maistro.backlog.*`
authorization keys (verified: develop's only "backlog" grant keys are
unrelated `state_user_access::…/routes/backlog.py` rows). A candidate-side
edit provably cannot approve them ("candidate baseline edits cannot approve
them"), and inventing an import edge to appease the scanner is the cosmetic
change this round is forbidden to make. Repair remains a grants-only develop
merge of the +5 reachability authorization rows (the candidate-side rows are
already banked and exact).

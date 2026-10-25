---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-82 develop-sync round: develop numbering wins, backlog work source re-parents onto 057 as 058

This round inherited a mid-flight merge of `origin/develop` (`56332162c`) into
auto-82 `c6cd5faec` with five unresolved conflicts, resolved semantically. No
tests were added or removed by this branch; suite inventory is unchanged
against the recorded baseline (`scripts/check-suite-inventory.py`: 15 suites
ok, 27047 unique node IDs — develop's side of the merge brought its own tests
and baseline rows together).

## Conflicts resolved

- **Migration chain — develop's deployed numbering wins.** Rename detection
  had folded develop's post-base changes into this branch's renumbered copies
  (`053_learning_lifecycle_columns` → branch `054`, `054_learning_applicability_epistemics`
  → branch `055`, `055_task_admission_generations` → branch `056`,
  `056_user_model_facts` → branch `057_user_model_facts`); diffing the copies
  against `56332162c` showed only docstring/revision-id lines differ. The
  branch-side duplicates were therefore dropped and develop's originals
  restored verbatim; `043_invocation_quota_door` keeps develop's parent
  (`055_task_admission_generations`); and the one genuinely-new branch
  revision — the backlog work source (#82), which had held `053` — re-parents
  onto develop's `057_run_store_planner_stability` tip as
  `058_backlog_work_source`, per the convention every prior collision round
  recorded (branch-side trailing revisions re-parent onto the incoming
  develop tip). `alembic heads` → single `058`.
- `alembic/versions/043_invocation_quota_door.py`: docstring conflict resolved
  to develop's narrative extended with this sync's record.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  collision narratives merged; the walk target is `058` and
  `get_heads() == ["058"]`.
- `tests/migrations/test_task_admission_generation_upgrade.py`: the
  refused-downgrade stamp assertion follows the head (`058`).
- `packages/maistro-core/src/_vulture_whitelist.py`: union — the backlog
  public-surface imports stay and develop's `ExternalAgentRegistry` reference
  is added.
- `quality/vulture-baseline.json`: both sides carried the same 15 rule ids
  with identical match fields but differently partitioned findings. Resolved
  to the per-rule multiset union, then re-banked with
  `check-vulture-baseline.py --update` under CI's exact scan arguments — the
  post-sync scan has 1333 findings (trusted base: 1336 reviewed identities;
  net decrease), `unclassified: 0`, `never_allowlist: 0`.
- `packages/maistro-core/src/maistro/backlog/{model,pg_store}.py`: doc
  references to the migration renamed `053_backlog_work_source` → `058`.

## Supply chain (the named CI failure this round)

`pip-audit --strict --format=json -r <uv pip freeze --exclude-editable>` (200
requirements, audit exit 1) flagged two advisories **with fixed releases**, so
the repair the gate prescribes is the lockfile bump:
`multidict 6.7.1 → 6.9.1` (CVE-2026-104874) and `werkzeug 3.1.8 → 3.1.9`
(CVE-2026-102598) — `uv lock --upgrade-package` changed exactly those two
packages. Re-run: audit exit 1 with only `ecdsa==0.19.2 PYSEC-2026-1325`
(ALLOWED-triaged); `scripts/pip_audit_gate.py` **exit 0** ("1 known, all
triaged in ALLOWED"; direct-dependency usage OK).

## Executed evidence (local PostgreSQL 18 via the compose stack, CI-shaped env)

- `pytest tests/migrations` — **147 passed** (2:57), including the chain suite
  on a pristine database (upgrade/downgrade through the renumbered
  `058_backlog_work_source`), the two resolved files, and
  `test_single_migration_head.py` (exactly one head).
- `alembic upgrade head` on the shared database walked `… 055 →
  043_invocation_quota_door → 056 → 057 → 058`.
- `pytest packages/maistro-core/tests/backlog` with PG legs against the
  migrated chain — 53 passed, 1 skip (the no-substrate reference test).
- `pytest packages/maistro-core/tests` — 13026 passed, 954 skipped, 1 xfailed;
  `packages/hive-conductor/backend/tests` — 3407 passed, 6 skipped;
  `packages/maistro-server/tests` + turing + canvas — 1189 passed, 84 skipped.
- ruff `check` + `format --check` — clean (3008 files).
- vulture gate with CI's exact args — **exit 0** (1336 reviewed → 1333
  findings; the maistro.backlog identities remain covered by the in-source
  `_vulture_whitelist.py`, so no ledger rows are needed).
- `check-shipped-surface-truth.py`, `check-radon-baseline.py`,
  `check-promotion-surface-provenance.py`, `check-wiring-reads.py`,
  `check-enumerations-provenance.py`, `check-ac-state.py`,
  `check-model-egress.py`, `check-lifecycle-provenance.py`,
  `check-shell-execution-provenance.py`,
  `check-contract-markers-provenance.py`,
  `check-citation-status-provenance.py` — all exit 0.
- `check-reachability.py` exit 0 (175 unreachable of 1299, all disposed);
  `check-reachability-dispositions.py` exit 0 (50 groups).

## Residual (unchanged, two-merge)

`maistro.backlog.{__init__,model,pg_store,sqlite_store,store}` remain
unreachable pending the #99/#102 Conductor-UI/authority cutover. The
trusted-base provenance gates (`check-reachability-provenance.py`,
`check-reachability-dispositions-provenance.py`, and the aggregated
`check-ratchet-provenance.py`) exit 1 on exactly those five modules: the
candidate baseline/dispositions carry the rows, but
`ratchet_provenance.load_authorizations` reads
`quality/ratchet-authorizations.json` **from the merge base**
(`scripts/ratchet_provenance.py:478`, #534) — now `56332162c` itself, since
this merge absorbed develop's tip — and develop carries zero backlog
authorization keys. There is no branch-local mechanism for this one: the
module genuinely has no production caller until #99/#102/#804 wire it, and
inventing an import edge to appease the scanner is the cosmetic change this
round is forbidden to make. Repair remains a grants-only develop merge of the
+5 reachability authorization rows (the candidate-side rows are already
banked and exact).

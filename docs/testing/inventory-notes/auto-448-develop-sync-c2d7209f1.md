---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-448 — second develop sync (origin/develop c2d7209f1) and conflict resolution

Lane L448 (issue #448), CI-repair round. The branch head `c2e7c2cba74d` was
**three commits behind `origin/develop`** (merge base `e20e9f52e`), and that
gap — not the branch's own code — is what produced the red `test`,
`Quality / Reachability`, `exact-debt-ledger`, `Quality gate`,
`integration-scope` and `gates-ran` checks. This note records the second
develop sync, the two conflict resolutions, and the evidence that the reds are
green at the merged head.

## Why the branch was behind, and what the gap actually broke

`origin/develop` gained `9417bb2f4` ("publish `admission_identity`"), which
re-exports `maistro.runs.admission_identity` from
`packages/maistro-core/src/maistro/runs/__init__.py`. The branch predates that
file, so on the branch the module had **no importer anywhere in `src/`** and
`scripts/check-reachability.py` reported it as `NEWLY UNREACHABLE`:

```
NEWLY UNREACHABLE maistro.runs.admission_identity
```

That single module is the whole of the reachability red, and through
`check-reachability-provenance.py` and `check-ratchet-provenance.py` it is
also the whole of the `exact-debt-ledger` red, and through the pillar
aggregation the whole of the `Quality gate`, `integration-scope` and
`gates-ran` reds. The earlier note in this lane
(`auto-448-ci-repair-pg-audit-runtime-ddl.md`) recorded the same red as
"inherited from develop"; that reading was correct about ownership but was
taken against the stale base `e20e9f52e` — the branch was never asked to sync
again after develop landed `9417bb2f4`, so the missing import edge persisted.

Merging develop restores the import edge and the module is reachable again:
**1422 production modules, 168 unreachable, no newly unreachable module**
(baseline `quality/reachability.json` untouched by this lane — `git diff
origin/develop...HEAD -- quality/` is empty).

## The merge and its two conflicts

`git merge --no-ff origin/develop` (local commit `817f68de9fd7`, parents
`c2e7c2cba74d` + `c2d7209f1dbc`). Two files conflicted; both were resolved in
place, keeping the canonical side of each question.

### 1. `packages/maistro-core/src/maistro/persistence/pg_audit.py`

Develop's form is canonical: `ensure_schema()` probes
`to_regclass('public.audit_log')` and **no-ops when the table is absent**,
because Alembic (005 / 036 / 062) owns the table's DDL. The branch's
`c2e7c2cba` form raised `UndefinedTableError` on an unmigrated database and
`c2e7c2cba`'s earlier `34379a166` form created the table at runtime — both
break the durable-events fresh-server path (`audit_log` missing → every audit
write fails) or contradict the migrations (runtime `CREATE TABLE` produces a
table without migration 036's `server_default ''`, and then
`ensure_schema()` → `alembic upgrade head` dies with
`DuplicateTable: relation "audit_log" already exists`).

Resolution: develop's probe implementation, with the merged docstring keeping
both facts — *absent table → no-op* and *the runtime-`CREATE TABLE` experiment
was removed and why*.

### 2. `packages/maistro-core/tests/persistence/test_pg_audit.py`

Both witnesses are kept, because they pin opposite halves of the same
contract and neither subsumes the other:

- develop's `test_ensure_schema_on_unmigrated_database_is_a_no_op` — a fake
  connection asserts the probe finds no table and no DDL is emitted;
- the branch's `test_ensure_schema_never_fabricates_the_migrated_audit_table` —
  a **real** PostgreSQL database proves `ensure_schema()` does not raise and
  does not create the table (`to_regclass('audit_log')` is still `NULL`).

The branch's witness kept its node ID (only its expectation changed from
"raises `UndefinedTableError`" to "no-op, and the migrated table is still not
fabricated"), so the `packages/maistro-core/tests: +1` recorded in
`auto-448-ci-repair-pg-audit-runtime-ddl.md` is unchanged by this round.

## Counts

This round authored **no new test node**: the merge carried develop's own
tests, which develop's own notes already account for
(`971-org-workspace-extension-policy.md` `+29` core / `+20` server,
`971-develop-sync-workspace-policy-names.md` `+1` core,
`auto-292-admission-identity-publication.md` `+3` core,
`292-cli-page-contract.md` `+16` hive backend, `auto-292-b2ab.md` `+1`,
`292-cli-refusal-audit-and-degenerate-arcs.md` `+6`, and the `+2` core
`ensure_schema` witnesses from `auto-1885-3733.md`). The lane's own
contribution to `packages/maistro-core/tests` this round is therefore `+0`.

Measured: `packages/maistro-core/tests` collects **16813 → 16848** across the
merge (+35, all of it develop's); `packages/maistro-bootstrap/tests` 247,
`packages/maistro-evolve/tests` 1004 and `packages/maistro-rsi/tests` 1729 are
unchanged. `scripts/check-suite-inventory.py` reports **21 suites match the
recorded inventory; 32509 collected = 32509 unique; 0 duplicates**.

## Evidence at the merged head (`817f68de9fd7`)

| check | command | result |
|---|---|---|
| vulture ledger | `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1326 reviewed identities → 1326 findings, OK |
| reachability | `scripts/check-reachability.py` | 1422 modules, 168 unreachable, **no newly unreachable** |
| ratchet provenance | `RATCHET_BASE_REV=origin/develop scripts/check-ratchet-provenance.py` | OK (candidate `817f68de9fd7`, 53 quality JSON consumers) |
| suite inventory | `scripts/check-suite-inventory.py` | 21/21 suites match, 32509 collected, 0 duplicates |
| root suite | `pytest tests/ --ignore=tests/tools/registry` | **5399 passed, 138 skipped** (the three reachability tests now pass) |
| core (changed areas) | `pytest packages/maistro-core/tests/{extensions,runs,sandbox,tools}` | 3206 passed, 380 skipped |
| server | `pytest packages/maistro-server/tests` | 591 passed, 8 skipped |
| hive backend | `pytest packages/hive-conductor/backend/tests` | 3791 passed, 24 skipped |
| pg17 / pg18 legs | full `ci.yml` postgres leg sequence | `LEG_RESULT fail=0` on both |
| durable events | `pytest packages/maistro-core/tests/events` on a **fresh unmigrated** PG17 | 383 passed, 0 skipped |
| strike ladder | `pytest .../test_strike_tracker_conformance.py` on PG17 | 40 passed |
| wheel imports | `scripts/verify-wheel-imports.py --dist dist/ --python 3.12` | all 12 wheels import from a clean venv |
| shipped image | `docker build -f Dockerfile` + `scripts/smoke-engine-canvas.sh` | image builds; `smoke-engine-canvas: PASS` |

Negative control: restoring the pre-merge `pg_audit.py` from `c2e7c2cba` and
re-running the events suite reproduces **5 failures**
(`asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not
exist`); the merged file was restored byte-identically afterwards (empty
`git diff`). The audit-DDL behaviour this lane keeps is therefore load-bearing
for the durable-events leg, not cosmetic.

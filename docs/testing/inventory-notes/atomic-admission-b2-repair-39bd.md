---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — 39bd

Frozen scope: issue #1893 only, assigned worktree `/home/dev/Git/wt/auto-1893`,
starting HEAD `53ca1187a3a2f009329a80088f09c10635136cb0`, supplied develop
`1c55afe5189619e1cbac7e1eaf20725d4d5b6621`. Starting tree clean.
Inspected repository instructions, supplied issue/linked PR snapshot, prior
result, driver logs, codec and adjacent DTO/tests/schema, accepted
ADR-081226-a66b and ADR-083126-5e62. Assignment is interpreted as authority to
repair this staged leaf, not activate it or grant independent integration.
The Goal -> Graph -> Run -> NodeRun -> Attempt model remains unchanged.

## Fresh evidence

Logs: `.pytest_cache/repair-39bd/` (local, ignored).

- Driver logs: dependency sync, ruff, formatting and inventory pass; focused
  tests **201 passed, 3 skipped**. Skips are not PostgreSQL proof.
- Source `admission_codec.py:291` already encodes bound `task_id` from the
  existing receipt identity, matching migration 055's paired-column CHECK.
  No new identifier is invented. Tests independently assert storage shape.
- Exact requested command `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**,
  1326 findings / 1326 reviewed identities. No Vulture edit is warranted.
- `RATCHET_BASE_REV=1c55afe5189619e1cbac7e1eaf20725d4d5b6621 uv run python
  scripts/check-ratchet-provenance.py`: **failed**, exit 1. Trusted merge base
  `e46ad6708fda` rejects new reachability/disposition debt for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  This is not unbanked Vulture debt. Candidate ledger edits cannot authorize
  it (ADR-083126-5e62); no fake caller, activation, grant or gate edit allowed.

## Executed validation

All source validation below used the starting SHA; only this note changed.

- `createdb maistro_1893_39bd`, then
  `DATABASE_URL=postgresql:///maistro_1893_39bd uv run alembic upgrade head`:
  **passed**, real fresh migration chain through 061, including 055. This is
  a dedicated disposable local PostgreSQL database, not SQLite or stamping.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_39bd` and `MAISTRO_REQUIRE_PG_LEGS=1`, ran
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=.pytest_cache/repair-39bd/focused.xml`:
  **204 passed, zero skips**. Same file paths with `--collect-only -q`:
  **204 collected nodes**, saved in `nodes.log`.
- Actual production/raw pool PID pairs: **3184458/3184460** (unbound),
  **3184461/3184462** (bound), **3184463/3184464** (acknowledged), all on the
  same local Unix-socket database above. Fixture uses production JSON codecs;
  raw pool does not. Each case requires non-null `pg_pool`, checks separate
  sessions, and sees **one scoped admission row** with identical TEXT/DTOs
  across pools. Corrupt escaped-surrogate TEXT fails safely in both pools.
  Final SQL: revision **061**, **0 rows / 0 generations / 0 bound Run IDs**
  after cleanup. Database retained; no destructive downgrade exercised.
- Process-local encoder mutation forces `task_id=None` (no source-file edit),
  then `pytest.main` on the codec file with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected exit 1,
  **2 failed, 1 passed, 128 deselected**. Both bound states fail the independent
  storage assertion at `test_admission_codec.py:134`.
- `uv run ruff check .`: **passed**. `uv run ruff format --check .`:
  **passed**, 3195 files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, 15932 unique identities.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**.
  Candidate checks do not supersede the trusted-base provenance failure at
  `provenance.log:20-29`.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key -x -q`:
  **1 failed**, line 287. Rich wraps the output as `not\na hex Ed25519 private
  key`, defeating the contiguous substring assertion. This is outside #1893;
  no unrelated test weakening or repair attempted. Whether it caused hosted
  `test: failure` is **UNVERIFIED**, since no hosted traceback was supplied.
- `rg -n 'admission_codec|runs.admission_identity' packages/*/src`: only
  codec-to-types and whitelist references, no production consumer.
- `git diff --check`: **passed**.

## Acceptance review

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Frozen/slotted header, shared immutable interfaces, named columns, fresh flat mapping | Source inspection plus 204 passing codec/identity tests. Storage uses physical `request` TEXT per migration 055, not a new column. |
| v2 snapshot round trips | Unit and migrated raw/production pool tests pass in all three binding states; mutation proves regression sensitivity. |
| Owner UUID hex at storage only | Strict UUID and repr/error-hygiene tests pass; DTO retains UUID. |
| Legacy bound/unbound/partial distinguished without identity invention | Explicit receipt plus bound pair, neither-set, partial pairs, receipt-only, missing receipt and unreadable evidence tests pass. |
| Expired legacy header preserves identity absence | Named test passes; no clock or admission decision is introduced. |
| Header expiry survives malformed snapshots | Named test and malformed/duplicate JSON cases pass. |
| Header fingerprint survives partial binding | Named test passes, original fingerprint unchanged. |
| Unknown format cannot become legacy; header must match row | Unsupported/null/bool/float and scalar mismatch tests pass. |
| Tagged nonfinite snapshots retain fingerprint and evidence | Synthetic nan/inf/-inf preservation tests pass. Actual model `encode_evidence` -> `model_of`/`model_of_json` materialization with arbitrary permitted program_context is **UNVERIFIED**. |
| Strict TEXT JSON and safe errors | Duplicate/nonobject/bare nonfinite, lossy numeric, nesting, Unicode and suppressed parsing-chain tests pass. |
| Raw and production JSON codecs | Three real migrated PostgreSQL tests pass, no skipped/fake DB legs. |
| Stage boundaries | No source, SQL writer, HTTP, queue, assessment, fingerprint, scheduler, authorization or policy edits. |
| Production reachability / unchanged full required CI | **Not established**: no consumer and trusted-base provenance fails; full required hosted CI **UNVERIFIED**. |

Also **UNVERIFIED**: authorized principals/Workspace/Project and registered
Graph admission; Run `json_of(run)` TEXT-to-JSONB object insertion; live
inclusive expiry/409 ordering; transaction/crash/dispatch guarantees;
migration downgrade/adoption. Synthetic DTO rows prove codec storage shape,
not these broader integration contracts. These must not be claimed as
reachable production behavior from this internal staged leaf.

## Handoff — BLOCKED

Only this evidence/inventory note changed; no tests added and no source repair
was warranted by the focused evidence. In particular Vulture already passes:
amending that ledger cannot repair the independently failing provenance gate.
No ledger/grant edits, cosmetic source edits, fake consumers, activation, or
GitHub mutations were performed. Existing work is preserved.

Next action requires the integration owner: genuine coordinated consumer
wiring or separately landed trusted-base authorization for the two modules.
That is outside this codec-only repair scope. Route the reproduced CLI failure
to its owner and obtain the actual hosted test traceback before attribution.
Do not redispatch unchanged #1893 work as a Vulture repair.

Progress: checked **1** issue; done **1** validation/handoff; skipped **0**
issues; errors **2** unresolved checks (provenance and unrelated CLI test).
This checkpoint is a blocked local handoff, not integration approval.

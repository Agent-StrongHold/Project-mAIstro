# Issue #1893 repair handoff — 0c5de62f

## Scope and decision

Only #1893 was processed in `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Starting source SHA: `bae51b579dcb855faaf375bf83b9918af88b0296`.
Frozen develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial tree was clean. No fetch, merge, GitHub mutation, source change, ledger
change, or activation occurred. This report is the only changed file.

Read repository instructions, supplied check-0 through check-4 logs, the issue
body and captured check evidence in dispatch-context.json, previous result,
codec/identity implementations and adjacent tests. Read accepted ADRs
081226-a66b (canonical lifecycle), 082526-7f02 (immutable admission provenance),
and 083126-5e62 (protected-base quality authority).
The issue's inactive-leaf constraint does not authorize a reachability exception.
No competing scheduler, identity, execution, or authorization authority was added.

**BLOCKED:** the required trusted-base provenance gate still rejects both
admission modules. Vulture passes; no Vulture repair is warranted. The limited
Vulture-ledger exception cannot authorize reachability/disposition edits.
No actual assigned-head test failure was supplied or reproduced.

## Fresh commands and outcomes

Commands used 1200-second timeouts. Logs are under
`/home/dev/maistro/jobs/0c5de62f76fd4a00aef1d4816bf3fc06/`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings / reviewed identities; worker-vulture.log |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two unauthorized dispositions; worker-provenance.log |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, 3 database skips; worker-focused.log |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes, no duplicate evidence; worker-inventory.log |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; worker-shipped.log |
| `uv run alembic upgrade head` with DATABASE_URL targeting the new disposable DB below | PASS: real chain from empty database through 062; worker-migration-corrected.log |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q --junitxml=<job>/worker-pg.xml -o junit_family=legacy` with both test DSNs and MAISTRO_REQUIRE_PG_LEGS=1 | PASS: 204 passed, zero skipped in 1.48s; worker-pg.log |

An initial migration invocation used MAISTRO_DATABASE_URL rather than DATABASE_URL
and failed before connecting with `ConfigError: No database configured`.
The corrected invocation above succeeded; both logs are retained. An initial
lookup of migrations/env.py found no file; alembic.ini resolved alembic/env.py.
These were validation setup errors, not source defects.

## Database evidence

Created only disposable database `maistro_1893_0c5de62f` in the existing lane
container `auto-1893-pg` (PostgreSQL 18.6, localhost port 15498). Existing databases
were not touched. DATABASE_URL, MAISTRO_TEST_DATABASE_URL and MAISTRO_TEST_PG_DSN
all named this database. Production pg_pool was non-null and registered the
production JSON codecs; a separate raw asyncpg pool read the same committed rows.
No downgrade tests or schema recreation substitutes were used.

JUnit properties record server identity `172.17.0.9/32:5432` and distinct backend
PIDs for each state: unbound 28096/28097, bound 28098/28099, acknowledged
28100/28101 (production/raw). Each state persisted exactly one admission row.
Raw and production mappings equaled the encoded parameters, including snapshots
and both binding columns. Each snapshot column was independently corrupted with
escaped-surrogate TEXT; both pools produced a safe typed failure while preserving
the header fingerprint. Final SQL queried revision 062 and zero task_idempotency
rows (worker-pg-residue.log). The empty disposable DB is retained for handoff.

## Acceptance audit

| Criterion | Evidence / limit |
| --- | --- |
| Exact public interfaces, immutable header and #1851 constructors, six decode codes | Source and focused tests inspected; all 204 focused nodes passed. |
| Named SQL columns, strict UUID .hex storage, signed timestamps, fresh flat mappings | Owner-token, generation, scalar, encode tests pass; live INSERT/read round trips pass for all three states. |
| No inferred legacy identity; bound/unbound/partial/receipt-only distinctions | Legacy tests pass, including bound pair without receipt rejected rather than inventing the receipt required by the DTO. |
| Header mismatch rejected; expiry/fingerprint survive malformed full records; unknown format fails closed | Header separation, mismatch and format tests pass. Inclusive expiry/409 assessment remains consumer C/F2 scope, not B2 behavior. |
| Strict TEXT JSON, duplicate/nonobject/bare-nonfinite rejection, safe errors | JSON/precision/nesting/Unicode tests pass; real PG corrupt-TEXT cases pass through both pools. |
| Tagged program_context and stored fingerprint preserved | Byte/tag/fingerprint tests pass. Actual evidence-json encoder to model_of/model_of_json materialization and original-model fingerprint generation remain UNVERIFIED; fixtures hand-construct tags and fingerprints. |
| Migrated raw/production pool contrast and matching DB identity | Proven above: 204 passed, zero skipped, real 001→062 chain, distinct sessions, zero residue. |
| Run JSONB remains an object; authorized principals, Workspace/Project and registered Graph | UNVERIFIED by this DTO-only suite; it performs no Run admission or Run payload INSERT. |
| No SQL/HTTP/queue/clock/claim/scope/policy behavior changes | Source inspection confirms mapping-only leaf; no implementation edits this round. |
| Runtime reachability | NOT satisfied: source search finds only codec-to-identity import and Vulture whitelist import. Source explicitly documents inactive leaf. Tests are not production consumers. |
| Focused pytest, lint, format, mypy and truthful inventory | Fresh checks above pass. No tests added or removed, so no inventory delta required. No new mutation/pre-fix claim. |
| Unchanged full required integration CI; no gate workaround | BLOCKED by provenance; full integration CI UNVERIFIED. No workaround made. |
| Coordination/base ownership and activation choices | External coordination UNVERIFIED; dispatch authorizes only this repair, not integration or activation. |

## Required next action

`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` introduce the rejected modules.
The enforcing job is `.github/workflows/vulture-ratchet.yml:77`.
A candidate cannot grant itself trusted-base authorization. An externally
coordinated integration/base decision consistent with #1893 is required; this
worker cannot resolve that by editing policy, adding fake callers, or activating
a consumer outside scope.

The frozen dispatch captures four `test` checks: failure on
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, success on
`5d835338f7fa45b62d6361c9f3eddc5faf14284a`,
`fcc8b437f209a35aa68a61d6f0a5387414938355`, and
`d0a03c8db5c49c4756a1dc231a7bdc31f731f105`. None names the assigned SHA;
all have null summaries. Generic `test: failure` remains UNRESOLVED without an
assigned-head failing step/node/traceback. CI's test job excludes core unit
suites (`.github/workflows/ci.yml:574-612`), so focused success is not proof of
that whole job. Do not manufacture a code repair from this status label.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required
gate (plus corrected validation setup error). Next: external coordination and
assigned-head CI evidence. Report committed locally as a blocked handoff.

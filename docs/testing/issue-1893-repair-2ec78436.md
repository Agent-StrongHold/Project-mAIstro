# Issue #1893 repair — job 2ec78436

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `741b38eb11cb3943de7d16480b79daee43e82483` (resolved; clean).
- Assigned base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- One item: issue #1893 and its supplied CI repair evidence. No other issue/PR
  is an implementation target; no remote mutation or policy/ledger changes.
- Production review scope: admission codec, prerequisite admission identity DTO,
  their tests, governing ADRs, and exact CI gates. Edit scope initially this
  evidence report; code/test edits only for an observed in-scope defect.

## Initial evidence and ambiguity

Read the supplied dispatch issue body and prior result e22b72b1. Driver logs
check-0 through check-4 report dependency sync, lint, formatting, 346 passing /
3 skipped focused tests, and inventory success (16567 core nodes). These are
reported driver results, not independent execution by this worker.

The supplied `test: failure` has no failing node or traceback. Do not assume a
code defect from that label. Prior result reports four provenance failures and
unverified PostgreSQL durability. Independently validate before any repair.
Stage-only scope remains: no production activation or competing execution path;
no reachability grants/baselines may be changed in this round. The explicit
Vulture exception applies only if the exact scan identifies retained debt.

## Progress

- Snapshot and initial evidence review complete.
- `origin/develop` resolves to the assigned base, with no local newer grant.
- Exact requested Vulture scan: PASS, 1322 reviewed findings, zero unclassified;
  no ledger amendment is justified.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1), reproducing four trusted-base errors: new unreachable modules
  and new dispositions for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`. Other provenance subgates pass.
- An exploratory documentation glob `docs/adr/README*` was not found; skipped.
  Actual ADR filenames will be resolved from the existing references.
- Codec inspection confirms an intentionally staged pure mapping/DTO surface,
  not a runtime admission consumer. Do not fabricate reachability to bypass
  the demonstrated authorization blocker.
- Read the complete codec, DTO and codec test files. The current tests cover
  strict headers, binding shapes, snapshot safety and three real-pool states;
  they do not establish authorized admission or production model materialization.
- Docker is available: existing `maistro-postgres` is pgvector/pg18 on port 5433.
  Both test database variables were unset. A newly created dedicated database
  can provide fresh codec durability evidence without modifying shared data.
- Read accepted ADR-081226-69ee, ADR-082826-b601 and ADR-083126-5e62 in full:
  preserve canonical execution and opt-in consumption; candidate evidence cannot
  authorize its own quality expansion. No activation or authorization workaround
  is appropriate. The prior request to resolve BLOCKED cannot override these.
- CI `test` job runs other package/root suites, not the focused core files.
  Its unspecified hosted failure remains unlocalized; no failing traceback is
  present in the supplied deterministic check logs.
- Some exploratory paths (root migrations/compose and pg-helper guesses) did
  not exist; skipped. Actual migration configuration is `alembic/env.py`, which
  uses the canonical DATABASE_URL resolver. No guessed Git ref was executed.

## Independent validation at the starting source SHA

No Python/test/quality files changed. Commands executed with long timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322 findings, no unbanked identities |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL; four reachability/disposition authorization errors |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; 2 source files |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1919 passed, 310 skipped; 4 aiosqlite worker-thread closed-event-loop warnings |
| `uv run alembic upgrade head` with DATABASE_URL targeting the new disposable DB | PASS; real empty-to-063 migration chain, including 055 |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs --junitxml=/tmp/maistro-1893-2ec78436-_9j5weww/codec.xml -o junit_family=legacy` with both test URLs and `MAISTRO_REQUIRE_PG_LEGS=1` | 204 collected/passed, zero skipped |

### Fresh PostgreSQL evidence

Created only `codec_1893_2ec78436` on the existing pg18 service, using its configured
local credentials without writing them to files. DATABASE_URL,
MAISTRO_TEST_DATABASE_URL and MAISTRO_TEST_PG_DSN all targeted that same database.
The later adjacent-suite invocation above did **not** inherit these variables;
its skips do not count as durability proof.

Server: PostgreSQL 18.6, `172.20.0.2/32:5432` (host mapping 127.0.0.1:5433).
Migration head queried after testing: `063`. JUnit recorded:

| State | Production PID | Raw PID | Persisted rows |
| --- | --- | --- | --- |
| unbound | 408636 | 408637 | 1 |
| bound | 408638 | 408639 | 1 |
| acknowledged | 408640 | 408641 | 1 |

All sessions reported database `codec_1893_2ec78436` and the server above.
Tests exercise committed INSERT/read through independent raw and production-codec
pools, then inject escaped surrogate storage TEXT in each snapshot column and
assert safe typed failures through both pools. Final independent SQL count:
`SELECT count(*) FROM task_idempotency` = **0**. The empty dedicated database is
left available for inspection. Migration/pytest logs and all 204 node identities
are in `/tmp/maistro-1893-2ec78436-_9j5weww/` (local artifacts, not committed).
No downgrade test or Run JSONB insertion was run. No pre-fix/mutation claim is
made: no behavior repair or new test was introduced in this round.

Additional executed gates (all exit 0):

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  — 16567 nodes, no duplicate evidence, inventory unchanged.
- `uv run python scripts/check-shipped-surface-truth.py` — complete.
- `uv run python scripts/check-reachability.py` — 1403 modules, 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py` — 50 groups.
- `uv run python scripts/check-promotion-surface.py` — 74 tolerated modules.

Those candidate-ledger checks do **not** supersede the failed trusted-base gate.
A production-source import search finds only the codec importing the DTO; no
runtime consumer imports the codec. No test or inventory count changed, so no
inventory-delta note is needed for this documentation-only checkpoint.

## Acceptance accounting

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces, six typed error codes, fresh flat encoding | Complete source inspection plus the 204 passing codec/DTO nodes; encode freshness, field validation and header mismatch tests |
| Strict storage UUID hex, signed timestamps, constructor validation, named SQL columns | Owner/generation/header tests pass; three migrated PostgreSQL state inserts pass real schema checks |
| Immutable snapshot round trips and unchanged stored fingerprint | V2 round-trip and tagged-nonfinite tests pass; full decode never recomputes fingerprint |
| Duplicate/nonobject/nonfinite JSON, lossy numeric evidence, unsafe error-chain suppression | Existing injected raw-TEXT regression cases pass, including real-PG surrogate injections |
| Legacy bound/unbound/partial/receipt-only, no invented identity | Legacy binding tests pass; bound pairs without receipt remain typed partial evidence because AdmissionBinding requires a receipt, rather than inventing one |
| Header expiry/fingerprint preserved across full decode failure; unknown formats fail closed | All named separation and unsupported-format tests pass; no clock or incoming fingerprint supplied |
| Raw/production pool equality on the same migrated database | Three states pass, independent session IDs recorded above; one row each and final total zero |
| Existing evidence-json/model_of materialization, arbitrary program_context, Run JSONB object rather than double encoding | UNVERIFIED end-to-end: codec tests use tagged dictionaries and placeholder identities; they do not insert/materialize canonical Run payloads |
| Authorized explicit principals, Workspace/Project and registered Graph kinds for positive admission | UNVERIFIED: these are codec storage tests, not positive authorized admission tests |
| No SQL mutation, queue/HTTP/policy/scope changes or competing execution authority | Source inspection confirms pure codec mapping/DTO behavior; this round modifies only this report |
| Expiry replacement and 409 precedence | UNVERIFIED here; explicitly the later consumer C/F2 scope, not B2 behavior |
| Full required integration CI and no self-authorizing baseline/grant change | FAIL: exact-debt provenance reproduces four errors; full integration CI and the unspecified hosted `test: failure` remain UNVERIFIED |
| Truthful validation and inventory | Source SHA, commands, test counts, database identities and final SQL count recorded above; no new tests or inventory changes |

## Disposition / handoff

**BLOCKED**, not a merge-ready handoff. Actual blocker:
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` add two modules without prior
trusted-base authorization. `.github/workflows/vulture-ratchet.yml:77` requires
the failing provenance gate. Do not change those ledgers, add fake callers or
activate production behavior in this leaf to force a green result.

Next action belongs to the coordinated integration/quality owner: resolve the
trusted-base prerequisite outside this lane and provide the failing hosted test
node/traceback if that failure persists. This worker has not fetched, merged,
pushed, mutated GitHub, or changed any gate/authorization. No evidence-backed
in-scope code repair was identified. Preserve the existing branch work.

Changed file: this report only. Commit it locally as the required checkpoint.
Progress: {checked: 1, done: 0, skipped: 0, errors: 1,
next: trusted-base authorization and localized hosted-test failure evidence}.


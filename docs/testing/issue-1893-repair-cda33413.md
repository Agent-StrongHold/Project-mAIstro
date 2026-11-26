# Issue #1893 repair — job cda33413

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, initially clean.
- Starting head `a08f992d5b8420450bb7a5879931e5a9caf091ca`.
- Assigned base `3c761d14db944a727fa0744444bc67cfe36d49f7`, verified to be the merge-base.
- One item: #1893 only. Inspect existing codec/identity source, adjacent tests,
  relevant ADRs and CI gates. Repair only demonstrated defects. No activation,
  competing execution authority, grant changes or GitHub mutations.
- Driver logs inspected: dependency sync, lint, format and suite inventory pass;
  codec/identity tests 201 passed, 3 skipped. PostgreSQL skips are not durability
  evidence. Prior result was read but its claims are not current verification.
- Generic `test: failure` has no failing traceback in the supplied check logs.
  Assumption: reproduce focused acceptance and named gates before considering
  any code change.

## Reproduced blocker

Executed with 1200-second timeout at the starting head:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1323 reviewed identities/findings, zero unclassified. No Vulture ledger
  amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1). Both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are new unauthorized unreachable modules and
  dispositions (169 trusted -> 171 candidate).

Logs: job directory `worker-vulture.log` and `worker-provenance.log`.
This is the enforced exact-debt-ledger provenance step, not a guessed scanner
finding or a develop sync conflict. The Vulture-only ledger exception cannot
permit reachability/disposition/grant edits. No runtime or ledger edits made.

## Additional validation checkpoint

Fresh `uv run ruff check .`, `uv run ruff format --check .` (3277 files),
targeted mypy on both implementation modules, suite inventory (16466 nodes,
zero duplicate evidence) and shipped-surface truth all passed. No tests added,
so no inventory delta is introduced.

Read accepted ADR-081426-1f7c and ADR-082526-7f02: execution remains Attempt-owned;
admission provenance is immutable, and absent identity is not invented.
The codec contains no clock, SQL execution, scheduler, HTTP mapping or claim
decision. Production-source search finds only its DTO import and a whitelist
import, not a production consumer. Activation is not an authorized repair.
A legacy task/run pair without receipt remains partial because the immutable
binding requires receipt evidence; no new receipt may be fabricated.

Reviewed complete codec and codec tests, header/record DTO constructors. The
fixtures directly construct evidence tags and placeholder principal/project
strings. Their passing tests establish representation, not authorized admission,
TaskResponse/Run materialization or Run JSONB persistence.

## Live database evidence

Docker probe verified lane-local `auto-1893-pg`, PostgreSQL 18.6 on port 15498,
user postgres, and absence of job DB `maistro_1893_cda33413`. Created only that
fresh disposable DB and ran `uv run alembic upgrade head`: PASS, actual empty
schema -> 001 -> ... -> 062. Earlier worker databases were not changed. No
schema recreation or destructive downgrade was used. The new empty DB is
retained for handoff. An initial guessed ADR filename did not exist; the
verified matching ADR files were then read.

With DATABASE_URL, MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL all set to
that DB, MAISTRO_REQUIRE_PG_LEGS=1, REQUIRE_AUTH=false and MAISTRO_DRY_RUN=1:

```
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/cda334139a65432e98ec0dc6b6564ea0/worker-pg-tests.xml
```

**204 collected, 204 passed, zero skips** (1.49s), at starting source SHA.
The production pool uses `_register_json_codecs`; the independent raw pool
reads the same migrated database. Tests exercise unbound/bound/acknowledged
rows with exact named-column equality and one persisted admission per state,
and inject escaped lone surrogates into each snapshot TEXT column. Both pools
must report safe typed failures while preserving header evidence. Independent
final SQL counts: task_idempotency=0, canonical_runs=0, canonical_projects=0;
alembic revision=062. Logs/XML live in this job directory as
`worker-migrations.log`, `worker-pg-tests.log`, `worker-pg-tests.xml` and
`worker-pg-final-counts.log`. No new mutation test or pre-fix failure is claimed.

Both pools report `maistro_1893_cda33413`, server `172.17.0.9/32:5432`.
Production/raw backend PIDs: unbound 17896/17897; bound 17898/17899;
acknowledged 17900/17901 (recorded in JUnit properties).

## Acceptance review and limits

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header, six typed decode codes, named-column interfaces, matching row scalars | Source inspected; header/scalar/missing-column/format tests passed. |
| Strict storage UUID hex, signed timestamps, immutable #1851 constructors | Owner/generation/scalar/identity tests passed; both live pools read identical flat SQL mappings. |
| Snapshot preservation and fresh mapping | Three-state byte-preservation and independent paired binding-column assertions passed; fresh-mapping test passed. |
| Legacy bound/unbound/partial, no invented identity, completed_at not authority | Legacy tests passed including receipt-only and pair-without-receipt failures. |
| Header survives invalid snapshot/partial binding, unknown format fails closed | Expiry/fingerprint/header-separation and unsupported-format tests passed. Codec makes no expiry or mismatch decision. |
| Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection, safe exceptions | Malformed JSON, numeric fidelity, nesting, Unicode and secret-hygiene assertions passed, including live corrupt TEXT injections. |
| Tagged nonfinite program_context and unchanged fingerprint | Tagged-value tests passed; codec retains tags without materializing or recomputing fingerprints. |
| Real migrated PostgreSQL with raw and production codecs, no skipped durability legs | 204 passed; same DB/server, distinct PIDs, one row per state, final residue zero. |
| model_of/model_of_json materialization, original-model fingerprint computation, Run INSERT produces JSONB object | **UNVERIFIED** here. Reviewed evidence_json contract; focused fixtures construct tags manually and do not insert a Run or materialize TaskResponse/Run. |
| Real authorized principals, Workspace/Project and registered Graph admission | **UNVERIFIED**. Direct codec row inserts are storage evidence, not authorized admission, transaction/crash or dispatch evidence. |
| No SQL mutation, queue/HTTP changes, clock, assessment, live _assess or scope utility changes | Complete codec source inspected; no implementation edits this round. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. |
| Production reachability / independent merge readiness | **BLOCKED** by the actual trusted-base gate failure. No runtime consumer found; test imports and whitelist do not establish one. |
| Full unchanged required CI and generic reported test failure | **UNVERIFIED**; focused tests pass. Captured #1945 at fcc8b437f209 has exact-debt-ledger failure with no traceback. Captured #1855 test failure belongs to its different 3f2c79a70d9e head, not this source. No current failing node supplied. |
| Coordination and activation | Assigned writer/base explicit. Captured #1325/#1855/#1945 bodies read with head qualifiers; no policy choice, activation or integration approval inferred. |

## Final commands and handoff

All Python validation used `uv run`, with 1200-second outer timeouts.
In addition to the commands above:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16466 nodes.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against candidate ledger.
- `git diff --check`: PASS.

Candidate-ledger passes do not override the trusted-base provenance rejection.
Blocking entries: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. Resolving them requires an
already-landed authorization under repository two-merge policy, or a separately
authorized real consumer integration. Neither can be manufactured by this lane.
No fetch/merge was attempted: the assigned base is already incorporated and
there is no conflict to resolve. Request the exact current failing test
command/node/traceback before assigning a speculative source repair.

Changed file: this report only. No source, test, inventory count, whitelist,
ledger, grant or gate modifications. Local commit is a blocked handoff only;
no push, PR, issue closure or other GitHub mutation.

Progress: checked 1, done 0 code repairs, skipped 0, errors 1 required provenance
gate; next: external trusted-base prerequisite and current CI test failure
traceback. Verdict: **BLOCKED**.

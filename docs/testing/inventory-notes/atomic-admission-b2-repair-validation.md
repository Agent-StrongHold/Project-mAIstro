---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 bounded repair validation — job fee6768070984aa18ca943269c130b65

Scope frozen: issue #1893 only; assigned branch `auto-1893`, starting head
`85cc9464e72c0e27f8d88565609439d6902b8d1c`, supplied develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial worktree was clean.
No GitHub mutations or activation changes are authorized.

Planned file scope: inspect admission codec, immutable identity constructors,
adjacent tests, existing B2 inventory notes, relevant ADRs and CI gates;
change only evidence-backed #1893 defects and this validation note. The explicit
vulture repair exception applies only if its exact scan finds retained debt.
No new tests yet; no inventory delta yet.

Ambiguity: dispatch reports `test: failure` without a failing node. Proceed by
reading the captured CI evidence and reproducing focused tests; do not guess a
repair. Prior reachability authorization failure remains unverified.

Progress: repository/head verified; supplied primary issue body and driver logs
read. Driver checks report 201 passed / 3 skipped (not live PostgreSQL proof),
clean lint/format and 16466 inventory nodes. Resolved local `origin/develop`
equals the supplied base; no conflict exists. The codec explicitly documents
that it has no production consumer (module lines 51–54). Existing binding fix
writes both task_id and run_id and validates receipt agreement. No speculative
source or ledger change is justified by inspection. Remaining validation results
will be recorded here before the local commit.

## Fresh measured results

At starting SHA, exact Vulture command passed: 1323 reviewed identities and
1323 findings, zero unclassified. No ledger amendment is warranted.
`RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
failed (exit 1): NEW unreachable modules and NEW dispositions for both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` lack
trusted-base authorization. Evidence: supplied job directory,
`worker-provenance.log:20–29`. This is not a develop-sync conflict and cannot
be fixed through the permitted Vulture exception.

`uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` passed
201 tests, skipped 3 PG cases (no DSN). No failing codec test reproduced.

Accepted ADR-081226-a66b and ADR-082526-7f02 reviewed: preserve canonical
lifecycle and immutable admission provenance. No competing authority or fake
runtime import will be introduced to evade the gate. Reachability resolution
requires owner action outside this leaf and cannot be self-authorized here.

## PostgreSQL validation (executed this round)

After confirming peer authentication and that the new DB name was absent,
created disposable `maistro_1893_jobfee67680` on local PostgreSQL 18.6.
`DATABASE_URL='postgresql://dev@/maistro_1893_jobfee67680?host=/var/run/postgresql'
uv run alembic upgrade head` applied the real empty-schema chain through 062.
Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` used that same URL.
With `MAISTRO_REQUIRE_PG_LEGS=1`, the focused pytest command above plus
`-o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml` executed
**204 passed, zero skipped**. No downgrade or destructive migration test ran
against an existing database.

Production/raw PID pairs in JUnit: 951392/951393 (unbound), 951395/951396
(bound), 951397/951399 (acknowledged). Each pair used the named database,
reported distinct backend PIDs and one persisted row. Server address/port
were NULL because these are Unix-socket connections. Final independent SQL
query: revision 062; zero admission rows, distinct generation IDs and Run IDs;
zero tasks, canonical_runs, canonical_node_runs and canonical_attempts.
Logs: `worker-migrate.log`, `worker-pg.log`, `worker-pg-counts.log` in the job
directory. The empty disposable database is retained for inspection.

## Acceptance evidence and limits

All ten named prospective tests executed in the 204-node run:

| Criterion | Evidence in `test_admission_codec.py` |
| --- | --- |
| Exact immutable snapshots and fresh flat parameters | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states); `test_encode_returns_a_fresh_flat_mapping` |
| UUID hex only at storage boundary | `test_owner_token_is_hex_at_storage_only`; `test_v2_generation_ids_are_strict_storage_hex` |
| Bound, unbound and partial legacy evidence distinguished | `test_legacy_binding_unbound_and_partial_are_distinct`; receipt-only and missing-receipt cases |
| No inferred identity from expiry | `test_expired_legacy_header_does_not_invent_missing_identity` |
| Header expiry survives snapshot failure | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header fingerprint survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unsupported formats and malformed scalars fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy`; scalar/mismatch/schema cases |
| Tagged evidence and unchanged stored fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` |
| Strict JSON with safe typed errors | `test_invalid_and_duplicate_json_is_rejected`; nested/lossy/surrogate injections |
| Raw/production pool TEXT equivalence | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (three live PG states) |

Inspection confirms frozen/slotted header and typed errors, signed timestamps,
named-column mapping, constructor validation, and header/full-record separation.
Production-source grep finds `admission_codec|decode_admission_record` only in
the codec itself: no runtime consumer is demonstrated. Codec fixtures use string
identities, not authorized principals/Workspace/Project/registered Graph admission.
Consequently reachable authorized admission, actual model materialization through
`model_of`/`model_of_json`, original-model fingerprinting, Run JSONB INSERT shape,
and consumer expiry/409 precedence are **UNVERIFIED** by these tests. The latter
consumer behavior belongs to later leaves; no activation is authorized here.
No pre-fix/mutation result is claimed because no code repair or test was added.

Fresh lint (`uv run ruff check .`), format (`uv run ruff format --check .`,
3277 files), and focused mypy (codec and identity modules) all passed. Logs are
`worker-ruff.log`, `worker-format.log`, and `worker-mypy.log`.

The captured PR #1945 check 114346705414 is `test: success` at source
`9922f395daa39249991f18210a6d4da68a3a76cb`, not the assigned current head.
The supplied `test: failure` has no current-head traceback and was not reproduced
by focused tests. After two bounded inspections of supplied evidence, this is
**UNRESOLVED**; do not guess an implementation repair. Full unchanged required
CI and coordination/activation approval remain **UNVERIFIED**.

Final executed checks:

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, 16466 nodes, zero duplicate identities (`worker-inventory.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: passed
  (`worker-shipped.log`). Candidate completeness does not authorize new debt.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  1918 passed, 310 skipped, 5 warnings in 51.65s (`worker-adjacent.log`). This
  adjacent run had no PG variables; skipped cases are not durability evidence.
  Warnings report aiosqlite threads encountering closed event loops, not a
  failing admission codec assertion. No unrelated SQLite repair is attempted.
- `git diff --check`: passed.

## Handoff

**BLOCKED.** Only this note changes; inventory delta zero. No implementation,
test, ledger, grant or gate was edited. No evidence-backed code repair was
identified. The independent PostgreSQL codec evidence is green, but trusted-base
reachability/disposition provenance still fails and cannot be resolved by a
candidate-side grant or by forbidden consumer activation. Next: integration-owner
resolution consistent with the two-merge authorization rule, plus the exact
current-head failing CI traceback if `test: failure` still applies.

Progress: checked 1 issue; done 0 repairs; skipped 0; errors 1 reproduced
provenance blocker. This bounded round is complete with a local documentation
commit, not integration approval. Do not redispatch an unchanged tree expecting
a Vulture ledger amendment to fix a reachability authorization failure.

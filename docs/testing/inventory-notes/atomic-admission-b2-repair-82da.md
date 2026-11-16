---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — 82da

Frozen scope: issue #1893 only, assigned worktree `/home/dev/Git/wt/auto-1893`,
starting HEAD `a9ca9eada397f4b779e1ed14d0ac0f87e8d84fac`, supplied base
`f11dfd0c559225b64098252677e843f23c3be299`.
Inputs: supplied dispatch-context.json, check-0 through check-4.log, prior
f856 result if present. No remote enumeration or GitHub mutation.
Potential edit scope: admission_codec.py, test_admission_codec.py, this note,
and quality/vulture-baseline.json only if the exact requested scan evidences
reviewed identity drift. Adjacent immutable identity types, migration 055,
production store, ADRs and CI configuration are inspection/validation only.

Initial state: clean; exact starting HEAD verified. Driver logs report lint,
format, 201 passed/3 skipped, inventory success. These are not independent
acceptance proof. Prior reported task_id/run_id mismatch and reachability debt
will be checked against current files, not assumed still present.

Ambiguity: dispatch says `test: failure` without a current failing node. Proceed
by reproducing focused tests including PostgreSQL and inspecting available
captured CI evidence. Historical branch-wide differences are not repair scope.
No production activation or new execution authority is authorized.

## Inspection checkpoint

The reported task_id defect is already fixed at admission_codec.py:290;
_v2_binding also rejects one-sided or mismatched binding pairs. No new source
repair is justified by that historical finding. The exact requested vulture
scan passed: 1328 reviewed identities / 1328 findings, no unbanked or eliminated
identities; no ledger amendment is needed or justified.

Fresh `RATCHET_BASE_REV=f11dfd0c559225b64098252677e843f23c3be299 uv run python
scripts/check-ratchet-provenance.py` **failed** on unauthorized reachability
and disposition additions for `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`; effective trusted merge base is af799688335f.
This is not vulture debt and the lane does not permit changing those ledgers,
grants or gates. Production import search confirms the codec has no consumer.
Do not add a fake caller or activate another leaf to evade this failure.

Read accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601, 082826-d9f5:
immutable admission provenance, Attempt execution identity, one canonical
consumer, and RunStore authority remain unchanged. An initial guessed ADR
filename was not found; skipped, then used the actual discovered path.

Created disposable local PostgreSQL 18 database `maistro_1893_82da` and ran
`DATABASE_URL=postgresql:///maistro_1893_82da uv run alembic upgrade head`
successfully through the real migration chain. Log: job repair-migrations.log.
The generic hosted `test: failure` has no supplied failing node; current
focused and adjacent execution below will determine reproducibility.

## Executed validation (unchanged production source at starting SHA)

Artifacts: `/home/dev/maistro/jobs/82dad920bda24d659202d9f4aaf27f27/repair-*`.
No source or test changes were needed; this note is the only changed file.

- Set `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_82da`,
  `MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_82da`, and
  `MAISTRO_REQUIRE_PG_LEGS=1`. Ran `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, no skips**. Collected identities saved in repair-focused-nodes.txt.
- The three real-DB tests used distinct production/raw backend PID pairs
  **3377263/3377264**, **3377265/3377266**, **3377267/3377268** (unbound,
  bound, acknowledged), all on the same disposable DB via local Unix socket.
  Each asserted exactly one persisted scoped row, byte-identical TEXT in both
  pools, complete DTO equality, then deleted its scoped row. The fixture uses
  production `_register_json_codecs` and was not None. These tests do not
  establish authorization or Run insertion.
- Same DB environment: `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **2118 passed, 3 skipped, 6 warnings**.
  Warnings are aiosqlite worker callbacks after loop closure. Skips are not
  counted as durability proof. Final SQL inspection: migration **060**;
  task_idempotency **3 rows**, **0 distinct generations**, **2 distinct Run IDs**
  (adjacent legacy test residue, not v2 codec rows).
- Regression sensitivity: an isolated `uv run python` invocation temporarily
  replaced `encode_admission_record` in process with a wrapper assigning
  `task_id=None`, then invoked pytest on the bound/acknowledged round-trip
  nodes. Both **failed at test_admission_codec.py:134**, `None != 'rcpt-1'`.
  The harness asserted pytest TESTS_FAILED. No source files were mutated.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  **3166** files. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **15610** nodes, delta **0**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, **1328/1328**.
- `uv run python scripts/check-reachability.py`: passed candidate scan,
  **171/1363** unreachable modules. `check-reachability-dispositions.py`:
  passed candidate ledger, **171** modules. `check-promotion-surface.py`:
  passed, **74** tolerated modules. These candidate checks do **not** negate
  the trusted-base provenance failure recorded above.
- `git diff --check`: passed.

## Acceptance audit

All following codec tests executed in the 204-node focused run, not merely
collected or inherited from earlier reports:

| Criterion | Evidence / limit |
| --- | --- |
| Immutable v2 DTO and fresh named flat SQL mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping`; frozen/slotted header and #1851 constructors inspected |
| Storage-only strict owner/generation UUID hex; safe errors | `test_owner_token_is_hex_at_storage_only`, `test_v2_generation_ids_are_strict_storage_hex`, `test_decode_error_scope_key_is_only_a_validated_hash`; invalid snapshots suppress unsafe exception chains |
| Legacy bound, unresolved, partial and receipt-only remain distinct; no inferred identity | `test_legacy_binding_unbound_and_partial_are_distinct`, `test_legacy_receipt_only_row_is_partial_not_unbound`, `test_legacy_bound_pair_without_receipt_is_partial_never_fabricated`, whitespace evidence tests |
| Expired header preserves scalar facts without inventing identity | `test_expired_legacy_header_does_not_invent_missing_identity`; codec takes no clock |
| Header survives malformed snapshot and partial binding | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`, `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown formats and mismatched headers fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, scalar mismatch and signed timestamp tests |
| Existing evidence tags and fingerprint remain unchanged | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`, round-trip snapshot assertions; no fingerprint recomputation in codec |
| Duplicate keys, nonobject/bare nonfinite JSON rejected; bad evidence not silently changed | `test_invalid_and_duplicate_json_is_rejected`, lossy-number, nesting and UTF-8 regressions |
| Raw and production pools read identical TEXT under actual migrated constraints | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (3 states), sessions/counts above; historical task_id defect is no longer reproducible |
| No new admission decision, SQL mutation, queue/HTTP policy or execution authority | Source inspection: codec only maps records; no runtime consumer; no production changes this round |
| Model materialization through model_of/model_of_json; provenance encode_evidence; Run INSERT text-to-JSONB object rather than double encoding | **UNVERIFIED** by this inactive leaf's tests; these do not materialize task/Run models or insert a Run |
| Positive authorized principal/Workspace/Project/registered Graph admission | **UNVERIFIED**: codec DB tests use DTO strings, not a live admission path |
| Live inclusive expiry / changed-payload 409 ordering | **UNVERIFIED**, belongs to consumer C/F2; only preserved header evidence proven here |
| Full required hosted CI / merge readiness | **UNVERIFIED**; supplied generic `test: failure` not reproduced in scoped suites; provenance gate independently fails |

## Handoff / disposition

**BLOCKED**, not merge-ready. No actual new codec failure or vulture identity
mismatch justifies speculative source or ledger edits. The reproducible blocker
is trusted-base reachability/disposition authorization for the inactive #1851
and #1893 modules. Resolving it needs coordinated integration/ownership outside
this bounded codec repair, not fake callers, unrelated activation, or a
candidate-approved grant. A failing hosted test node/log is still needed to
repair the supplied generic CI `test: failure`; it remains UNRESOLVED.

No GitHub mutations, branch merges, policy changes, grant edits or discarded
work. Progress: checked 1 issue; validation/handoff done 1; skipped 0 issues;
errors 1 blocking provenance gate. Next: owner-coordinated trusted integration
and concrete hosted test failure evidence. Commit this note locally; no
integration approval is implied.


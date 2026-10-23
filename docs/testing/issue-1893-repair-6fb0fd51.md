# Issue #1893 repair — job 6fb0fd51

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `cd3717f9addb10ab0915631e80c3391b18142b5d`; supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064`.
- One item: issue #1893 B2 codec and reported `test` / exact-debt-ledger failures. No other issues or PRs will be processed.
- Initial worktree was clean; no incoming changes need salvage.
- Inspection scope: repository instructions, relevant admission ADRs, codec/identity implementation and adjacent tests, CI gate scripts/workflows, supplied job evidence. Edit scope: this validation report; codec/test/ledger repairs only if actual reproduced evidence warrants them. Reachability grant/baseline edits are not authorized.
- Ambiguity: dispatch says `test: failure` without a failing node or log. Treat it as unverified until reproduced, not permission for speculative repairs.
- Driver logs inspected: check-0 dependency sync succeeded; check-1 ruff passed; check-2 format passed (3301 files); check-3 324 passed / 3 skipped; check-4 inventory passed (16543 nodes). These are driver observations, not live PostgreSQL proof.

## Progress

- `uv sync --locked --extra dev`: PASS, 256 resolved / 214 checked.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings / zero unclassified. No Vulture ledger repair is warranted.
- Resolved the supplied base with `git rev-parse --verify ...^{commit}` before using it. `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), two unauthorized admission-module dispositions and two unauthorized unreachable-module additions. Candidate 171 versus trusted 169. Other provenance subgates passed.
- Import search confirms no production consumer of `admission_codec`; `admission_identity` is imported by the codec and Vulture whitelist only. No fake caller or production activation will be introduced to bypass this evidence.
- Neither PostgreSQL test environment variable is set. No database durability evidence claimed yet.

No production change or activation authorized. The reproduced blocker is reachability provenance, not the Vulture per-identity ledger.

## Focused validation at the starting source SHA

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`: PASS, 327 nodes, 324 passed / 3 PostgreSQL skips in 1.85s. No failing test reproduced.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16543 collected nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.

Read repository instructions and accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Reconciliation: retain `Goal -> Graph -> Run -> NodeRun -> Attempt`; immutable admission evidence is not execution authority, and candidate banking cannot approve its own reachability expansion. B2 remains an inactive contract leaf; implementing a production consumer is explicitly outside the assigned issue.

## Adjacent validation

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: PASS, 2229 nodes, 1919 passed / 310 skipped / 5 warnings in 49.36s. Warnings are aiosqlite worker threads encountering closed event loops in existing `test_sqlite_store.py` tests. No test failure reproduced; no unrelated SQLite repair attempted.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger, 1403 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against candidate ledger, 50 groups / 171 modules. Neither candidate-ledger pass overrides the failing trusted-base provenance check.
- `git diff --check`: PASS.

## Acceptance audit

Executed test names below are in `packages/maistro-core/tests/tasks/test_admission_codec.py`. They establish a library contract, not reachable production admission. Source and test bodies were inspected rather than relying on test names alone.

| Criterion | Evidence and limits |
| --- | --- |
| Frozen/slotted header; strict supported version, hash and signed timestamps; supplied header must match row | Header dataclass/source inspection; `test_header_scalar_mismatch_is_invalid_header`, `test_invalid_scalar_headers_fail_closed`, missing-column cases PASS. |
| Immutable DTO / fresh flat SQL mapping / snapshot preservation | `test_v2_round_trip_preserves_all_snapshot_bytes` in three states, `test_encode_returns_a_fresh_flat_mapping`, adjacent identity constructor tests PASS. Canonical snapshot text preserved; arbitrary noncanonical byte formatting is intentionally normalized. |
| Storage UUID hex only; safe typed failures and validated scope | `test_owner_token_is_hex_at_storage_only`, `test_v2_generation_ids_are_strict_storage_hex`, `test_decode_error_scope_key_is_only_a_validated_hash` PASS. Codec suppresses unsafe parsing chains. |
| Bound, unresolved, partial and receipt-only legacy remain distinct; no inferred identity | `test_legacy_binding_unbound_and_partial_are_distinct`, missing-receipt, receipt-only and unreadable evidence cases PASS. |
| Header/full-decode split preserves expiry and fingerprint without assessment | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`, `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` PASS. No replacement or 409 decision claimed. |
| Unknown formats fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` PASS for seven invalid values and header mismatch. |
| Strict JSON rejects duplicates, nonobjects, bare nonfinite values and corrupt evidence | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting, lossy numeric and invalid UTF-8 cases PASS. Invalid TEXT is injected at the row boundary. |
| Tagged nonfinite context survives without recomputed fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` PASS for nan/inf/-inf. Fixtures use pretagged data and a fixed fingerprint: production evidence-json encoding, original-model fingerprinting and model_of/model_of_json materialization remain UNVERIFIED end to end. |
| Named SQL fields; paired task/run binding; legacy completed_at is not authority | Independent mapping assertions in round-trip cases and v2 partial-binding tests PASS; `test_legacy_completed_at_is_never_read` PASS. |
| Raw versus production pool TEXT equality on real migrated disposable PostgreSQL | Three `test_raw_and_production_pool_codecs_read_identical_text_snapshots` cases SKIPPED. UNVERIFIED this round; no live DB session identities, migration-chain/downgrade evidence, or final SQL counts claimed. |
| Authorized principals / Workspace / Project / registered Graph; Run JSONB object insertion | UNVERIFIED. DTO fixtures contain string identities, not an authorized production admission path; no Run payload INSERT is exercised by these codec tests. |
| No SQL mutation, clock, assessment, queue/HTTP or policy changes | Codec source is mapping-to-DTO/mapping only; import search finds no production consumer. This round changes only this report. Canonical execution authority remains untouched. |
| Focused checks, inventory, full required CI and coordination | Focused checks above PASS, unchanged inventory 16543. Trusted-base provenance FAILS. Full integration CI and remote unspecified `test: failure` are UNVERIFIED; no owner/activation release is inferred. |

No new tests or source changes were introduced, so no inventory-delta note or pre-fix/mutation-failure claim is appropriate. Prior live-PG and full-CI claims are not carried forward as fresh evidence.

## Disposition

**BLOCKED.** Concrete failing locations are `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. The Vulture-only repair exception does not authorize editing these reachability policies, and Vulture has no reproduced mismatch. There is no merge conflict to resolve at this head.

Only `docs/testing/issue-1893-repair-6fb0fd51.md` is changed in this round. No source, tests, ledger, grants or gates were changed; no fetch, merge, push or GitHub mutation was performed. Commit this report locally as the handoff, without claiming repair completion.

Next: the integration/governance owner must resolve trusted-base reachability authorization through the existing two-merge process or provide explicitly authorized integration scope. Provide the SHA-qualified failing CI test log/node before another speculative test-repair dispatch. Re-run live PostgreSQL and full integration acceptance after that prerequisite is resolved.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 blocking gate; next: owner resolution of the trusted-base blocker and concrete test-failure evidence.

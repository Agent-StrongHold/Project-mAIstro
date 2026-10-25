# Issue #1893 repair — 29c430e9

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD verified: `227d8f688bf118ddee2989ba2f545748452d3398`; working tree initially clean.
- Dispatch base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Only issue #1893: admission codec, prerequisite immutable identity types, their tests, existing CLI/pack regression tests named by the driver, and relevant quality gates. No other issue or PR processing.
- Evidence snapshot: job `29c430e9c28c42f5b65e3f961c77b848` dispatch-context.json and check-0 through check-4.log; supplied prior result.
- Planned writable file: this validation/handoff note only unless an actual in-scope failure establishes a necessary repair. No baseline/grant changes to bypass reachability.

## Ambiguity and assumption

The generic `test: failure` has no failing node in the assignment. Treat it as unverified pending supplied logs and fresh focused validation. Writer role applies; no production activation or GitHub mutation is authorized. Previously reported passes are not new evidence.

## Progress

Initial repository instructions and full primary issue body inspected. Supplied driver logs inspected: dependency sync, ruff and format pass; focused four-file run reports 346 passed / 3 skipped; inventory matches 16567 nodes. Prior result explicitly reports BLOCKED, not integration readiness. Both dispatch base and local origin/develop resolve to `ac7370141e8e61bd6f352bca35ed0b505104aadb`.

Source inspection confirms admission_codec.py explicitly remains an inactive contract leaf, with header/full-record separation, strict UUID storage, named fields, and no SQL mutation or runtime consumer. Its PG test uses real pools only when both DSNs are supplied; the three driver skips cannot establish durability. Fresh validation reproduced 346 passed / 3 PG skips. Exact Vulture command passed (1322 reviewed identities = 1322 findings, zero unclassified), so no ledger amendment is warranted. `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` exited 1: both admission modules are NEW unreachable modules without trusted-base authorization and both dispositions are unauthorized. The other provenance legs passed. This is an actual required-gate blocker, not a guessed scanner finding.

## Independently executed commands

All validation ran against starting HEAD plus this documentation-only note, with 1800-second command timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322 reviewed identities and findings; no unbanked identities. |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1; two unauthorized unreachable modules and two unauthorized dispositions. |
| `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -rs` | 346 passed, 3 skipped; all skips require PostgreSQL DSNs. |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -rs` | 1919 passed, 310 skipped, 5 warnings; 47.32 seconds. Warnings are aiosqlite worker threads reporting closed event loops, not failed tests. Skipped durability legs are not evidence. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3301 files already formatted. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; two source files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 16567 unique collected nodes, no duplicate evidence. |

## Acceptance audit

- **Immutable interfaces, six error codes, named columns, fresh flat mapping, signed timestamps, UUID hex:** source inspection and passing codec/identity tests establish the isolated DTO contract. Header frozen/slotted shape is source-verified.
- **Snapshot bytes and owner storage:** `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound/bound/acknowledged; independently asserts both binding columns required by migration 055, not just encode/decode agreement. `test_owner_token_is_hex_at_storage_only` passes.
- **No invented legacy identity:** bound/unbound/partial, receipt-only, missing receipt, unreadable evidence and ignored completed_at tests pass. A pair lacking a receipt fails rather than inventing the receipt required by the canonical binding constructor.
- **Header before full decoding:** expiry/fingerprint preservation, expired scalar evidence, header mismatch and unsupported-format tests pass. The decoder accepts neither clock nor incoming fingerprint. Replacement and 409 precedence remain consumer C/F2 obligations, UNVERIFIED here.
- **Strict snapshots and safe errors:** duplicate/nonobject/bare nonfinite, excessive nesting, lossy numeric and invalid Unicode injection cases pass. Tests directly inject corrupt row values and assert typed safe errors. Tagged fixtures survive unchanged without fingerprint recomputation.
- **Production evidence-json/model_of materialization, arbitrary permitted program_context:** UNVERIFIED by these hand-built tagged fixtures; no materialization integration is introduced in B2.
- **Real raw/production PostgreSQL pools on migrated disposable schema:** UNVERIFIED this round. Three codec cases skipped at `test_admission_codec.py:470`; no DB session identities, migration/downgrade results or final SQL counts produced. No fake or skipped PG evidence is counted.
- **Run JSONB object storage and actual authorized principal/Workspace/Project/Graph:** UNVERIFIED by DTO-only tests; no Run admission occurs in these fixtures.
- **Stage constraints:** source inspection confirms pure mapping conversion, no SQL mutation, queue, HTTP mapping, claim/assessment, scope utility or legacy policy changes. No production activation was attempted.
- **Runtime reachability:** NOT SATISFIED. Production import search finds only codec -> identity and `_vulture_whitelist.py:105`; no production consumer. `admission_codec.py:51-54` explicitly documents inactivity. Tests, whitelist references and exports do not establish runtime wiring.
- **Common validation:** scoped tests, lint, format, mypy and suite inventory pass with the noted skips. Required exact-debt-ledger provenance fails. Full hosted CI, new mutation/pre-fix execution and external coordination/activation release are UNVERIFIED. No new transaction/crash/dispatch invariant is claimed.

## Architecture and reconciliation

Read repository instructions, docs/README.md, docs/quality-gates.md, accepted ADR-081226-a66b and ADR-083126-5e62. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; DTO construction grants no admission authority. Candidate evidence cannot authorize itself. The Vulture-ledger exception does not authorize reachability or disposition amendments. An attempted historical ADR filename `ADR-082526-7f02-admission-provenance-is-immutable.md` was not found; skipped, not claimed as read.

## Handoff

**BLOCKED.** Existing unauthorized entries remain at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`; `.github/workflows/vulture-ratchet.yml:77` runs the failing gate. Resolve trusted-base authorization/coordination outside this worker before a permitted integration sync. Do not add fake runtime imports or candidate grants to turn the gate green.

The generic hosted `test: failure` is UNRESOLVED: supplied logs and fresh focused/adjacent tests do not reproduce it, and no assigned-head failing node was established. Obtain the exact failing hosted step before repairing unrelated tests. No merge conflict existed, so conditional conflict-repair instructions did not apply.

Only this handoff note changed. No tests were added/removed; no inventory-delta update is necessary. No source, ledger, grant or gate changes were justified. Local commit is a blocked handoff, not merge approval or closure.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Next: owner-controlled reachability resolution and attributable hosted test-failure evidence.

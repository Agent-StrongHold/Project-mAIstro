# Issue #1893 repair checkpoint

Frozen scope: issue #1893 only; assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, starting head `5fc4a0d9ec21fb7ab6ca07cd8dd4378f4d0733a0`, dispatched base `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Inputs are the captured dispatch-context.json and check-0.log through check-4.log in job `189c1e36de224fd2b274d40ac9df5d44`. No GitHub mutation or issue re-enumeration.

Captured evidence reviewed: driver check-0 through check-4 pass (dependency sync, lint, format, 346 passed/3 skipped, inventory 16567). Prior result is BLOCKED, not an approval. Captured issue explicitly forbids activating the codec or changing reachability grants to make the slice green. Local origin/develop resolves to the dispatched base; no develop-sync conflict exists. Captured check-run output supplies no failing test traceback for this head. Assumption: validate focused tests and exact-debt gates; do not speculate about the unspecified hosted test failure.

Executed exact Vulture command: PASS, 1322 findings, 0 unclassified; no ledger amendment justified. Executed `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), two unauthorized unreachable modules and two unauthorized dispositions (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`). Source import search finds only codec-to-identity and Vulture whitelist imports, not a production consumer. Blocker is reproduced, not inferred from prior reports. Fixing it by activation or reachability ledger changes conflicts with this lane's explicit scope; no such changes will be made.

Focused pytest rerun: 346 passed, 3 skipped (3.13s). Skips are all raw/production PostgreSQL contrast cases; this run does not prove durability. Reviewed ADR-062 (including retired run_graph caveat), ADR-082526-7f02 (immutable admission provenance), ADR-082826-b601 (one canonical consumer), both admission source modules and codec test fixtures. No competing executor/store/auth path will be introduced. The codec intentionally has no clock, fingerprint recalculation, SQL mutation, or assessment. Existing fixture snapshots are hand-built tagged objects, not materialized TaskRequest/TaskResponse/Run models; their passing round trip is not model materialization or Run JSONB evidence.

Further executed validation: root Ruff check and format check PASS (3301 files); focused mypy PASS (2 source files); core inventory PASS (16567 unique nodes). Adjacent tasks + runs suites: 1919 passed, 310 skipped, 5 warnings in 48.56s (2229 nodes). Warnings are aiosqlite worker-thread `RuntimeError: Event loop is closed` attributed to test_sqlite_store.py; pytest exited 0. No evidence links those warnings to the unspecified hosted failure, and SQLite lifecycle repair is outside this issue. No test changes, so inventory delta is zero and no new inventory note is needed.

Initial status: clean; exact starting head verified. Writer assignment assumed (explicit repair lane), despite generic verifier instructions also present. Inspect captured criteria, architecture, adjacent tests, and actual failures before choosing source changes. Only issue-related source/tests and this report are in scope; new tests require an inventory note. No quality authorization or reachability ledger edits permitted.

## Final disposition: BLOCKED

Only this report changed in this round; source, tests, inventory, workflows and quality ledgers are unchanged. This is an evidence handoff, not an implementation fix or integration approval. The actual failing gate cannot be repaired within the permitted B2 scope. A separately authorized trusted-base resolution is required; do not add fake imports or candidate-side grants. No remote refs were refreshed or merged: this is not a develop-sync conflict and validation uses the exact dispatched base.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; errors 1 blocking gate. Next: coordinator resolves trusted-base reachability authorization/stack ownership and supplies the hosted `test` failure traceback and exact failing head. Full required CI and hosted-test remediation remain UNVERIFIED. No new items started.

## Commands and outcomes

All validation below ran against source head `5fc4a0d9ec21fb7ab6ca07cd8dd4378f4d0733a0` (only this report was untracked), with 1200-second command timeouts.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`: 349 collected, 346 passed, 3 skipped.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: 2229 collected, 1919 passed, 310 skipped, 5 SQLite thread-cleanup warnings; exit 0. Not a reproduction of the hosted failure.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16567 unique nodes, no inventory change.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: pass, 1322 reviewed identities.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`: exit 1, unauthorized reachability additions and dispositions for both admission modules. Required by `.github/workflows/vulture-ratchet.yml:77`.
- `uv run python scripts/check-reachability.py`: matches candidate baseline, 1403 modules / 171 unreachable. This is NOT trusted-base authorization.
- `uv run python scripts/check-reachability-dispositions.py`: pass, 50 groups / 171 dispositions. This is NOT trusted-base authorization.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `uv run python scripts/check-promotion-surface.py`: pass, 74 tolerated modules.
- `git diff --check`: pass before staging this report.

## Acceptance evidence and limits

All named tests below are in `packages/maistro-core/tests/tasks/test_admission_codec.py` and executed in the focused run unless explicitly marked skipped.

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted scalar header, named mapping, strict supported format | Source `AdmissionRowHeader`, `decode_admission_header`; unknown-format and invalid-scalar tests pass. |
| Reject header/row disagreement | `test_header_scalar_mismatch_is_invalid_header` and supported/unsupported format mismatch cases pass. |
| Exact immutable v2 DTO and fresh flat SQL mapping | Three states of `test_v2_round_trip_preserves_all_snapshot_bytes`, fresh mapping and non-v2 rejection tests pass. Independent assertions check task_id equals receipt_id, not just encode/decode agreement. |
| Strict storage-only UUID hex, signed timestamps, #1851 constructors | Owner-token, generation-ID, lease-window, expiry and acknowledgement tests pass; focused identity tests pass. |
| Legacy bound/unbound/partial distinctions without guessed identities | Bound/unbound, both partial pairs, receipt-only, missing receipt, whitespace/unreadable evidence and completed_at tests pass. A bound pair lacking receipt stays a typed failure because the DTO requires explicit receipt identity. |
| Header preserves expiry/fingerprint despite corrupt full record | Both named header-preservation tests and expired-header test pass. No replacement/409 decision is claimed. |
| Typed safe error codes, validated scope and suppressed parser chain | Invalid/duplicate JSON, excessive nesting, numeric loss, UTF-8 and malformed identity cases pass; source uses `raise ... from None`. |
| Nonfinite tags and arbitrary context preserved without fingerprint change | Tagged nonfinite and valid Unicode/exact-number tests pass as object/text contracts. They do not prove real request/receipt/Run materialization. |
| Raw and production PostgreSQL pools on same real migrated DB | UNVERIFIED this round: all three pool tests skipped without configured DSNs. No migration, DB session IDs, final row counts or durability claim. |
| Existing evidence-json/model_of materialization and Run JSONB object | UNVERIFIED: this leaf has no runtime materialization consumer; fixtures manually spell tags. No double-encoding claim established by pure codec tests. |
| Explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED as positive admission behavior: codec tests use DTO identity strings and do not perform authorization or create a canonical Run. |
| No clock, assessment, SQL mutation, HTTP/queue or policy activation | Source review of both modules and production import search: no consumer beyond codec-to-identity (Vulture whitelist is not reachability). ADR canonical execution and immutable provenance boundaries preserved. |
| Focused validation/inventory and unchanged integration gates | Focused checks above pass; required trusted-base gate fails at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`. Full CI remains UNVERIFIED. |
| Meaningful regression/mutation evidence for a new repair | No source or test repair made; no new mutation/pre-fix result claimed. Existing assertions inspected, not treated as evidence of runtime admission. |

Residual risks: trusted-base blocker remains; PostgreSQL and production integration criteria are unproven here; reported hosted test failure has no captured traceback for this source head. Do not promote this result based on green candidate-baseline or unit-test checks. Initial staged whitespace check caught a trailing blank line in this report; removed before commit.

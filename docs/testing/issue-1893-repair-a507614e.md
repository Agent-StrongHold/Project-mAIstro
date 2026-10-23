# Issue #1893 repair — a507614e

## Frozen scope and initial checkpoint

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `c338cf9b255d0d81d1ae5ed32a459e83b78928b7`; supplied base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Initial worktree clean; no incoming changes to salvage.
- Frozen repair candidates: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, their task/run tests and inventory notes, and (only if actual scan requires it) `quality/vulture-baseline.json`. This report is the checkpoint/output file. No other implementation scope or GitHub mutations.
- Read supplied dispatch issue body and prior result. Driver logs check-0 through check-4 report dependency sync, lint, format, focused tests (346 passed, 3 skipped), and suite inventory passing. These are driver evidence, not independent runtime verification.
- Ambiguity: hosted `test: failure` has no failing node or traceback in the supplied summary. Proceed by reproducing focused tests and exact gates, not guessing a repair.
- Prior reachability authorization blocker is not permission to edit reachability baselines/grants. Activation/ownership constraints in the issue remain applicable.

## Independent validation checkpoint

- Both supplied base and local `origin/develop` resolve to `ac7370141e8e61bd6f352bca35ed0b505104aadb`; no unresolved refs used.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings, zero unclassified. No Vulture ledger amendment is warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions lacking trusted-base authorization. The remaining provenance components pass.
- This reproduces the previous blocker, not a develop-sync conflict. Changing the candidate reachability ledger or adding fake production imports would not be a permitted repair. No such edits made.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`: PASS, 201 passed, 3 skipped (204 collected). All three raw/production PostgreSQL contrasts skip at test line 470 because the two DSN variables are unset. No database durability claim follows from this run.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files unchanged.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two source files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

## Architecture and acceptance review

Read repository instructions, documentation authority map, accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle), ADR-081426-1f7c (Attempt mechanics boundary), and ADR-082526-aef8 (workflow-rooted reachability). No change to canonical execution, authorization, events, or stores is authorized or made. Pure codec readiness does not establish production admission behavior.

Production-source search for `admission_codec|admission_identity` finds only the codec's identity import and a Vulture whitelist import; neither provides a production consumer. This agrees with the independently failing provenance gate. Issue B2 explicitly prohibits activation, so adding an artificial caller or export is not a reconciliation.

| Acceptance | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header; scalar validation; header/row mismatch | Existing codec and identity tests pass in the 204-node focused run. |
| Strict storage UUID hex, fresh flat mapping, task/Run binding and receipt equality | Existing round-trip, UUID and binding tests pass; migration CHECK compatibility is not newly proven against PostgreSQL. |
| Exact snapshots, tagged nonfinite evidence, unchanged fingerprint | Existing canonical text round-trip and tagged-evidence tests pass; production model materialization/Run JSONB object insertion remains UNVERIFIED here. |
| Legacy bound/unbound/partial/receipt-only classification; no invented identity | Existing legacy contract tests pass; no production consumer or claim decision is introduced. |
| Supported header survives malformed snapshots and partial binding | Both named header-preservation tests pass; expiry/409 policy remains consumer work, not B2 evidence. |
| Unsupported schema/format; duplicate/nonobject/bare nonfinite rejection; safe errors | Existing negative tests pass, including numeric loss and UTF-8 corruption boundaries. |
| Real migrated PostgreSQL, raw/production pool equality, authorized scope and registered Graph | UNVERIFIED this round: all three database tests skipped; pure DTO fixtures are not admission authorization evidence. |
| Full required hosted CI, reported `test: failure` | UNVERIFIED: supplied logs contain no failing test node/traceback; focused tests do not reproduce it. |
| Trusted-base gates | BLOCKED: two unauthorized unreachable modules/dispositions; exact Vulture and shipped-surface gates pass. |

## Final checkpoint / handoff

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -rs`: PASS, 1919 passed, 310 skipped, 5 warnings in 47.37s (2229 collected). Warnings are aiosqlite worker `Event loop is closed` exceptions reported during `test_sqlite_store.py`; these are not a reproduced test failure and are not changed in this lane. PostgreSQL skips are not durability evidence.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16567 unique nodes, no duplicate evidence.
- Inspected captured dispatch check-run sources for failing conclusions; the extraction produced no failing check output/traceback. Hosted `test: failure` remains UNRESOLVED; do not infer a repair from that label alone.
- Changed file this round: this report only. No implementation or test additions; inventory delta is zero, so no new inventory note is required. No gates, grants, or ledgers changed.
- Disposition: **BLOCKED**. The proven failure is trusted-base reachability provenance, outside the Vulture-only ledger repair exception. Owner/coordinator must resolve authorized integration staging (or separately land any appropriate authorization under the existing two-merge policy); this worker cannot approve it, activate the consumer, or mutate GitHub. Obtain the actual hosted failing test log before attempting a test repair. Re-run mandatory PostgreSQL legs on an identified disposable migrated database before claiming durability.
- Snapshot progress: checked 1, done 0 (implementation repair), skipped 1 (blocked), errors 1 (provenance gate); next: owner/coordinator resolution plus hosted failure evidence. Validation checkpoint complete; no merge-readiness or activation approval.


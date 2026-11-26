# Issue #1893 repair checkpoint — be4948fd

## Frozen scope

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting source `fcc8b437f209a35aa68a61d6f0a5387414938355`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 codec repair validation. Initial tree clean; no salvage required.
- Frozen implementation review: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, their two test files, existing atomic-admission B2 inventory notes. Read-only gate review: workflow/scripts and existing reachability ledgers. This report is the only planned edit unless executed evidence identifies a repair in scope.
- No GitHub mutations, activation, consumer wiring, or reachability ledger/grant modifications authorized. Vulture ledger changes permitted only for actual scanner findings.

## Initial evidence

Read supplied dispatch issue body and PR #1945 description from the frozen dispatch context. Issue explicitly stages representation only and prohibits using ledger changes to green an unwired slice. Assumption: assigned writer scope permits validation/reporting, not resolving external owner/activation decisions.

Driver logs in `/home/dev/maistro/jobs/be4948fd2728485eb116aca0e1665152`: dependency sync successful; ruff check/format successful; focused tests 201 passed, 3 skipped; suite inventory 16466 nodes matches. These are driver results, not fresh execution or PostgreSQL proof. Prior claims will be checked independently.

## Fresh gate evidence

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed findings, zero unclassified. No vulture ledger repair justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL. Reachability and disposition gates each reject both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`; trusted 169 becomes candidate 171. Other provenance subgates pass. Long timeout: 1200 seconds.
- Runtime import search finds only codec-to-identity and whitelist imports; no production codec consumer. This agrees with the source's explicit staged-only description, not runtime acceptance.

This is an external authorization/integration prerequisite, not a vulture finding or a merge conflict. No grant, consumer, or ledger edits will be invented to bypass it. Focused validation characterizes the handoff, not a re-run of this known blocker.

## Independent focused validation

Executed at the starting source SHA above, with 1200-second timeout:

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, three PG skips, 1.33s |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

The three live PostgreSQL cases skip at `test_admission_codec.py:470` without both required environment variables. No database was created or mutated this round; no current DB session identities, durability proof or SQL row counts are claimed. Prior live PostgreSQL results are historical evidence, not independently reproduced here. No new tests were added, so there is no inventory delta or new pre-fix/mutation-failure claim.

## Acceptance review

Read repository instructions/documentation authority, complete codec and identity sources, both adjacent test files, the B2 inventory's scope/repair history, supplied prior result and accepted ADR-082526-7f02 and ADR-081426-1f7c. Admission provenance remains immutable; execution identity belongs to Attempt. Nothing justifies a competing execution or authorization path.

The issue's shorthand that legacy task/run pairs are bound is reconciled with its stronger no-invented-identity requirement: a pair without receipt evidence is a typed partial failure, because the required binding DTO needs a receipt. No receipt is guessed.

| Criterion | Evidence / limitation |
| --- | --- |
| Exact shared interfaces; frozen/slotted header; six typed failure codes | Source review; header/schema/format tests and flat fresh mapping test pass |
| Strict UUID .hex and signed timestamp validation through #1851 constructors | Storage owner/generation, scalar boundary and DTO validation tests pass |
| Immutable v2 snapshots and binding | Three in-memory state round trips pass; independent task_id/receipt_id and paired binding assertions pass |
| Legacy bound/unbound/partial distinctions; receipt-only and announced-without-Run | Existing legacy tests pass; pair without receipt is rejected rather than fabricated; completed_at grants no authority |
| Header evidence survives full-decode failure; mismatched headers fail | Named expiry/fingerprint preservation and scalar mismatch tests pass |
| Unknown formats and invalid scalar headers fail closed | Unsupported-format and scalar validation tests pass |
| Strict TEXT snapshots and safe error hygiene | Duplicate/nonobject/nonfinite, nesting, numeric loss and surrogate tests pass; suppressed chains and validated error scope asserted |
| Arbitrary permitted program_context evidence tags and unchanged fingerprint | Tagged nonfinite, exact numeric and Unicode tests pass at representation boundary; no tag decoding or fingerprint recomputation in codec |
| Named SQL parameter mapping, fresh mapping, TEXT snapshot values | Source and pure mapping assertions pass; request maps to request_snapshot and claim_token to owner_token |
| Same migrated disposable database, raw/production pools, real SQL constraint compatibility | UNVERIFIED this round: three PG tests skipped; historical successful runs not adopted as current proof |
| Existing evidence-json/model_of/model_of_json model materialization and original-model fingerprint | UNVERIFIED: tests use tagged fixture dictionaries, not production model persistence |
| Run JSONB INSERT is an object, not doubly encoded | UNVERIFIED: no Run persistence executed |
| Explicit principals, authorized Workspace/Project, registered Graph kinds | UNVERIFIED: DTO string fixtures are not authorization evidence |
| No SQL mutation, HTTP/queue mapping, clock, assessment/claim decision or scope/policy change | Complete codec source review; mapping-only implementation; no source changes this round |
| Inclusive expiry/replacement and changed-payload 409 precedence | UNVERIFIED: C/F2 consumer responsibilities, explicitly outside B2 behavior |
| Reachable production behavior | NOT ESTABLISHED: only codec-to-DTO and whitelist imports; source explicitly inactive; provenance gate fails |
| Full required CI and reported `test: failure` | UNVERIFIED: focused checks pass, required provenance fails; supplied check logs have no failing test traceback. No speculative source fix or unrelated full-tree rerun |
| Coordination, activation and parent closeout | BLOCKED: repair assignment does not authorize activation, settle policy, or authorize reachability debt |

Storage lookup attempts at `migrations/versions/055*` and `maistro/runs/{postgres.py,serialization.py}` returned not found; skipped, not evidence. No database or model-persistence conclusion is based on those failed lookups.

## Final handoff

Only this report changes. No reproducible in-scope source defect or Vulture ledger discrepancy was found. The supplied develop base resolves and is already HEAD's merge base; this is not a develop-sync conflict.

Blocking entries are `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`, enforced by `.github/workflows/vulture-ratchet.yml:77`. The Vulture-only exception does not authorize modifying them. Required next step is an owner-approved, already-landed trusted-base authorization under the two-merge rule, or a separately authorized runtime integration. Repeating this lane or merging the same base cannot resolve that prerequisite. Supply an actual current-head failing test traceback for any further `test` repair.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1 required provenance gate. Verdict **BLOCKED**. This locally committed evidence handoff is not integration approval or issue closeout.

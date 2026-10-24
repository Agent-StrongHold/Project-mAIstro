# Issue #1893 repair — a62717ba

## Frozen scope

- One item: issue #1893, branch `auto-1893`, starting head
  `493be81602f74ce53b131a94c60aefe88e8a7c2e`.
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect existing admission codec/identity modules, adjacent tests, relevant ADRs,
  CI workflows, and existing reachability changes; no other issue implementation.
- Planned writable file: this validation report. Production/test repairs only if
  concrete failure evidence warrants a scoped change. No authorization/ledger edits
  except the explicitly permitted vulture ledger if its exact gate requires one.
- Initial tree clean; no incoming work to salvage.
- Driver logs: dependency sync, ruff check and format pass; focused pytest reports
  201 passed / 3 skipped, suite inventory 16,466. These are supplied results, not
  independent execution or live PostgreSQL evidence.

## Ambiguity and assumption

Dispatch names only `test: failure` without a failing node or traceback. Treat it
as unlocalized until independently reproduced. Prior reachability provenance
failure must be tested rather than assumed resolved. Coordination/policy remains
outside this staged codec repair; no activation or authorization changes.

## Validation

Fresh exact Vulture scan passed (1323 findings, zero unclassified). No ledger
amendment is warranted. Fresh provenance gate against the supplied resolved base
failed: both admission modules add an unauthorized unreachable module and an
unauthorized disposition (four findings). Other provenance subgates passed.
This is a reproduced external blocker; the Vulture exception does not authorize
reachability edits. Continue only focused validation and documentation, not
consumer wiring or fabricated reachability.

Commands (1200-second timeout):
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` — exit 1.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` — 201 passed, 3 skipped, 1.24s (204 nodes). All three PG cases skipped at test_admission_codec.py:470 because both DSNs are absent. Not live durability proof.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` — passed, 2 source files.
- `uv run python scripts/check-shipped-surface-truth.py` — passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` — passed, 16,466 nodes, zero duplicate evidence.

Read accepted ADRs 081226-a66b, 082526-7f02, 083126-5e62: preserve the
Goal -> Graph -> Run -> NodeRun -> Attempt model, immutable admission provenance,
Attempt-owned dispatch identity, and trusted-base authority. No reconciliation
permits activating the future consumer or self-authorizing reachability here.

An initial local JSON evidence extraction failed with AttributeError (captured
check-run data is a list, not an object); this is an inspection script error,
not the reported CI test failure. Prior result artifact was present and read;
its claims are not adopted as current-head execution evidence.

Corrected extraction of the frozen dispatch found the captured `test` failure
on dependency head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null
output title/summary/text. The captured `exact-debt-ledger` failure is on
`fcc8b437f209a35aa68a61d6f0a5387414938355`. Neither is an assigned-head
traceback. `.github/workflows/ci.yml:574-612` explicitly excludes core from
the `test` job; a focused core pass cannot establish that job. The generic
`test: failure` is UNRESOLVED, not repaired. No remote refresh was performed.

## Acceptance audit

All executed tests above use the unchanged starting Python source SHA.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header; required shared signatures and six error codes | Source inspected; header/DTO and scalar contract tests pass. |
| Named columns, strict storage UUID .hex, signed timestamps, matching header, #1851 constructors | Focused header/schema/UUID/v2 tests pass; encoder produces a fresh flat mapping. |
| No guessed legacy identity: bound/unbound/partial/receipt-only | Focused legacy tests pass. Both IDs without receipt evidence stay partial because the canonical binding requires a receipt; inventing one would violate the immutable identity contract. |
| Header preserves expiry/fingerprint despite bad snapshot or partial binding | Both named separation tests pass; no clock or incoming fingerprint accepted. Consumer replacement/409 ordering is not B2 behavior and remains UNVERIFIED. |
| Unknown format fail-closed; invalid/duplicate/nonobject/bare nonfinite TEXT rejected | Focused negative cases pass, including precision loss, excessive nesting and invalid Unicode. Safe error messages, suppressed parsing context and validated scope are asserted. |
| Snapshot bytes/tags and stored fingerprint preserved; storage-only owner token | Three-state round trips, tagged nonfinite and owner-token tests pass. Fixtures supply tags/fingerprints; actual evidence_json -> model_of/model_of_json materialization and unchanged original-model fingerprinting remain UNVERIFIED. |
| Real migrated DB, raw/production pools, non-null pg_pool, distinct sessions and row counts | UNVERIFIED this round: three database tests skipped without DSNs. No schema recreation or prior result substituted as durability evidence. |
| Run JSONB object, explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED: representation fixtures are identity strings, not authorized admission or Run INSERT tests. |
| No SQL mutation, HTTP mapping, queue/scope/claim/assessment or policy changes | Codec is a pure row/DTO mapping; no production edits in this round. |
| Meaningful inventory and pre-fix evidence | Existing focused tests run; no new tests or inventory delta. No fresh mutation/pre-fix experiment claimed. |
| Unchanged required CI and production reachability | NOT established: provenance gate fails. admission_codec.py:50-53 and admission_identity.py:3-6 explicitly identify inactive leaves; tests are not production consumers. Full integration CI UNVERIFIED. |
| Coordination and activation prerequisites | UNVERIFIED externally; this assignment does not authorize activation or merge. |

## Handoff

Only changed file: `docs/testing/issue-1893-repair-a62717ba.md`. No evidenced
production repair or Vulture ledger amendment was needed. Existing reachability
entries at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` still fail the required
`.github/workflows/vulture-ratchet.yml:77` provenance gate. They were not edited.

Next: an owner-coordinated, separately landed trusted-base authorization or
separately authorized consumer integration is needed; neither can be supplied
by this Vulture-only repair. Supply the assigned-head failing test step and
traceback before attempting a test-specific repair. Repeating unchanged inputs
cannot resolve the policy blocker.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Residual risks: inactive production slice, unverified live DB/materialization/
authorization/full CI, unresolved generic test failure. Local evidence commit
is a BLOCKED handoff, never integration approval.


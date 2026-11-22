# Issue #1893 repair checkpoint — e3643b17

## Frozen scope

- Assigned item: #1893 only, branch `auto-1893` in `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `0480c587b28f54106eb6ab32f290a8884b3e9cfd`; supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial tree clean. No incoming uncommitted work to salvage.
- Production/test inspection scope: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, their task/run tests, evidence JSON/model serialization, migration 055, and adjacent admission consumer.
- Gate inspection scope: existing reachability baseline/dispositions, vulture whitelist/baseline, relevant CI workflow/scripts; no reachability or authorization edits permitted. This checkpoint is the only planned edit unless validation identifies an actual in-scope repair.
- Evidence snapshot: supplied dispatch-context.json, check-0.log through check-4.log, prior a62717ba result. No remote issue/PR enumeration or GitHub mutations.

## Initial evidence and assumptions

Supplied checks: dependency sync, lint, format and suite inventory pass; focused tests report 201 passed, 3 skipped. Those skipped tests are not database durability proof. The dispatch reports a generic CI `test: failure` and a previous reachability-provenance block. Treat both as unverified until locally reproduced. Assigned repair ownership is assumed; production activation and independent integration approval remain outside scope.

## Reproduced results

Fresh local commands (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passes: 1323 reviewed findings, zero unclassified. No Vulture amendment is justified.
- After verifying the supplied base resolves, `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` fails: both admission modules add unauthorized unreachable modules and unauthorized dispositions (four findings). Remaining provenance subgates pass.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: 201 passed, 3 skipped. All three skips require both PostgreSQL DSNs. This is not live DB evidence.

The snapshot's failed `test` check belongs to dependency head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output title/summary/text; failed `exact-debt-ledger` belongs to `fcc8b437f209a35aa68a61d6f0a5387414938355`. Neither supplies an assigned-head failing traceback. Generic test failure remains unlocalized. No guessed test repair.

The existing baseline/disposition additions were inspected directly against the supplied base. They remain a required-gate blocker; the Vulture-only exception cannot authorize reachability changes or activation.

Additional fresh commands (1200-second timeout):

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass, 2 files.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16,466 collected nodes, zero duplicate evidence.
- Runtime-source reference search found only the codec's identity import and the Vulture whitelist import; no production consumer. An adjacent-source search also named nonexistent `migrations/` and exited 2; corrected discovery located and inspection read `alembic/versions/055_task_admission_generations.py`. This inspection typo is not a CI failure.

## Architecture and acceptance audit

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Keep the canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority, immutable admission provenance, Attempt-owned dispatch identity and trusted-base authorization. None permits self-authorizing these inactive modules. No competing execution, event, Goal or authorization path was introduced.

All executed Python tests use the unchanged starting source SHA. Focused collection totals 204 nodes, of which 201 executed and 3 skipped.

| Acceptance criterion | Executed evidence / limitation |
| --- | --- |
| Required frozen/slotted header, shared signatures and six typed error codes | Source inspected; focused header/scalar/DTO cases pass. |
| Named columns, strict storage UUID .hex, signed timestamp validation, matching header and #1851 constructors | Focused schema, UUID, scalar mismatch and record-constructor tests pass. Encoder returns fresh flat mappings. |
| Immutable snapshots, owner-token storage-only representation and unchanged stored fingerprint | Three-state round trips, owner-token and tagged nonfinite tests pass. Fixtures preconstruct tags/fingerprints: original-model fingerprinting and actual model_of/model_of_json materialization remain UNVERIFIED. |
| Strict TEXT JSON: duplicate keys, nonobjects, bare nonfinite values and invalid original evidence | Negative cases pass, including precision loss, deeply nested JSON and unpaired surrogates. Safe errors and suppressed exception chains asserted. |
| Legacy bound/unbound/partial/receipt-only without invented identity | Focused cases pass. Both IDs without a receipt remain partial rather than fabricating the receipt required by AdmissionBinding; this reconciles the shorthand 'both IDs bound' with the no-invention contract. |
| Header preserves expiry and fingerprint despite record decoding failures | Both named separation tests pass. No clock/request fingerprint enters the codec. Consumer replacement/409 precedence remains outside B2 and UNVERIFIED. |
| Unknown format fails closed; optional completed_at supplies no authority | Focused negative format and completed_at tests pass. |
| Real migrated PostgreSQL, matching DSNs, raw/production pools and durable row/session counts | UNVERIFIED this round: all three PG cases skipped for missing DSNs. No prior result adopted as current execution proof. |
| SQL mapping matches forward representation | Inspection of migration 055 confirms TEXT request/snapshots and paired binding with task_id=receipt_id; independent storage-shape unit assertions pass. Live constraint enforcement remains UNVERIFIED. |
| Run INSERT JSONB is an object; authorized explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED: codec fixtures use identity strings, not authorized runtime admission or Run INSERT. |
| No SQL/HTTP/queue mutation, assessment, scope utility, admission decision or policy change | Pure codec inspected; current idempotency._assess is separate and unchanged. This round changes documentation only. |
| Inventory and meaningful regression evidence | Existing tests executed; no added tests, no suite-count delta, no new inventory note required. No fresh mutation/pre-fix experiment claimed. |
| Unchanged required integration CI and production reachability | NOT established: exact-debt-ledger provenance gate fails, and source search confirms no consumer. Full integration CI UNVERIFIED. CI's test job explicitly excludes core (ci.yml:574 onward), so the focused pass is not proof that the reported test job is repaired. |
| Coordination/activation prerequisites | External coordination UNVERIFIED. Assignment grants repair work, not production activation, merge, policy decisions or parent closeout. |

## Final handoff

Changed only `docs/testing/issue-1893-repair-e3643b17.md`; no speculative production fix, test change, ledger/grant edit or gate weakening. Existing reachability rows at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` reproduce the provenance failure required by `.github/workflows/vulture-ratchet.yml:77`.

BLOCKED: resolving this requires separately authorized trusted-base work or separately authorized consumer integration, neither permitted by this lane. Obtain an assigned-head failing test step/traceback before a test-specific repair. Re-running unchanged dispatches cannot repair the authority blocker.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate (plus one corrected inspection-path error). Next: owner action on provenance and concrete test failure evidence. Residual risks: inactive production slice and unverified live DB/materialization/authorization/full CI. Local documentation commit is a handoff, not integration approval.

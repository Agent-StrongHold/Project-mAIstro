# Issue #1893 repair handoff — e236155f

## Frozen scope and disposition

**BLOCKED; no implementation repair justified by the reproduced evidence.**

Only issue #1893 on `auto-1893`, starting source
`f86e374ba41e7dda58be362aebe29ebedaf0000a`, was processed. The worktree was
clean. Supplied base and resolved `origin/develop` both equal
`2154f845347c9541016288c760f8da3f5cd2e064`; no sync conflict was present.
The only edited file this round is this report. No tests were added or changed,
so there is no inventory delta. No GitHub mutations, merges, or pushes occurred.

Read repository instructions, the frozen dispatch issue body and associated PR
bodies, previous result cfe471dce8f548c98c2b8ff81ce87b8a, all supplied check logs,
the codec and adjacent tests, CI ledger workflow, and accepted ADRs
081226-a66b, 082526-7f02, and 083126-5e62. The canonical execution hierarchy and
immutable admission provenance remain unchanged. Candidate evidence cannot
self-authorize reachability debt. The Vulture-only repair permission does not
permit reachability grants or production activation prohibited by the issue.

## Independently executed validation

Commands ran with 1800-second timeouts against the starting source SHA.
Logs for the first three substantive checks are retained in job directory
`/home/dev/maistro/jobs/e236155fb26941d1a0617ad9232a69f6/`.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Pass |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Pass: 1322 findings, 1322 reviewed identities, zero unclassified; `repair-vulture.log` |
| `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py` | **Exit 1**: two new unreachable modules and two new dispositions lack trusted-base authorization; `repair-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 327 nodes: 324 passed, 3 skipped in 1.97s; `repair-pytest.log` |
| `uv run ruff check .` | Pass |
| `uv run ruff format --check .` | Pass: 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Pass: two source files |
| `uv run python scripts/check-shipped-surface-truth.py` | Pass |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Pass: 16543 nodes, zero duplicate evidence |

No Vulture ledger amendment is warranted by the exact scan. The failed
provenance command identifies `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`, increasing both unreachable modules and
dispositions from 169 to 171. Relevant existing candidate entries are
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`.

## Acceptance audit

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header; exact decode/encode interfaces and six error codes | Codec inspected; header mismatch, schema, format, fresh flat mapping and identity tests passed. |
| Named columns, strict storage UUID hex, signed timestamps, prerequisite constructors | Storage UUID, scalar shape/range, envelope and binding rejection tests passed. Physical `request` maps to DTO `request_snapshot`. |
| Safe typed errors with validated scope only | Invalid scope, owner token, duplicate JSON, nested/lossy/non-UTF8 snapshot tests passed; messages omit raw values and displayed parsing chains are suppressed. |
| Immutable v2 unbound/bound/acknowledged round trips | Three pure round-trip states passed, including independent assertions of both binding columns and receipt identity. |
| Strict JSON object evidence and unchanged fingerprint | Duplicate/nonobject/bare-nonfinite rejection and tagged nonfinite round trips passed. Original model fingerprinting through evidence-json and subsequent model_of/model_of_json materialization remains **UNVERIFIED**; fixtures build tags directly. |
| Legacy bound/unresolved/partial distinguished without invented identity | Bound, unbound, one-sided, receipt-only and missing-receipt cases passed. A pair missing receipt stays partial because the canonical constructor requires receipt identity. |
| Header evidence survives full decode failure; unknown formats fail closed | Named expiry/fingerprint preservation, header mismatch and unknown-format tests passed. Consumer expiry/409 precedence remains **UNVERIFIED**, outside this representation-only leaf. |
| Real migrated PostgreSQL TEXT round trips using raw and production codecs | **UNVERIFIED** this round: all three cases skip at test_admission_codec.py:470 because required DSNs are unset. No live DB sessions, row counts, migration or durability evidence claimed. |
| Authorized principals/Workspace/Project, registered Graph and object-valued Run JSONB payload | **UNVERIFIED**: synthetic DTO tests do not establish these integration properties. |
| No SQL mutation, HTTP/queue/assessment changes or competing execution authority | Source inspection confirms mapping-only conversion with no clock or incoming fingerprint; no source was changed. |
| Reachable production behavior | No consumer found by `rg -n 'admission_codec|admission_identity' packages --glob '*.py' --glob '!**/tests/**'`: only codec-to-identity and whitelist-to-identity imports. Codec lines 50-53 explicitly document inactivity. Tests do not prove production activation. |
| Required validation and coordinated staging | Focused pytest, lint, format, mypy, Vulture, inventory and shipped-surface pass; required provenance fails. Full integration CI and parent ownership/activation coordination remain **UNVERIFIED**. |

The unspecified hosted `test: failure` was not reproduced in the focused
suite. No failing hosted node/trace was supplied. No pre-fix or mutation failure
is claimed, since no source or test change was justified. Supplied prior live
PostgreSQL claims were not substituted for execution in this round.

## Next action

Resolve the trusted-base staging/authorization conflict through the owning
coordination process, or supply a concrete failing CI node and traceback for a
separate test repair. Do not treat an unchanged Vulture rerun, a candidate grant,
a fake caller, or another passing codec test as resolving this blocker.
No additional DB setup or full integration run was started after reproducing
the blocker: neither can supply the missing authorization.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base owner coordination and actual hosted failing-test evidence}`.

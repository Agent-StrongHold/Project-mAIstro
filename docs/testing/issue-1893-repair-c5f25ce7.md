# Issue #1893 repair checkpoint — c5f25ce7

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, clean starting head
  `c5f25ce701d62c08dc63345eca5b6e69e7a0038c`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect existing admission codec/identity implementation and their two test files,
  relevant ADRs, captured dispatch evidence, and named CI gates. No new work items.
- Candidate repair files: those two implementation/test pairs, their inventory
  notes if tests change, and this validation report. Vulture ledger changes only
  if the mandated scan supplies actual retained-identity evidence. No reachability
  ledger/grant changes or activation wiring are authorized.
- Driver logs inspected: check-0 sync succeeded; check-1 lint passed; check-2
  format passed; check-3 201 passed / 3 skipped; check-4 core inventory matched
  16466 nodes. These are supplied evidence, not independently executed claims.
- Ambiguity: dispatch says CI `test: failure` without a failing test trace.
  Proceed by executing focused tests and named gates; do not guess a code repair.
- Prior authorization blocker and PostgreSQL legs require independent validation.

## Results

Independently reproduced the blocking gate (1,200-second timeout):

- Both the supplied base and local `origin/develop` resolve to
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. No unresolved merge/conflict exists;
  merging this same base cannot supply missing authorization.
- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,323 findings,
  zero unclassified. No evidence warrants a vulture ledger amendment.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py`: FAIL (exit 1). Admission identity and
  codec modules each add an unauthorized unreachable identity and disposition;
  trusted/candidate counts are 169/171. Other provenance checks pass.

The prior BLOCKED result is independently confirmed, not resolved. Required
provenance is enforced before vulture at `.github/workflows/vulture-ratchet.yml:77`.
No grant, reachability ledger or gate edit is permitted in this lane.

Additional independent checks (1,200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`:
  201 passed, three PostgreSQL cases skipped, 204 nodes, 1.26 seconds.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Runtime import search found only codec -> identity and whitelist -> identity
  references. Neither is a reachable production consumer. No activation wiring
  will be added to evade the provenance failure.
- Docker discovery found `maistro-postgres` and `maistro-soak-pg`, not the prior
  report's lane container. No existing service/database was mutated. Live PG
  validation for this head remains UNVERIFIED; historical PG claims are not
  reused as current-head evidence.

Read accepted ADR-082526-7f02 and ADR-081426-1f7c: admission provenance remains
immutable and physical execution belongs to Attempt. The codec introduces no
execution or authorization authority. No conflict with those ADRs was found.
The issue's shorthand 'both IDs is bound' is constrained by its prohibition on
invented identity and the prerequisite binding constructor's required receipt:
a bound legacy pair without receipt evidence stays a typed partial disposition.

`uv run python scripts/check-suite-inventory.py --suite
packages/maistro-core/tests` also passed: 16,466 nodes, zero duplicate evidence.
`git diff --check` passed. No tests were added or changed, so no inventory delta
or new regression/mutation failure is claimed.

## Reported CI failure: UNRESOLVED

The frozen dispatch contains `test` check records for linked heads: success at
`5d835338f7fa45b62d6361c9f3eddc5faf14284a`, failure at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, success at
`fcc8b437f209a35aa68a61d6f0a5387414938355`, and success at
`d0a03c8db5c49c4756a1dc231a7bdc31f731f105`. Their summary/text fields are null.
None identifies an actual failing test at the assigned starting head. After
inspecting this captured evidence and executing focused tests, the generic
`test: failure` remains unattributed; no speculative code repair is justified.
Full CI was not executed or claimed green.

## Acceptance review

All source/test review and independent execution above apply to source SHA
`c5f25ce701d62c08dc63345eca5b6e69e7a0038c`. Only this report changes afterward.

| Criterion | Evidence / limitation |
| --- | --- |
| Exact shared codec API; frozen/slotted header; six typed decode codes | Complete codec review; existing schema, header-mismatch, and DTO tests pass |
| Storage UUID .hex; signed scalar timestamps; prerequisite constructors | Strict generation/owner token tests, invalid scalar boundary tests, and identity constructor tests pass |
| Fresh flat parameter mapping; named SQL field mapping | Existing mapping and three-state in-memory round-trip tests pass; request -> request_snapshot and claim_token -> owner_token reviewed |
| Bound v2 identity matches immutable receipt | Independent task_id/run_id expectations at test_admission_codec.py:134-137 pass; identity constructor rejects receipt mismatch |
| Bound, unbound, partial legacy evidence; no inferred identity | Legacy pairing, missing-receipt, receipt-only, malformed-evidence and expired-header tests pass; completed_at is not read |
| Header/full decoding split and row/header agreement | Header expiry/fingerprint preservation, scalar mismatch and unknown-format tests pass; no clock or incoming fingerprint exists in API |
| Strict TEXT JSON; duplicate/nonobject/bare-nonfinite rejection | Existing invalid JSON, deep nesting, decimal loss, non-UTF8 and predecoded-value tests pass |
| Safe error messages and suppressed parsing chain; validated scope only | Existing malformed JSON/token/scope tests pass; codec raises typed errors from None without raw snapshots/token values |
| Tagged arbitrary program_context evidence preserved; no recomputed fingerprint | Tagged nonfinite, exact numeric and Unicode tests pass with stored fingerprint assertions; codec does not materialize tags or recompute identity |
| Real evidence_json encoding, model_of/model_of_json materialization, original-model fingerprint, Run JSONB object INSERT | UNVERIFIED: codec fixtures contain pre-tagged dictionaries rather than real request/receipt/Run persistence |
| Raw/production pool equivalence on actual migrated disposable PostgreSQL | UNVERIFIED at this head: all three PG cases skipped; no migration, session identities or final SQL counts claimed |
| Positive admission uses authorized principals/Workspace/Project/registered Graph | UNVERIFIED: fixtures are representation strings, not authorization or admission evidence |
| No SQL mutation, HTTP mapping, queue, live assessor, scope or policy change | Complete codec review: mapping-only functions; no implementation change this round |
| Inclusive expiry replacement, changed-payload 409 precedence, crash/claim/dispatch | UNVERIFIED here and outside B2: future C/F2 behavior, not codec decisions |
| Canonical execution and immutable provenance | Accepted ADRs reviewed; no new scheduler, execution, event or authorization authority |
| Production reachability and required CI | FAIL: two inactive modules/dispositions lack trusted-base authorization; test imports/whitelist are not production reachability |
| Focused pytest, lint, format, scoped mypy, inventory, vulture, shipped-surface | Independently PASS as recorded above, with explicit PG skips |
| Coordination/activation and independent integration | BLOCKED: repair assignment does not authorize activation, policy resolution, or new reachability grants |

## Final handoff

Changed file: `docs/testing/issue-1893-repair-c5f25ce7.md` only. No code, tests,
ledgers, grants, gates, existing reports, or GitHub state were changed. Existing
work was preserved. The local report commit is evidence handoff, not approval.

Blocking evidence: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The owner must arrange an
already-landed trusted-base reachability authorization under the two-merge rule,
or separately authorize the production integration. The vulture-only ledger
exception cannot resolve this gate. Re-running it or merging the identical base
cannot resolve it either. Supply a current-head CI traceback before attributing
or repairing the generic test failure.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1 required
gate. Next: owner resolves that prerequisite and current-head CI attribution.
Verdict: **BLOCKED**.


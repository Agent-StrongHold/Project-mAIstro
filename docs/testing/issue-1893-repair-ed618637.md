# Issue #1893 repair — ed618637

## Frozen scope and initial evidence

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `3ffbfd01894759eeabfe5d6dec38cc615fcc734d`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Only item: issue #1893 CI repair. Candidate implementation files are
  `packages/maistro-core/src/maistro/tasks/admission_codec.py`,
  `packages/maistro-core/src/maistro/runs/admission_identity.py`, their existing
  `test_admission_codec.py` / `test_root_admission_identity.py` tests, and this
  validation report. Vulture ledger amendment only if the mandated scan proves
  retained unbanked identities. No other ledger/grant changes are authorized.
- Initial worktree clean; exact assigned head resolves.
- Read dispatch issue body and supplied prior result. Driver logs check-0 through
  check-4 show dependency sync, ruff, formatting and inventory passing; focused
  tests: 201 passed, 3 skipped. These are driver evidence, not live PG proof.
- Ambiguity: dispatch says `test: failure` without an assigned-head traceback.
  Proceed by reproducing focused tests and named gates, not guessing a repair.
- Prior provenance failure and lack of runtime activation are not assumed fixed.
  Stage contract forbids adding runtime callers or grants simply to turn green.

## Validation

Fresh executions (1800-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities / 1323 findings. No ledger amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), two unauthorized unreachable modules and two unauthorized dispositions: `maistro.runs.admission_identity`, `maistro.tasks.admission_codec`. Trusted base has 169, candidate 171. Other provenance subchecks pass.

Mandatory external blocker is independently reproduced. No sync conflict exists.
The Vulture-only exception does not permit reachability/disposition grants or
out-of-scope consumer wiring. Remaining validation will document staged codec
behavior without asserting independent mergeability.

## Completed focused checks

Fresh commands, each run with a 1800-second tool timeout:

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, 3 skipped; 204 nodes, 1.32s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; 2 source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Read repository AGENTS.md, both complete source modules and both focused test
files, CI exact-debt-ledger workflow, and accepted ADR-081226-a66b,
ADR-082526-7f02, ADR-083126-5e62. Reconciliation: preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model, immutable admission provenance,
and trusted-base authorization. The issue's staged-leaf scope is not permission
to bypass reachability gates or activate the prospective consumer.

## Acceptance audit

- Frozen/slotted header, named mapping interfaces, typed errors, validated scope,
  signed timestamps and strict UUID `.hex`: inspected source and executed focused
  contract tests pass.
- Header/full-decode separation, unchanged expiry/fingerprint evidence despite
  corrupt snapshots or partial binding, mismatched-header rejection, unsupported
  schema/format fail-closed: executed focused tests pass. Replacement and 409
  ordering belong to C/F2 and are not claimed as B2 behavior.
- V2 snapshot round trips, fresh flat mapping, original receipt binding and
  acknowledgement rules: executed tests pass. Independent mapping assertions at
  `test_admission_codec.py:134-138` pin both SQL binding columns, not merely mutual
  encode/decode agreement.
- Legacy bound/unbound/partial, receipt-only, bound-without-receipt and unreadable
  evidence: executed tests pass; codec never invents a missing identity and does
  not read `completed_at` as authority.
- Strict TEXT JSON rejects duplicate keys, nonobjects, bare nonfinite tokens,
  numeric loss, excessive nesting and invalid Unicode with safe typed errors:
  executed tests pass. Tagged evidence and stored fingerprint survive unchanged.
- Production `encode_evidence`/`model_of`/`model_of_json` materialization and
  fingerprinting on original models: **UNVERIFIED**. Existing fixture tags are
  hand-built; mapping tests do not prove production materialization.
- Real migrated PostgreSQL raw/production pool contrast: **UNVERIFIED this
  round**. All three cases skip at `test_admission_codec.py:470` because required
  DSNs are absent. No DB provisioned after the mandatory external blocker was
  reproduced; no session identities, migration proof or SQL residue counts claimed.
- Run payload JSONB object persistence, real authorized principals,
  Workspace/Project and registered Graph kinds: **UNVERIFIED**. The DTO tests
  are not positive admission/authorization or transaction tests.
- No SQL mutation, HTTP/queue change, clock, assessment/claim decision, scope
  algorithm or policy change in the codec: inspected source. No new runtime
  consumer is present: source search finds only codec -> identity and whitelist
  -> enum imports. Test imports and exports are not runtime reachability.
- Focused tests, lint, format, scoped types, inventory and shipped surface pass.
  Required unchanged full integration CI: **UNVERIFIED**; mandatory provenance
  gate **FAILS**. Coordination and activation prerequisites remain external.

## Final handoff

Only this report changed; no source, tests, inventory, ledger, grant or gate edits.
No tests were added, so no inventory delta or new mutation/pre-fix claim applies.
Reported `test: failure` remains **UNRESOLVED**: supplied check logs contain no
failing node/traceback, and focused execution did not reproduce a test failure.
Do not infer an implementation repair from that label.

The blocker is concrete: `.github/workflows/vulture-ratchet.yml:77` runs the
provenance gate, which rejects candidate additions at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. Resolution requires an
externally authorized integration base/consumer decision; this lane cannot
self-authorize it. Assigned-head CI failure diagnostics are also needed.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 mandatory gate;
next: external prerequisite and attributable CI traceback. Verdict: **BLOCKED**.
Commit this report locally only; no push, merge or issue action.

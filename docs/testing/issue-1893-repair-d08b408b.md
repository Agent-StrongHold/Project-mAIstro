# Issue #1893 bounded repair — d08b408b

## Frozen scope and initial evidence

One item: #1893, assigned worktree `/home/dev/Git/wt/auto-1893`, branch
`auto-1893`, starting clean HEAD `be9ef5aca2c6307d21e1e1796115fe37ea69248a`,
assigned base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Review files: admission codec and prerequisite identity DTO, their adjacent tests,
repository instructions/relevant ADRs, supplied dispatch/prior result, and named
CI gates. Edit scope: this report, with code/test repair only on actual evidence.
No other issues or linked PRs are implementation targets. No remote changes.

Driver check-0..4 logs were inspected: dependency sync, ruff and format passed;
focused tests reported 346 passed / 3 skipped; inventory reported 16567 nodes.
These are driver evidence, not this worker's independent execution.

Ambiguity: `test: failure` supplies no failing node or traceback. Proceed by
running focused tests and exact named gates, not guessing a repair. The prior
result reports a trusted-base authorization blocker. Independently reproduce
it; the Vulture-only ledger exception does not authorize reachability edits,
fake runtime callers, or production activation. No develop sync conflict exists.

Source inspection confirms the codec explicitly stages a pure mapping/DTO
surface without a runtime consumer; it cannot prove live admission behavior.
The previous report's PostgreSQL results are not adopted as fresh evidence.

## Validation

Independent results at the starting source SHA:

- Exact requested Vulture command passed: 1322 findings, zero unclassified;
  no retained unbanked identities exist, so no ledger amendment is justified.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`
  failed (exit 1): both admission modules are new unreachable modules and new
  dispositions without trusted-base authorization (four errors).
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`
  passed (2 source files).
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`
  collected 204: 201 passed, 3 skipped (both PostgreSQL test variables unset).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  passed: 16567 nodes, no duplicate evidence.

The exact Vulture command was:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
All validation commands used 1200-second timeouts.

Read accepted ADR-081226-69ee, ADR-082826-b601 and ADR-083126-5e62 in full.
Reconciliation: canonical execution and explicit opt-in remain authoritative;
stage-only codec acceptance cannot authorize a new runtime consumer or its own
quality expansion. The request to resolve BLOCKED cannot authorize that bypass.
A production-source import search finds only the codec importing the DTO (plus
Vulture's whitelist); no runtime consumer imports the codec.

No production/test/ledger changes made. No develop sync conflict was found.
The demonstrated provenance failure is not a Vulture debt or merge-conflict
repair. It requires an integration/quality-owner prerequisite outside this lane.

Additional independent commands (1200-second timeouts):

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`
  — 2229 collected, 1919 passed, 310 skipped, four aiosqlite closed-event-loop
  worker-thread warnings. No failing node reproduced in this scoped suite.
- `uv run python scripts/check-shipped-surface-truth.py` — passed.
- `uv run python scripts/check-reachability.py` — passed against candidate ledger:
  1403 modules, 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py` — passed against
  candidate ledger: 50 groups covering 171 modules.
- `uv run python scripts/check-promotion-surface.py` — passed, 74 tolerated modules.
- `git diff --check` — passed.

Passing candidate-ledger checks do not override the failed trusted-base gate.

## Acceptance accounting

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Frozen/slotted header, exact APIs, six typed errors, safe hash/error surface, fresh flat mapping | Source inspection and 201 passing focused nodes, including header mismatch, scalar validation, safe parse failure and encode freshness cases |
| Strict UUID .hex and signed timestamps; constructor validation; named SQL mapping | Owner/generation/storage and header validation tests passed; mapping and binding shape assertions passed |
| Immutable snapshots and stored fingerprint preserved | V2 unbound/bound/acknowledged byte round trips and tagged nonfinite tests passed; no fingerprint recomputation in codec |
| Duplicate keys, nonobject roots, bare nonfinite tokens rejected; permitted evidence retained | Invalid JSON, Unicode, lossless-number and tagged-value tests passed; actual model materialization remains UNVERIFIED |
| Legacy bound/unbound/partial/receipt-only distinguished without invented identity | Legacy tests passed; bound pair without stored receipt stays typed partial evidence because the prerequisite DTO requires receipt identity |
| Header survives invalid snapshot/partial binding and preserves expiry/fingerprint | Named header separation tests passed; no clock or request fingerprint enters decoder |
| Unknown format fails closed and mismatched header rejected | Unsupported-format parametrization and scalar-mismatch tests passed |
| Raw/production pools against same disposable migrated DB; real schema and final SQL identity counts | UNVERIFIED in this round: three PG cases skipped, both test URLs unset; no old database claim adopted |
| Existing evidence-json/model_of materialization, arbitrary program_context, Run JSONB object shape | UNVERIFIED end-to-end; current tests hand-build tagged JSON and do not materialize or insert canonical Run payloads |
| Positive authorized admission uses explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED: codec tests use placeholder identity strings, not an admission flow |
| Typed representation only; no SQL mutation, clock/assessment, live _assess, scope, queue, HTTP or legacy-policy change | Complete codec/DTO inspection; this round changes only this report; production consumer remains intentionally absent |
| Expired replacement / 409 precedence | UNVERIFIED; later C/F2 consumer evidence, not this B2 leaf's behavior |
| Required integration CI, no self-authorizing gate/baseline changes | FAILED trusted-base gate; hosted test failure remains unlocalized and full integration CI UNVERIFIED |
| Inventory and truthful validation | Inventory gate passed; no tests changed or added, so no inventory-delta note is needed; no pre-fix/mutation experiment claimed |

## Final disposition

BLOCKED. Actual evidence is `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`, rejected by the required gate
at `.github/workflows/vulture-ratchet.yml:77`. Do not repeat this unchanged
repair indefinitely: next action is coordinated resolution of the trusted-base
prerequisite, plus a concrete hosted failing test node/traceback if `test` still
fails. This lane cannot manufacture authorization, independently activate the
consumer, or remove preserved implementation work to pass the gate.

Changed file: this report only. No code fix was justified by this run. Existing
source, tests, inventory, ledgers and grants are preserved. No fetch, merge,
push, PR, issue action, destructive Git operation or database mutation occurred.
Commit this report locally as the writer checkpoint; this is not merge approval.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1,
next: trusted-base prerequisite and localized hosted-test evidence}.

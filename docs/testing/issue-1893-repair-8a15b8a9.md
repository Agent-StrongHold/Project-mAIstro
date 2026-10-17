# Issue #1893 — bounded repair check 8a15b8a9

## Frozen scope and decision

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Clean starting source: `b2c36c7763c0813f4136e29ca2d5a6abb71ca02f`.
Validated base and local `origin/develop` both resolve to
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Scope: issue #1893, supplied dispatch snapshot and reported CI failures only.
No incoming uncommitted work; all existing work preserved.

Read repository instructions, documentation authority map, accepted
ADR-081226-a66b, ADR-081426-1f7c and ADR-082526-aef8, the frozen issue body,
recent issue comments, supplied PR check evidence, prior result, codec source,
identity constructors, adjacent tests and existing B2 inventory note.
Reconciliation: retain Goal → Graph → Run → NodeRun → Attempt and the issue's
explicit prohibition on activation. No artificial caller or alternate authority
will be introduced to make a staged codec appear reachable.

The job's check-0 through check-4 logs report successful dependency sync,
lint, format, focused tests (346 passed, 3 skipped) and suite inventory.
The dispatch snapshot records PR #1945's `test` check 117010602704 as successful
at **80171ce1cff9**, not this head. No failing test node or traceback accompanies
the generic `test: failure` assignment. Assumption: validate scoped tests and
exact gates, not guess a repair. Hosted failure remains UNRESOLVED.

## Independently reproduced gate results

Executed at the starting source SHA with 1000-second command timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **exit 0**, 1322 findings / 1322 reviewed identities. No unbanked identity and no justified Vulture ledger amendment.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: **exit 1**. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are NEW unreachable modules absent from the trusted base and NEW dispositions without already-landed authorization. Other component gates pass.

Failure locations: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606–613`. CI invokes provenance at
`.github/workflows/vulture-ratchet.yml:77`. The Vulture-only repair exception
cannot authorize reachability ledger/grant edits. This is not a merge conflict;
the local develop ref already matches the supplied frozen base. Do not retry
this same head expecting an authorization change.

## Independently executed focused validation

All commands below used a 1000-second timeout at the starting source SHA:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: **346 passed, 3 skipped**, 349 collected. All three skips are the real PostgreSQL contrast cases at `test_admission_codec.py:470`; required DSNs are unset. No durability proof claimed.
- `uv run ruff check .`: **pass**.
- `uv run ruff format --check .`: **pass**, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **pass**, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **pass**, 16567 unique nodes, no duplicate evidence.
- Production-only import search for both modules: only codec → identity (`admission_codec.py:67`) and Vulture whitelist → identity (`_vulture_whitelist.py:105`). No runtime consumer found; consistent with the failed provenance scan and codec staging notice at lines 50–53.
- `git diff --check`: **pass**.

## Acceptance matrix

| Criterion | Evidence or limitation at this head |
| --- | --- |
| Required header/interfaces, immutable DTOs, strict UUID hex and signed timestamps | Source inspection and passing focused contract tests, including invalid formats/scalars and header mismatch. Focused mypy passes. No reachable production consumer. |
| Exact legacy bound/unbound/partial distinctions, receipt-only and missing-receipt rejection; no inferred identity | Passing named legacy tests in focused suite; codec does not manufacture generation, receipt or Run identity. |
| Header/full-decode separation preserves expiry/fingerprint | Passing named expiry/fingerprint preservation tests. Decoder takes only row/header, not a clock or incoming fingerprint. Replacement/409 ordering is not implemented or claimed by this leaf. |
| Typed error codes, safe scope and suppressed unsafe parsing chains | Passing negative tests for malformed JSON, duplicates, nonobject roots, bare nonfinite values, excess nesting, numeric loss, escaped surrogates and invalid identities. |
| Fresh flat named-column encoding and binding mapping | Passing fresh-mapping, strict-storage-token and bound/unbound/acknowledged round-trip tests. No SQL mutation added. Real migration CHECK enforcement **UNVERIFIED this round**. |
| Snapshot byte fidelity, evidence tags and unchanged stored fingerprint | Passing canonical snapshot and tagged nonfinite round-trip tests. Fixtures use literal tags and a preset fingerprint: original-model fingerprint generation and production `model_of`/`model_of_json` materialization **UNVERIFIED**. |
| Raw/production codecs, matching disposable migrated database and row/session evidence | **UNVERIFIED**: three tests skipped; no DB created or accessed in this bounded blocker check. Prior job's live-DB claims are not adopted as current evidence. |
| Run JSONB payload is an object, explicit authorized principals/Workspace/Project and registered Graph | **UNVERIFIED**: DTO/storage fixtures do not perform positive admission or insert a Run; no runtime consumer. Activation is expressly outside B2 authority. |
| Inventory, focused pytest, lint, format and typing | Fresh passes above. Existing inventory note inspected; no tests added or counts changed, so no new inventory-delta note required. |
| Unchanged required integration CI and applicable quality gates | **NOT SATISFIED**: provenance fails. Vulture passes. Full hosted CI **UNVERIFIED**; reported `test: failure` not reproduced and lacks actionable traceback. |
| Canonical ownership and stage constraints | Preserved: no alternate scheduler, execution, Goal/event/auth authority, live assessor, scope utility, HTTP, deletion or queue change. No activation or closure action. |

## Handoff

**BLOCKED**. Only changed file this round:
`docs/testing/issue-1893-repair-8a15b8a9.md` (this evidence/handoff).
No source, test, ledger, grant or gate changes; no speculative repair or new
pre-fix/mutation evidence claimed. All incoming branch work remains intact.

Next: coordinator must resolve the staged integration and trusted-base
reachability authorization under existing policy (without treating a
candidate grant as authorization), and supply the actual hosted failing-test
node/traceback. Neither a Vulture ledger amendment nor an artificial import
would address the reproduced failure. No fetch/merge was warranted by a sync
conflict; no GitHub mutation, push, branch deletion or integration action taken.
This report is committed locally as required, not an integration approval.

Progress: checked 1, done 0 (implementation repair), skipped 1 (blocked),
errors 1 (provenance gate); next: authorized staging resolution and failing-test evidence.

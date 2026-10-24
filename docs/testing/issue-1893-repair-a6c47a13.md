# Issue #1893 repair at a6c47a13

## Frozen scope and initial evidence

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `a6c47a13a5c8962b9201118dff65d581dd7c31b6` (verified); supplied develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (resolved by diff).
- Single assigned item: #1893; no other issue/PR will be processed or refreshed.
- Initial tree clean; no incoming edits to salvage.
- Implementation inspection scope: `tasks/admission_codec.py`, `runs/admission_identity.py`, their two test files, existing B2 notes, applicable ADRs and CI workflows/gate scripts. Any change will be evidence-driven; no reachability ledger/grant changes are authorized.
- Captured driver logs in job `4c0dd67fd2854e69afb750ea29ec6ed4`: dependency sync, ruff check, format check passed; targeted tests 201 passed/3 skipped; core inventory 16466 matched. These are driver results, not live PostgreSQL acceptance evidence.
- Ambiguity: dispatch says `test: failure` without a failed node/log. Proceed by reproducing focused tests and the specifically named vulture/provenance gates, not guessing a code or ledger change.
- Stage constraint: typed codec only; no live admission activation, scheduling authority, HTTP mapping, or policy change. Prior reachability blocker requires independent verification.

## Reproduced blocker

Fresh validation against the resolved supplied base:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1323 findings, zero unclassified identities. No Vulture ledger amendment is justified.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`: exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions without already-landed authorization (169 trusted entries versus 171 candidate entries).

Logs: `worker-vulture.log` and `worker-provenance.log` in the assigned job directory. `.github/workflows/vulture-ratchet.yml:77-85` requires these gates. The Vulture-only repair exception does not authorize reachability grants or baseline changes. This is not a develop-sync conflict: the tree was clean and local `origin/develop` resolves to the supplied base.

## Architecture reconciliation

Read accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle) and ADR-082526-7f02 (immutable admission provenance, Attempt-owned dispatch identity). This leaf preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`; constructing a DTO grants no admission authority. Source inspection and `rg -n 'admission_codec|admission_identity' packages/*/src --glob '*.py'` find only the codec's DTO import and a Vulture whitelist import, not a runtime consumer. The module itself explicitly documents the inactive stage. Adding a fake caller or activating the consumer to evade the gate would violate the assigned stage constraints.

## Validation

Commands run with 1200-second timeout at the starting source SHA:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, two source files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: 204 nodes, **201 passed, 3 skipped** in 1.28s (`worker-focused.log`). All three skipped cases require the PostgreSQL environment variables; no durability claim follows.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: exit 0 (`worker-inventory.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0 (`worker-shipped.log`).

No source/test changes are supported by the reproduced evidence. No new tests, inventory delta, regression/mutation proof, or database proof is claimed. Prior runs' database claims are not adopted as current validation.

## Acceptance evidence and limits

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header, required signatures and decode codes | Source inspection; header mismatch and unsupported-format tests passed. |
| v2 immutable round trip, fresh flat mapping, named columns | Three snapshot round-trip states and fresh-mapping test passed; independent binding-column assertions match migration-055 shape. |
| UUID `.hex` at storage only, signed timestamps, #1851 constructors | Owner/generation encoding, invalid scalar and DTO validation tests passed. |
| Bound/unbound/partial legacy distinction; no inferred identity | Legacy pair, missing receipt, receipt-only, unreadable and whitespace evidence tests passed. |
| Header preserves expiry/fingerprint despite full decode failure | Both preservation tests and expired-header test passed. No clock or incoming fingerprint is accepted by the codec. |
| Unsupported format/schema and mismatched supplied header fail closed | Unknown-format, missing-column and scalar-mismatch tests passed. |
| Strict object JSON, duplicate/nonfinite rejection, safe errors | Snapshot tests passed, including nested corruption, lossy numeric evidence and invalid Unicode; error assertions check suppressed chains and redaction. |
| Tagged nonfinite and arbitrary permitted program-context evidence, unchanged fingerprint | Tagged snapshot and valid Unicode/exact-number tests passed at representation level. No tag materialization or fingerprint recomputation occurs in this codec. |
| Existing evidence codecs/model materialization, original-model fingerprinting, Run JSONB object INSERT | **UNVERIFIED**: hand-tagged fixture dictionaries do not prove those production operations. |
| Raw and production pools against one disposable database migrated through real chain | **UNVERIFIED**: three cases skipped; no fresh sessions, migration-chain, durability or final SQL row-count evidence. |
| Real authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED**: unit fixture strings are not authorization or production admission proof. |
| No SQL mutation, HTTP mapping, queue, live assessor or scope-policy changes | Source inspection confirms representation-only functions; this repair changes documentation only. |
| Inclusive expiry/replacement and mismatch/409 precedence | **UNVERIFIED**, intentionally owned by the future consumer, not implemented by B2. |
| Full unchanged required CI and integration gates | **Not satisfied**: provenance gate fails. Full CI not run; dispatched `test: failure` not reproduced by focused tests and has no actionable traceback in supplied check logs. |
| Coordinated stack ownership and activation | Assigned repair ownership only; broader integration ownership/activation remains **UNVERIFIED/BLOCKED**. |

## Handoff

Only `docs/testing/issue-1893-repair-a6c47a13.md` changed. No baseline, grant, gate, whitelist, source or test edit. Existing unauthorized entries remain in `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`.

Resolution requires owner coordination of the already-landed reachability authorization required by the two-merge policy, or a separately authorized runtime integration. Neither is permitted within this repair. Supply the actual current-head failing CI test traceback before requesting a speculative test repair. Repeating this unchanged source/base validation cannot clear the policy blocker.

Progress: checked 1; done 0 repairs; skipped 0 items; errors 1 reproduced provenance blocker; next: owner authorization and actionable CI test evidence. This documentation commit is a blocked handoff, not integration approval or issue closeout.

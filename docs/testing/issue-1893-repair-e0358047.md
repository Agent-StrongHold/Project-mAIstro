# Issue #1893 repair validation — e0358047

## Frozen scope and assumptions

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, verified
starting HEAD `bda144a9587e911a5cc8fb9b27c5ee0ca702427b`; base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Initial worktree clean.
Only issue #1893 is a work item. Snapshot: supplied dispatch context, check-0
through check-4 logs and prior result 000e4eb6; repository instructions,
admission ADRs, codec/identity modules and adjacent tests, CI workflows and
gate scripts, existing reachability entries, and this report. No remote actions.

Assumption: writer repair, not verifier. Repair only reproduced defects;
Vulture ledger exception does not permit reachability authorization changes.
No sync conflict exists. No new tests planned absent a reproducible defect.

## Recorded progress

- Supplied logs independently read: dependency sync, Ruff, format, focused tests
  (346 passed, 3 skipped), inventory (16567) all succeed. No failing traceback.
- Prior result records a provenance blocker, not an actual codec test failure.
  Treat those claims as unverified until local commands run.
- Independently executed `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`: FAIL, both admission modules add unauthorized unreachable identities and dispositions (169 -> 171). This is an actual policy failure, not a missing dependency.
- Exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed identities/findings, zero unclassified. No ledger amendment is warranted.
- Read repository instructions and accepted ADR-081226-69ee, ADR-082526-7f02, ADR-083026-aba1 and ADR-083126-5e62. Preserve canonical execution ownership and immutable provenance; absent runtime callers must be stated, and candidate policy edits cannot self-authorize. No production activation or fake caller is an acceptable repair.
- Codec source explicitly states it has no production consumer (lines 50-54). It implements mapping-only encode/decode, not admission decisions. Source grep independently confirms only the codec's identity import and a Vulture whitelist import; neither supplies production reachability.
- Reviewed codec and identity tests, including independent task/run storage assertions at `test_admission_codec.py:134-137`, malformed storage injections, and the three real-pool cases. Synthetic DTO fixtures do not prove authorization or real model materialization.
- `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance command before the exact Vulture check. Passing Vulture alone cannot satisfy this job.
- Captured check-run evidence attributes `test: failure` to linked #1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not assigned HEAD; its output summary/text are null. Captured #1945 head `973772507c94428dba24fad7d9530490688d59e2` has coverage and exact-debt-ledger failures, also without traceback. Generic test failure at assigned HEAD remains UNRESOLVED, not repaired by guesswork.

## Independently executed validation

Commands ran in the assigned worktree with 1800-second timeouts. Source SHA is
unchanged from starting HEAD; only this report changed.

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q` | PASS: 349 nodes, 346 passed, 3 skipped, 2.98s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3301 files already formatted |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16567 unique identities; no copied-file duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

Exact Vulture passes; trusted-base provenance fails as recorded above. No test
added or removed, so inventory delta is zero and no new inventory note is
required. No mutation/pre-fix run is claimed in this documentation-only round.

## Acceptance audit

| Criterion | Executed evidence or limitation |
| --- | --- |
| Shared frozen/slotted header, exact interfaces and six typed codes | Source review plus focused DTO/codec tests; no clock or incoming request fingerprint parameter |
| Strict named scalar fields, UUID hex, signed timestamps, header/row agreement, unknown format fail-closed | Focused scalar, mismatch, schema and UUID tests pass |
| Validated hash only in errors; no snapshot/token in messages or displayed parser chain | Focused malformed JSON, token, nesting, lossy number and surrogate tests pass |
| Fresh flat encoding, separate generation/owner, binding consistency | Round-trip and fresh-mapping tests pass; storage task_id/run_id shape asserted independently of round-trip equality |
| Snapshot duplicate/nonobject/bare nonfinite rejection; tagged evidence and stored fingerprint preserved | Focused JSON/tagged round-trip tests pass; real model_of/model_of_json materialization and original-model fingerprint-before-tagging remain UNVERIFIED (fixtures supply pre-tagged synthetic snapshots) |
| Legacy bound/unbound/partial/receipt-only distinctions without invention | Focused legacy tests pass; a pair lacking receipt evidence is rejected rather than inventing the receipt required by the canonical binding |
| Header expiry/fingerprint survives invalid full decode | Both named header-separation tests pass; expiry replacement/409 precedence is C/F2, not claimed as B2 behavior |
| Same migrated disposable PostgreSQL DB, raw/production codecs, TEXT persistence | UNVERIFIED this round: all three PG cases skipped; no sessions, migration-chain execution, or SQL row counts claimed |
| Explicit authorized principals, Workspace/Project, registered Graph, object-valued Run JSONB | UNVERIFIED: synthetic DTO fixtures are not positive admission/Run persistence evidence |
| No SQL mutation/HTTP/queue/live assessor/scope/claim changes; canonical execution preserved | Source review and no Python edits this round; leaf is inactive |
| Focused pytest/Ruff/format/mypy and truthful inventory | PASS as above; no test delta |
| Unchanged full integration gates, no candidate-authored policy workaround | FAIL: trusted-base provenance rejects two unreachable modules and dispositions; full required integration CI is UNVERIFIED |
| Coordinated base/ownership, rollout constraints | Assigned local HEAD verified; external coordination release/activation permission UNVERIFIED; no activation or remote mutation |

## Disposition

**BLOCKED.** Changed file: this report only. Existing implementation and all
prior work preserved. No source/test defect was reproduced that warrants a
repair; no Vulture identity is unbanked. The inherited blocking evidence is
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The Vulture-specific ledger
exception does not authorize editing reachability policy, deleting retained
work, or adding a fake production import.

Next: owner supplies independently landed protected-base authorization or a
coordinated real integration consistent with the issue constraints, plus the
actual failing CI test node/traceback. No develop-sync conflict was found;
the conditional fetch/merge instruction does not apply. Repeating this same
unspecified test-repair dispatch cannot resolve the policy dependency.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker). Handoff
will be committed locally; no push or GitHub mutation. No integration approval.

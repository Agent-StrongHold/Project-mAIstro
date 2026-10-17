# Issue #1893 repair checkpoint — 71cf87aa

## Frozen scope and evidence

Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Starting source SHA: `b292254b5d5ae88d391ed58dd98525fb92b37921`.
Trusted develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (also the locally resolved `origin/develop`).
Initial tree clean; no incoming changes or merge conflicts to salvage.
Process issue #1893 only: the existing codec/identity modules, their adjacent tests,
applicable CI gates, and this report. No GitHub mutations or remote re-enumeration.
The supplied dispatch snapshot and logs are in job directory
`/home/dev/maistro/jobs/71cf87aa447941209bbf925a0039dc73`.

Read repository instructions, the full issue body in the dispatch snapshot,
prior result `6fbcb02240474f4b8325a85d4c8bef3c/result.json`, and driver
`check-0.log` through `check-4.log`. Driver results: sync, ruff, format and
inventory passed; focused tests 201 passed, 3 skipped. These are driver evidence,
not fresh database verification. The generic dispatched `test: failure` supplies
no failing node/traceback; no speculative source repair is justified.

Accepted ADR-082526-7f02 preserves immutable admission provenance and
Attempt-owned dispatch identity; ADR-081426-1f7c preserves Attempt-owned runtime
mechanics, not a competing domain authority. This leaf remains representation-only;
no change to `Goal -> Graph -> Run -> NodeRun -> Attempt` is authorized.

## Fresh reproduced blocker

Commands executed with 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1323 findings, zero unclassified. No Vulture ledger amendment is justified.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`: **exit 1**. Reachability and disposition checks reject both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`: 169 trusted entries become 171 without already-landed authorization. Other constituent checks passed.

Logs: `worker-vulture.log`, `worker-provenance.log` in the job directory.
The workflow `.github/workflows/vulture-ratchet.yml` requires both commands in
`exact-debt-ledger`. The reproduced blocker is not Vulture debt. The permitted
Vulture-only ledger exception cannot authorize reachability ledger edits. No
candidate grant, fake caller, or gate weakening is an acceptable repair.

## Validation and acceptance

Fresh commands at the starting source SHA, with 1200-second timeout:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, two files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: **201 passed, 3 skipped**, 204 nodes. The skipped raw/production pool cases explicitly require the two PostgreSQL environment variables. Log: `worker-focused.log`.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.

Read both source modules and both focused test files completely. Production-source
search for `admission_codec|admission_identity` found only the codec's DTO import
and the Vulture whitelist import, not a runtime caller. The codec docstring also
explicitly describes the missing consumer. Pure tests are not production reachability.

| Acceptance criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header, exact public interfaces and typed decode codes | Source inspection plus scalar/header mismatch and invalid-format tests passed. |
| Exact v2 DTO round trip, fresh flat SQL mapping, named columns | Three `test_v2_round_trip_preserves_all_snapshot_bytes` states and `test_encode_returns_a_fresh_flat_mapping` passed. Binding columns independently checked against migration-055 shape. |
| Storage-only UUID hex and signed timestamps | Owner-token, generation, header-scalar and DTO invalid-input tests passed. |
| No guessed legacy identity, partial/receipt-only disposition | Legacy unbound/bound/partial, receipt-only, missing receipt, unreadable and whitespace evidence tests passed. |
| Header evidence survives corrupt snapshot/partial binding; no clock or classifier | Expiry/fingerprint preservation and expired-header tests passed; signatures accept no clock or request fingerprint. No claim, HTTP, SQL mutation or queue path introduced. |
| Unknown formats/schemas fail closed | Unknown-format and missing-column tests passed, including supplied-header mismatch. |
| Strict snapshots and safe errors | Duplicate keys, nonobjects, bare nonfinite, deep nesting, lossy numbers and invalid Unicode tests passed, with suppressed parsing contexts. |
| Tagged evidence retained without fingerprint recomputation | Tagged nonfinite, valid Unicode and exact-number cases passed at the representation boundary. |
| Raw/production PostgreSQL pools, real migrated schema and durability | **UNVERIFIED**: three tests skipped; no database session/row-count evidence collected this round. |
| Real model materialization via evidence codecs, original-model fingerprinting and Run JSONB object insertion | **UNVERIFIED**: fixture tags are not model materialization or Run INSERT evidence. |
| Explicit authorized principals, Workspace/Project and registered Graph admission | **UNVERIFIED**: fixture identities establish representation only, not authorization or transactions. |
| Consumer inclusive expiry/409 precedence | **UNVERIFIED**, belongs to consumer integration rather than this inactive codec leaf. |
| Unchanged full required CI and dispatched `test: failure` | **UNVERIFIED**; focused failure not reproduced, failing CI traceback absent. Provenance gate independently fails. |
| Coordinated ownership/base and production activation | **UNVERIFIED/BLOCKED**; assigned repair ownership does not settle activation policy. |

No new source/test change is supported by these results. Existing tests were run
unchanged; no test count delta or new inventory note is required. No new regression
or mutation proof is claimed. Prior green database claims are not adopted as fresh
evidence. Bounded validation stops at the reproduced authorization blocker rather
than repeating unrelated full-suite/database runs against unchanged source/base.

## Handoff

Only this report changed. No ledger, grant, whitelist, gate, source or test edits.
Reachability entries in `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` remain rejected by the trusted-base
policy. Resolution requires the integration owner to coordinate the already-landed
reachability authorization required by the two-merge policy, or an independently
authorized runtime integration slice. This worker cannot grant that permission.
Provide the actual current-head CI `test` traceback before requesting a source repair.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 reproduced
provenance blocker; next: owner authorization and actionable CI evidence. This local
evidence commit is a blocked handoff, not integration approval or issue closeout.

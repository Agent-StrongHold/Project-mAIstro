# Issue #1893 repair checkpoint — dd8022b3

## Scope and decision

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Starting source SHA `c7e1cdce94a413aaec5f9ea46451b3bca5aef9b2`;
validated trusted base `435dc1937e0407ab4de198ffcced49860bb14ad2`.
Initial worktree was clean, with no conflict or incoming diff to salvage.
Frozen work item: #1893 only, its codec/identity implementation, adjacent tests,
applicable gates and this report. No remote enumeration, GitHub mutation or push.

Read repository instructions, the supplied issue body, prior result artifact,
driver `check-0.log` through `check-4.log`, codec source and focused codec tests,
identity constructors, and the exact-debt-ledger workflow. Driver checks passed,
with 201 focused tests passing and three PostgreSQL cases skipped; those are not
fresh durability evidence. The generic dispatched `test: failure` provides no
failing node or traceback in these logs. No guessed code repair is justified.

Accepted ADR-082526-7f02 requires immutable admission provenance and Attempt-owned
dispatch identity. Accepted ADR-081426-1f7c assigns physical execution mechanics
to the Attempt, not another domain authority. This representation-only leaf must
not invent admission identity or a consumer just to make reachability green.
`Goal -> Graph -> Run -> NodeRun -> Attempt` remains unchanged.

## Fresh validation

Commands below ran at the starting source SHA with 1200-second timeouts.
Logs are in `/home/dev/maistro/jobs/dd8022b3cdac49d7bd32d7939acd369b/`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1323 findings, zero unclassified; `worker-vulture.log`. |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | **Failed, exit 1**; `worker-provenance.log`. Both admission modules add unreachable modules and dispositions without already-landed authorization. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: **201 passed, 3 skipped**; `worker-focused.log`. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed: 3277 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed: two source files. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed: 16466 nodes, no duplicate evidence; `worker-inventory.log`. |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed; `worker-shipped-surface.log`. |
| `git diff --check` | Passed. |

The provenance gate reports 169 trusted dispositions/unreachable modules becoming
171. `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` remain unauthorized by the base.
The Vulture-only repair exception does not authorize reachability changes.
Neither candidate grants nor baseline edits can satisfy the two-merge rule.
No ledger amendment is warranted by the passing Vulture scan.

Production-source search (`rg -n 'admission_codec|admission_identity'
packages/*/src --glob '*.py'`) found only the codec's DTO import and the Vulture
whitelist import. There is no production codec consumer; the module explicitly
states this at `admission_codec.py:49-52`. Test imports are not runtime reachability.

## Acceptance evidence and limits

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header, supported versions, named scalar fields and header/row agreement | Header mismatch, invalid scalar, missing schema and unknown-format tests passed; source signatures inspected. |
| Exact immutable v2 records and fresh flat SQL parameter mapping | Round-trip tests passed for unbound, bound and acknowledged states; independent assertions require paired task/run columns and receipt identity. Fresh mapping test passed. |
| Storage-only UUID hex and signed timestamps | Owner token, generation, invalid scalar and DTO constructor tests passed. |
| No guessed legacy identity | Unbound/bound/partial, receipt-only, bound-without-receipt and invalid legacy evidence tests passed. `completed_at` is not authority. |
| Header evidence survives snapshot or binding failure | Expiry/fingerprint preservation and expired-header tests passed. Decoder accepts neither clock nor incoming fingerprint; no classification or mutation is performed. |
| Typed safe errors; strict snapshot objects | Duplicate keys, nonobjects, nonfinite literals, nesting, lossy numbers and invalid Unicode tests passed, including suppressed exception chains and validated error scope. |
| Tagged evidence and stored fingerprint preservation | Tagged nonfinite, exact-number and valid Unicode tests passed at the representation boundary. |
| Real migrated database, raw and production JSON-codec pools | **UNVERIFIED**: three tests skipped at `test_admission_codec.py:470`, requiring both PostgreSQL environment variables. No database session or row-count evidence collected this round. |
| Real model materialization, original-model fingerprinting and Run JSONB object INSERT | **UNVERIFIED**: hand-built tagged fixture snapshots are not model/Run persistence evidence. |
| Explicit authorized principals, Workspace/Project and registered Graph | **UNVERIFIED**: DTO fixtures do not establish authorization or admission transactions. |
| Consumer expiry/409 precedence, crash or dispatch invariants | **UNVERIFIED** and outside B2's representation-only scope; no consumer was added. |
| Unchanged full required CI / dispatched test failure | **UNVERIFIED**: focused tests pass, no failing CI traceback supplied, and required provenance gate fails independently. |
| Coordinated integration and production activation | **BLOCKED/UNVERIFIED**; assigned repair ownership does not settle activation policy or authorize another integration leaf. |

## Handoff

Only this evidence report is changed. No source, tests, whitelist, ledgers, grants
or gates were edited. Existing tests ran unchanged; no test inventory delta or
new mutation proof is claimed. Prior PostgreSQL verification claims were not
adopted as current evidence. Full-suite and disposable-database validation were
not repeated after reproducing the unchanged trusted-base authorization blocker.

Next: integration owner must coordinate the required already-landed reachability
authorization or an independently authorized runtime integration slice. Supply
the actual current-head failing CI test traceback before another source repair.
This checkpoint is not integration approval or issue closeout.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 reproduced
provenance blocker; next: owner authorization and actionable CI failure evidence.

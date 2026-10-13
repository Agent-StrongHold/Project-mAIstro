# Issue #1893 repair checkpoint — job 6abe224f

## Frozen scope

- Issue #1893 only; assigned branch `auto-1893`, clean starting head
  `7b16addf163a698a9bc1df89d32c13ad89cd7345`.
- Supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inspect the existing admission codec, immutable identity types, adjacent tests,
  applicable ADRs/workflows, supplied dispatch evidence and check logs.
- Candidate edits: evidence-backed codec/test repair if reproduced, this report,
  and inventory note if tests change. Vulture ledger edits only if its exact scan
  demonstrates reviewed retained debt. No reachability/grant edits authorized.
- Ambiguity: the dispatch says `test: failure` without a failing test node.
  Treat it as unverified until reproduced; do not alter unrelated tests.
- No new ownership, activation, scheduler or identity authority is authorized.

## Progress

Initial worktree clean and exact starting head confirmed. No incoming edits to
salvage. Prior success claims are not adopted.

Fresh execution: exact Vulture scan passed (1322 reviewed identities, zero
unclassified). No Vulture ledger change is justified. The provenance wrapper
with `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064` failed:
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each have
both a new unreachable module and a new disposition lacking trusted-base
authorization. Other wrapper gates passed. This is an actual blocker, not a
missing dependency or guessed scanner finding. Supplied check-0 through check-4
logs independently report sync/lint/format/inventory success and 324 passed,
3 skipped focused tests.

## Fresh validation at the starting source SHA

All commands ran in the assigned worktree with 1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 findings, zero unclassified |
| `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py` | FAIL, two unauthorized modules and two unauthorized dispositions; other wrapper gates including promotion pass |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q` | 327 nodes: 324 passed, 3 skipped |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 2229 nodes: 1919 passed, 310 skipped, 6 warnings |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16543 nodes, no duplicate evidence |

The six adjacent-suite warnings are aiosqlite worker threads reporting a closed
event loop in `tests/runs/test_sqlite_store.py`, not failing codec tests.
No source or tests changed; no inventory delta or new regression claim exists.

## Architecture and acceptance audit

Read repository instructions, docs authority hierarchy, accepted ADR-081226-a66b
(Run/NodeRun/Attempt ownership) and ADR-083126-5e62 (trusted-base quality authority).
No competing execution or authorization path was introduced. The issue permits
an inactive staged contract, not activation; inventing a runtime import to pass
reachability would violate that scope. A candidate ledger cannot authorize itself.

| Acceptance | Evidence and limits |
| --- | --- |
| Frozen/slotted header; named columns; signed timestamps; supported formats; header-row agreement | Reviewed codec lines 159–258; existing scalar, mismatch, schema and format tests passed. |
| Immutable v2 DTOs, flat fresh encoder, strict storage UUID hex | Existing round-trip, fresh mapping, owner-token and UUID tests passed. Binding columns independently asserted at test_admission_codec.py:134–137. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run; no guessed identity | Existing legacy tests passed. A pair without receipt is explicitly partial because the #1851 constructor requires receipt evidence; none is fabricated. Optional completed_at remains unread. |
| Header survives malformed snapshot/partial binding; no clock, incoming fingerprint or assessment | Existing expiry/fingerprint preservation tests passed. Consumer replacement/409 ordering remains outside B2 and UNVERIFIED here. |
| Strict snapshot objects, duplicates/nonfinite rejection, safe errors | Existing invalid JSON, excessive nesting, numeric precision-loss and surrogate corruption tests passed. They inject raw row TEXT and assert typed errors, suppressed chains and preserved header evidence. |
| Tagged nonfinite program_context and unchanged fingerprint | Existing tagged nan/inf/-inf tests passed. They prove tag retention, not actual model_of/model_of_json materialization or unchanged production request fingerprint calculation; those remain UNVERIFIED. |
| Real migrated PostgreSQL, both raw and production codecs, TEXT parameters and JSONB object payload | UNVERIFIED: both MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL are unset; all three codec PostgreSQL states skipped. No DB sessions or final SQL counts produced, and no skipped test is counted as durability evidence. |
| Explicit principals, authorized Workspace/Project, registered Graph kinds | UNVERIFIED for live admission: DTO fixtures are not authorization calls; this leaf remains inactive. |
| No SQL mutation, HTTP/queue mapping, scope utility, legacy/deletion policy or live assessor change | No production changes this round. Import search finds no production caller of admission_codec; identity is imported only by codec and Vulture whitelist. |
| Focused pytest, ruff, mypy, inventory and applicable gates | Commands above; provenance FAILS. Full required integration CI remains UNVERIFIED. |

## Failure attribution and handoff

The captured check-run evidence has a `test` failure on linked #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output text/summary,
and an `exact-debt-ledger` failure on linked #1945 head
`90d4c278e6d729d41a3f30d9f17bc65025d6f59d`. These are not the assigned head
and provide no failing test node. The reported merge-queue test failure remains
UNRESOLVED, not reproduced in the scoped suites; obtain its actual SHA-qualified
failure log before attempting a code repair. No extra GitHub fetch/mutation was
performed.

**BLOCKED.** Actual blocker: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612–613`. This round's Vulture exception
does not authorize changing these files or grants. Existing work is preserved.
Resolution requires campaign-owner coordination of trusted-base authorization
before a later integration, or a separately authorized scope decision; it cannot
be accomplished by documentation, candidate grants or artificial runtime callers.
There is no develop-sync conflict in the clean assigned starting worktree.

Only this evidence report changed. This is a committed handoff, not a completed
implementation repair or integration approval. Remaining checks include real
disposable-PG durability and full required integration CI on the coordinated head.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 blocking provenance
command. Next: resolve protected-base policy outside this lane and supply the
actual failing test log. No new mutation/pre-fix test evidence because no code or
test repair was justified.


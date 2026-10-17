---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — f75b

## Scope and decision

Assigned worktree `/home/dev/Git/wt/auto-1893`; starting source
`a37a52ad217e4e0f076e647481c758a9bf390aeb`, supplied develop base
`675db8be6c41b020ffffb224b2748c159c78a122` (also the resolved local
`origin/develop`). Starting tree clean. Frozen repair scope: #1893 codec,
its tests/inventory evidence, and Vulture ledger only for actual scanner
findings. This note is the only repository change; no tests added or removed.

Read the supplied dispatch issue, latest captured coordination comments, prior
result, driver logs, codec, adjacent immutable types/tests, migration 055,
production pool fixture, and accepted ADR-081226-a66b and ADR-083126-5e62.
Historical coordination text does not authorize activation; the lane assignment
is interpreted as local staged repair authority only. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and trusted-base quality authority.

The reported binding bug is **already fixed**: `admission_codec.py:291` encodes
`binding.receipt_id` as `task_id`; `_v2_binding` rejects partial/mismatched pairs.
Migration 055 requires both binding columns and `task_id = receipt_id`.
Fresh tests and a regression mutation confirm this, not earlier verification
claims. No evidence warrants another source edit or Vulture amendment.

## Executed validation

Commands ran against the starting source above. Raw logs, collected node IDs
and JUnit properties are under
`/home/dev/maistro/jobs/f75b7b090e9d4449a8438ab7d385b100/repair-*`.

- Inspected supplied `check-0.log` through `check-4.log`: sync, Ruff, formatting
  and inventory pass; focused tests report 201 passed / 3 skipped. Those skips
  are not database evidence.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **exit 0**, 1326 reviewed
  identities / 1326 findings. No unbanked identities.
- `RATCHET_BASE_REV=675db8be6c41b020ffffb224b2748c159c78a122 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**. The trusted merge base is
  `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. The gate rejects NEW unauthorized
  reachability/disposition debt for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` (`repair-provenance.log:20-29`).
  This is not Vulture debt and cannot be repaired by candidate banking.
- `createdb maistro_1893_f75b`, then
  `DATABASE_URL=postgresql:///maistro_1893_f75b uv run alembic upgrade head`:
  **passed**, fresh dedicated disposable native PostgreSQL database migrated
  through the actual chain, including 055, to 061. No stamping or SQLite.
- With `MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_f75b`,
  `MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_f75b`, and
  `MAISTRO_REQUIRE_PG_LEGS=1`, ran `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, zero skips**. Same two paths with `--collect-only -q`:
  **204 nodes** recorded in `repair-nodes.log`.
- The real-pool tests require non-null `pg_pool`, use production JSON codec
  registration and an independent raw pool, and compare same-server/database
  identities. Production/raw PostgreSQL PID pairs: **3478091/3478092**
  (unbound), **3478093/3478094** (bound), **3478095/3478096** (acknowledged).
  All use `maistro_1893_f75b` via Unix socket. Each persists exactly **one**
  scoped admission row. Final SQL: revision **061**, **0 rows / 0 generations /
  0 bound Run IDs** after cleanup. Database retained; no downgrade performed.
- In-process encoder mutation setting `task_id=None`, followed by
  `pytest.main` on the codec file with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: expected **exit 1**,
  **2 failed / 1 passed / 128 deselected**. Both bound states fail the independent
  storage assertion at `test_admission_codec.py:134`. Source files unchanged.
- `uv run pytest packages/maistro-core/tests/tasks -x -q`: **627 passed /
  20 skipped** without PG environment; adjacent-suite evidence only, not a
  substitute for the explicitly configured zero-skip database run above.
- `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **exit 0**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **exit 0**.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, and `promotion-surface`:
  **exit 0**. Candidate agreement does not override trusted-base failure.
- Production-source import search finds only codec-to-types and Vulture
  whitelist references, no production consumer of this codec. Test callers,
  exports and pool-codec registration are not runtime admission reachability.

## Acceptance audit

| Criterion | Fresh evidence and boundary |
| --- | --- |
| Exact frozen/slotted header, named columns, header-row scalar match, fresh flat mapping | Source inspection and passing codec/identity tests. Physical `request` TEXT maps to the snapshot DTO per migration 055. |
| v2 snapshot/binding round trip | Named round-trip test in all three states, real migrated PG tests, and failing historical-bug mutation. |
| Owner token hex at storage only | Named owner-token test and strict UUID/repr/error tests pass. |
| Legacy bound/unbound/partial distinctions, no identity guesses | Named legacy test, missing receipt, receipt-only, partial pair and unreadable/whitespace cases pass. A pair without receipt evidence cannot satisfy the #1851 binding constructor and stays partial. |
| Expired legacy header preserves evidence without inventing identity | Named test passes; decoder takes no clock. |
| Header expiry survives malformed snapshot | Named separation test plus invalid/duplicate JSON cases pass. |
| Header fingerprint survives partial binding | Named test passes; fingerprint is never recomputed. |
| Unknown format cannot become legacy | Named unknown-format and scalar-mismatch cases pass. |
| Tagged nonfinite evidence, unchanged fingerprint | Synthetic nan/inf/-inf tests pass. Actual evidence-json/model_of/model_of_json model materialization with arbitrary program_context remains **UNVERIFIED**. |
| Invalid/duplicate/nonobject/bare nonfinite JSON rejected safely | Named JSON, precision, recursion and Unicode tests pass; safe errors and suppressed exception chains asserted. |
| Raw and production pool codecs read identical TEXT snapshots | Three real PG cases pass with distinct sessions and the same migrated database; escaped-surrogate corruption is also rejected through both pools. |
| No SQL mutation/HTTP/queue/assessment/claim policy changes | This repair is note-only; inspected codec remains a pure representation leaf. |
| Unchanged required CI and reachable production behavior | **Not proven**: provenance gate fails and no production consumer exists. Hosted `test: failure` has no executed traceback here; attribution and full required CI remain **UNVERIFIED**. |

Authorized principals/Workspace/Project and registered-Graph admission,
`json_of(run)` TEXT-to-JSONB object insertion, live expiry/409 precedence,
transaction/crash/dispatch invariants and downgrade/adoption are **UNVERIFIED**
by these synthetic codec DTO tests. The SQL round trip is representation proof,
not authorization or production activation proof.

## Handoff — BLOCKED

No justified source or ledger repair remains within this lane. The integration
owner must resolve real consumer wiring or separately landed trusted-base
reachability authorization under existing governance. Neither a fake caller,
a new execution authority, nor a candidate grant is permitted here. Do not
redispatch this unchanged branch as another Vulture repair. Obtain the hosted
failing test traceback before assigning an unrelated test change to #1893.

Progress: checked **1** issue; done **1** validation/handoff; skipped **0**
issues; errors **1** unresolved executed gate. No merge, push, GitHub mutation,
grant edit or activation. Local commit records this checkpoint only.

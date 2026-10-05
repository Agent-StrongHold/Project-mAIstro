---
inventory-delta:
  packages/maistro-core/tests: +66
---
# atomic-admission-b2

## What moved

B2 of the #1845 admission-decode stack (#1893): the new
`maistro.tasks.admission_codec` module turns forward-schema admission rows
into exact #1851 immutable DTOs or typed fail-closed errors, and the new
`packages/maistro-core/tests/tasks/test_admission_codec.py` pins that
contract with 66 tests. All 66 are pure unit tests over `Mapping` rows — no
database, no clock, no HTTP — because the forward schema itself is B1
(#1892), which is not on this branch yet.

## Base provenance

The assigned lane head was bare develop (`680329c96`). The #1893 prerequisite
(#1851 typed vocabulary) lives on `origin/auto-1851`, so the work is staged
as: merge `origin/auto-1851` (clean, additive ledger rows only — verified
against `origin/develop` by row diff), then the codec leaf on top.

## Why unit-level only

The issue gates database round-trip tests on B1: "The forward schema leaf
#1892 (B1) is required for database round-trip tests; pure codec work may be
prepared earlier." The prospective
`test_raw_and_production_pool_codecs_read_identical_text_snapshots` is
therefore pinned at the value level here (snapshots are TEXT str in both
pool kinds; a pre-decoded value is rejected, never silently accepted), and
the real raw-asyncpg vs `_register_json_codecs` two-pool contrast against
the migrated schema lands with B1. No skipped test is counted as durability
proof — there are no skips in this file.

## Contracts worth remembering

- Header decode is scalar-only and deliberately skips cross-field timestamp
  ordering, so C can order valid header → inclusive expiry → fingerprint →
  full decode; header evidence survives every full-decode failure.
- Unknown `format_version` (including `True`/`1.0`, which `==` would equate
  to 1) fails `unsupported_format` and can never reach a legacy record;
  `decode_admission_record` re-derives the header structurally, so a loose
  `==` can never launder a non-scalar column into a supported format.
- Legacy binding: both ids + receipt identity is bound; neither + no receipt
  evidence is unbound; one-sided pairs, receipt-only rows, unreadable
  evidence, and bound-pairs-without-receipt are all `partial_legacy_binding`
  — a receipt is never fabricated to make a row fit.
- The v2 mapping always emits `task_id` as NULL: the #1851 DTO is
  task-agnostic by design, and the binding statement owns that bookkeeping.
  `test_v2_round_trip_preserves_all_snapshot_bytes` pins the resulting
  encode→decode→encode identity.
- Error messages never quote snapshot bytes or owner tokens, and parsing
  chains are suppressed (`__suppress_context__` asserted).

## Repair-round revalidation evidence (L1893, head 532944f92)

After syncing the coordinated develop base (8a4bc239f, via merges a8931abb0
and 532944f92 — the `_vulture_whitelist.py` conflict resolved as the exact
union of both sides' rows, no row dropped), every gate in this leaf's scope
was re-run at the merged head:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  -> 66 passed (matches the +66 delta above).
- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks -q` -> 551 passed, 16 skipped (the skips
  are the PG-DSN-gated durability tests; not counted as proof, per the issue).
- `uv run ruff check .` and `uv run ruff format --check .` -> clean.
- `uv run mypy packages/maistro-core/src/maistro/tasks
  packages/maistro-core/src/maistro/runs/admission_identity.py` -> clean.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> 1338 reviewed
  identities, 1338 banked, exit 0.
- `check-reachability-dispositions.py`, `check-suite-inventory.py`,
  `check-convergence-matrix.py`, `check-backlog-consistency.py`,
  `check-execution-lifecycles.py`, `check-model-egress.py`,
  `check-doc-links.py` -> all exit 0.
- `check-reachability.py` -> exit 1, reporting exactly the newly-unreachable
  `maistro.tasks.admission_codec` predicted below. Unchanged by design at that
  head: this leaf made no baseline edit, so the gate stayed honestly red until
  the codec leaf itself reconciled the ledger (next section).

## CI-repair round (L1893, branch head after 0d663a48e)

CI at `0d663a48e` failed four checks with one shared root cause and one
structural residual, both now measured locally:

- **Shared root cause (fixed here):** `maistro.tasks.admission_codec` was
  newly unreachable and absent from the candidate ledger. That single fact
  red `check-reachability.py`, the three root-suite tests that pin the
  committed baseline to the tree
  (`tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::
  test_the_committed_baseline_passes_the_gate_it_now_carries` and
  `::test_the_baseline_is_exactly_the_unreachable_set` — i.e. the `test` job),
  the Quality gate's reachability/disposition steps, and the Coverage gate's
  combine step (which re-runs the root suite as the `scripts` producer and
  aborts on its failure). The repair banks the module in
  `quality/reachability-baseline.json` (unreachable, `_generated_from`
  refreshed to the measured 1266) and extends the existing CONNECT group
  `runs-root-admission-contracts` in `quality/reachability-dispositions.json`
  to cover it, naming the C leaf's consumer as the reaching root; the
  convergence matrix's `Task queue and runner` row moves `none` -> `few` to
  match the recomputed 1/16 share (same repair as #1851's matrix sync). This
  is the ledger describing the tree, not a gate change: the module is
  recorded as built-but-never-wired with an owner and a named future
  consumer, and the entry leaves the baseline when the C leaf lands.
- **Structural residual (recorded, not fixable in-branch):**
  `scripts/check-ratchet-provenance.py` (the exact-debt-ledger wrapper) still
  fails: both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are NEW unreachable modules and NEW
  dispositions relative to the merge base `8a4bc239f`, and
  `ratchet_provenance.load_authorizations` reads
  `quality/ratchet-authorizations.json` **from the merge base**, so a
  candidate-side grant is inert by construction ("banking is not
  authorizing"; the two-merge rule). The only in-branch "fixes" — wiring the
  consumer (forbidden: the C leaf owns it and this leaf forbids live
  `_assess` changes), an `__init__` re-export (the issue itself rules
  package exports out as runtime reachability), or an
  `_EXCLUDED_PACKAGE_PYTHON` entry (gate modification) — are all dishonest or
  out of scope. Resolution requires the campaign to land the reachability
  authorizations on the integration base first, then re-evaluate this
  branch; until then the exact-debt-ledger red is the truthful state.

Re-run at the repaired head (all locally executed):

- `uv run python scripts/check-reachability.py` -> exit 0, 1266 production
  modules, 174 unreachable, 0 newly unreachable.
- `uv run python scripts/check-reachability-dispositions.py` -> exit 0, 50
  groups give all 174 modules a disposition (150 CONNECT, 22 LIBRARY,
  2 RETIRE).
- `uv run python scripts/check-convergence-matrix.py` -> exit 0, 52
  subsystems classify all 1266 modules; 174 unreachable attributed.
- `uv run pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py -q` -> 38 passed (the three
  previously failing tests included).
- `uv run pytest tests/test_m1_542_policy_coverage.py
  tests/test_m1_convergence_freeze.py tests/test_check_citation_status.py
  tests/test_check_reachability_dispositions.py -q` -> 301 passed.
- `scripts/check-ratchet-provenance.py` -> exit 1, residual exactly the two
  unauthorized NEW unreachable modules and two NEW dispositions above; every
  other ratchet in the wrapper (adr-status-language, citation-status,
  promotion-surface, shell-execution, contract-markers, enumerations,
  lifecycle) reports no candidate-approved expansion.
- Diff coverage (core producer, `scripts/check-diff-coverage.py` with the
  `--source=packages/maistro-core/src/maistro` producer XML): both new
  modules clear the 90% line / 80% branch floors per file
  (`admission_identity.py` 98%, `admission_codec.py` 92%);
  `_vulture_whitelist.py` sits outside every measured root and is named
  unmeasured, per the gate's own output.

## CI-repair round 2 (L1893, head 8d76655aa after develop sync + radon fix)

CI at `b9ddf1b75` failed exactly two checks: the Quality gate's **radon CC
ratchet** step and the **exact-debt-ledger** job. The previous section's
"fixed here" claim about the Quality gate was therefore incomplete — the
reachability banking fixed the gate's reachability/disposition steps and the
`test` job, but the gate stayed red for a second, unrecorded cause: radon.
Recorded here so the note matches the measured gate, per the drift finding.

- **Radon (fixed here, in-branch refactor):**
  `scripts/check-radon-baseline.py` reported one new unbaselined block vs the
  trusted base: `admission_codec.py:202 decode_admission_header -> C (11)`.
  The block was refactored, not banked: the inline format-version coercion
  and scope/fingerprint hex validation moved into two new A-graded helpers
  (`_coerce_format_version`, `_require_hex`), leaving the public function at
  A (1); `_hex64` became a `TypeGuard[str]` so the extraction stays mypy-clean.
  Behavior is preserved by the existing tests — including the
  `bad_format in [3, 0, -1, None, "1", True, 1.0]` parametrization that pins
  bool/float rejection. No radon ledger entry was added or needed.
- **Exact-debt-ledger (structural residual, unchanged):**
  `scripts/check-ratchet-provenance.py` still fails on exactly the two NEW
  unreachable modules / NEW dispositions (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec`) relative to the merge base —
  `ratchet_provenance.load_authorizations` reads grants from the merge base,
  so a candidate-side bank is inert (two-merge rule). Every other ratchet in
  the wrapper reports no candidate-approved expansion. Resolution stays
  campaign-level: land the reachability authorizations on the integration
  base first, then re-evaluate. The issue itself forbids the in-branch
  "fixes" (wiring the C consumer, `__init__` re-exports, exclusion entries).

Re-run at this head (all locally executed, develop synced first — merge of
`origin/develop` `94781cf6b` brought #1976's handler-identity gate, no
conflicts, no production-module change):

- `uv run python scripts/check-radon-baseline.py` -> exit 0; 143 -> 143
  C-or-worse blocks vs base `94781cf6b`, 0 new / 0 regressed / 0 stale.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  -> 139 passed (the two focused files; +66 delta above unchanged).
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -q` -> 1674 passed, 263 skipped
  (skips are PG-DSN-gated; not counted as proof).
- `uv run ruff check .` and `uv run ruff format --check .` -> clean.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` -> clean;
  the 5 remaining `packages/maistro-core/src` errors are pre-existing
  `maistro_bootstrap` import-not-found (bootstrap extra not synced in the
  worktree), identical on the merge parent — zero new mypy errors.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> exit 0.
- `uv run python scripts/check-shipped-surface-truth.py` -> exit 0.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` -> ok (13429 identities match inventory).
- `uv run python scripts/check-reachability.py` -> exit 0 (1267 production
  modules, 174 unreachable; the committed baseline still matches the tree
  after the develop sync) and `uv run pytest
  tests/test_check_reachability.py tests/test_reachability_baseline_identity.py
  -q` -> 38 passed.
- `scripts/check-ratchet-provenance.py` -> exit 1, residual exactly the two
  campaign-level items above; nothing else moved.

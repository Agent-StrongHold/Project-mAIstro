---
inventory-delta:
  packages/maistro-core/tests: +70
---
# atomic-admission-b2

## What moved

B2 of the #1845 admission-decode stack (#1893): the new
`maistro.tasks.admission_codec` module turns forward-schema admission rows
into exact #1851 immutable DTOs or typed fail-closed errors, and the new
`packages/maistro-core/tests/tasks/test_admission_codec.py` pins that
contract with 70 tests. Sixty-nine are pure unit tests over `Mapping` rows;
one is a PostgreSQL durability test gated on the required disposable database.
At the original B2 leaf B1 (#1892) was not yet on the coordinated branch; the
real-pool test was added only after B1 reached this branch.

## Base provenance

The assigned lane head was bare develop (`680329c96`). The #1893 prerequisite
(#1851 typed vocabulary) lives on `origin/auto-1851`, so the work is staged
as: merge `origin/auto-1851` (clean, additive ledger rows only — verified
against `origin/develop` by row diff), then the codec leaf on top.

## Database durability boundary

The issue gates database round-trip tests on B1: "The forward schema leaf
#1892 (B1) is required for database round-trip tests; pure codec work may be
prepared earlier." B1 is now present, so
`test_raw_and_production_pool_codecs_read_identical_text_snapshots` is the
real raw-asyncpg versus `_register_json_codecs` pool contrast against its
migrated TEXT schema. `test_text_snapshots_reject_predecoded_values` retains
the complementary pure value-level boundary. Neither test treats a skipped
PostgreSQL leg as durability proof.

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
  encode→decode→encode identity. A v2 bound row must additionally have
  `task_id == receipt_id`: although the DTO intentionally omits task queue
  bookkeeping, the codec validates that immutable storage invariant before it
  drops the column, so corrupt storage cannot be re-described as a valid
  canonical binding.
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

## CI-repair round 3 (L1893, head 7a0669c7c — hosted-CI log reconciliation)

This round reconciled the merge-queue report ("test: failure") against the
hosted CI runs themselves (read-only API), then re-proved every gate at this
head instead of trusting earlier claims:

- **Hosted run 37257451206 (`CI` at `0d663a48e`): the `test` job failed on
  exactly three tests** — `tests/test_check_reachability.py::
  test_baseline_matches_the_tree`, `tests/test_reachability_baseline_identity.py::
  test_the_committed_baseline_passes_the_gate_it_now_carries` (assert 1 == 0)
  and `::test_the_baseline_is_exactly_the_unreachable_set`. The logged diff
  (baseline index 144: `maistro.testing` vs `maistro.tasks.admission_codec`,
  plus a missing `maistro_rsi.rate_pacer` on the tree side) matches the
  round-1 ledger state before the develop sync; at this head the committed
  baseline is sorted, contains both new modules and `maistro_rsi.rate_pacer`,
  and the two files pass (38 passed, locally re-run). Hosted corroboration:
  the same workflow is green at `b9ddf1b75` (run 37265891410).
- **Hosted run 37265891390 (`quality` at `b9ddf1b75`): the only failed step
  was the radon CC ratchet** (job step list queried via API) — the cause the
  round-2 section records, fixed by the `7a0669c7c` refactor.
- **Hosted run 37265891391 (`Vulture Ratchet` / `exact-debt-ledger` at
  `b9ddf1b75`): failed at its first step, `check-ratchet-provenance.py`** —
  the two-merge residual below.

Re-proven at this head (all locally executed; mypy under CI's
`uv sync --locked --all-extras` environment):

- The full Quality-gate ratchet battery in CI's exact form, all exit 0:
  `check-radon-baseline.py` (143 -> 143 C-or-worse vs base `94781cf6b`),
  `check-release-consistency.py`, `check-doc-links.py`,
  `check_enumerations.py`, `check-workspace-retirement.py`,
  `check-route-permissions.py`, `check-principal-identity.py`,
  `check-frontend-typed-client.py`, `check-credential-authority.py`,
  `check-wiring-reads.py`, `check-agent-store-writes.py`,
  `check-contract-markers.py`, `check-convergence-matrix.py`,
  `check-reachability-dispositions.py`, `check-security-inventory.py`,
  `check-image-inventory.py`, `check-image-pins.py`,
  `check-workflow-inventory.py`, `check-backlog-consistency.py`,
  `check-promotion-surface.py`, `check_direct_effects.py`,
  `check-reachability.py` (1267 modules, 174 unreachable),
  `check-shipped-surface-truth.py`.
- `uv run mypy --strict packages/maistro-core/src` -> Success, 708 files,
  after `--all-extras` sync (the 5 `maistro_bootstrap` import-not-found
  errors in the `--extra dev` env are environmental, not code).
- Full changed-package suite: `uv run pytest packages/maistro-core/tests -q`
  -> 12540 passed, 888 skipped, 1 xfailed (skips are PG-DSN-gated; not
  counted as proof).
- Focused: both admission files -> 139 passed (delta +66 unchanged).
- Vulture at CI's exact invocation (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) -> exit 0, 1338 reviewed identities -> 1338
  banked. **No unbanked identity exists, so the CI-repair round's vulture
  ledger amendment is moot: nothing is genuinely dead and no row is removed.**

**Two-merge landing path proven by experiment (scratch worktrees, no tree or
branch mutation of this lane):** a probe commit `3235229f5fed` (develop
`94781cf6b` + only the two `reachability` grants for
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` in
`quality/ratchet-authorizations.json`, owner/issue/reason fields complete)
merged with this head (probe merge `083a660e2eff`) makes
`RATCHET_BASE_REV=3235229f5fed uv run python scripts/check-ratchet-provenance.py`
exit 0 — every ratchet OK including "174 unreachable module(s), no
candidate-approved expansion" and "174 unreachable module(s) have
dispositions; new debt uses prior reachability authorization". The grant
payload and landing order are therefore proven, not guessed: the campaign
lands the two grants on the integration base first, this branch syncs it,
and the exact-debt-ledger goes green without any further change here.

## CI-repair round 4 (L1893, head 190ee154b — probe independently executed)

The round-3 probe experiment was recorded as claimed-not-independently-
executed by the verifier (job `ad3b492fdf104195b3202f8750dc1921`). This
round executed it for real against the final head, with persistent
artifacts instead of scratch worktrees:

- Probe state: worktree `~/Git/worktrees/probe-1893-grant`, branch
  `probe/grant-1893-merged-head`, merge `0521ce4fd252` = `190ee154b` +
  grant commit `3235229f5fed` (whose parent is exactly develop tip
  `94781cf6b`, so it is a fast-forwardable develop landing). Merge was
  clean: only `quality/ratchet-authorizations.json` (+10 lines).
- `RATCHET_BASE_REV=3235229f5fedd7f9ba876650b4baad0ef22d9993 uv run python
  scripts/check-ratchet-provenance.py` -> **exit 0**: both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  print `authorized: ... #1893 -- @BlakeMatthews-dev: ...`, reachability
  reports "174 unreachable module(s), no candidate-approved expansion" and
  dispositions "174 unreachable module(s) have dispositions; new debt uses
  prior reachability authorization". `check-shipped-surface-truth.py` and
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (1338 -> 1338) also exit 0 under the same base — the
  complete exact-debt-ledger job is green in the post-landing state.
- At this head without the grant (base `94781cf6b`),
  `check-ratchet-provenance.py` still fails on exactly the two reachability
  provenance gates (NEW unreachable modules + NEW dispositions, both
  unauthorized from trusted base); every other sub-ratchet is OK. Vulture
  again exits 0 with no unbanked identity, so the mandated vulture-ledger
  amendment remains moot.
- `test`-job suites locally in CI's form: root
  `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=
tests/tools/registry` -> 4375 passed, 90 skipped; full changed package
  `packages/maistro-core/tests` -> 12540 passed, 888 skipped, 1 xfailed;
  untouched packages (server/canvas/turing/bootstrap) collect cleanly
  (502/519/210/238) so the core edits broke no import surface. Local
  footgun recorded for future rounds: running ratchet gates locally writes
  gitignored `quality/ac-state.json`, which then fails
  `tests/test_branch_independence_repository.py` ("unclassified quality
  state") until moved aside — a local artifact, not a repo defect; hosted
  `test` never sees it because each job is a fresh runner.
- Behavioral acceptance spot-checks re-executed against the production
  codec at this head: receipt-only and one-sided task/run rows ->
  `partial_legacy_binding` with the receipt id absent from the message;
  `format_version=7` -> `unsupported_format`; no raw snapshot bytes in any
  decode error message; header/row scalar mismatch -> `invalid_header`;
  an unvalidated scope hash keeps `scope_key=None`.

Residual: the exact-debt-ledger red at this head is the documented two-merge
rule, not a defect repairable inside this worktree. The campaign action that
makes it green is fully specified and now execution-proven: land the grant
commit (fast-forward `3235229f5fed` or an equivalent two-entry
`reachability` grant) on develop, then merge origin/develop here — the probe
merge `0521ce4fd252` is that exact state and passes every gate.

## CI-repair round 5 (L1893, head b739b00dd — develop sync to 30677b185)

The merge-queue evaluation reported `test: failure` with develop advanced to
`30677b185` (two commits this branch did not have: `1885c8eda` research #919 +
`30677b185` epic M8-J docs). The branch merged `origin/develop` cleanly
(merge `b739b00dd`; only docs + `packages/maistro-rsi/tests/
test_m8b5_corouting_benchmark_research.py` + that leaf's inventory note came
in — no production code, no ledger, no frontend/OpenAPI surface). Every
Python step of the `test` job re-run at the merged head in CI's form:

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=
  tests/tools/registry` -> 4413 passed, 104 skipped.
- `packages/maistro-core/tests` -> 12540 passed, 888 skipped, 1 xfailed;
  `packages/maistro-bootstrap/tests` -> 237 passed; `packages/maistro-
  server/tests packages/maistro-canvas/tests` -> 958 passed, 83 skipped;
  `packages/maistro-turing/tests packages/maistro-turing/backend/tests
  packages/maistro-design/tests` -> 840 passed; `PYTHONPATH=packages/
  maistro-rsi/src:packages/maistro-evolve/src ... packages/maistro-rsi/tests
  packages/maistro-evolve/tests` -> 2015 passed, 6 skipped (includes develop's
  new #919 file).
- `python scripts/check-suite-inventory.py` (full, 14 suites) -> ok,
  26186 node IDs; `scripts/check-test-duplicates.py` -> ok; `ruff check .` +
  `ruff format --check .` -> clean; CI's nine-package `mypy` -> "Success: no
  issues found in 943 source files"; `verify-monorepo-layout.sh`,
  `check-merge-markers.py`, `check-cross-package-imports.py` -> ok.
- The `test` steps not runnable here (npm lint/build/audit, hive-conductor
  backend venv, generated-OpenAPI-types diff, one-process combined run) are
  unchanged by diff — `git diff --stat origin/develop...HEAD` touches only the
  ten declared B2 surfaces, none under hive-conductor/frontend/maistro-server
  — and were hosted-green at head `7035433722` (`test` check-run success), so
  the `test` failure is accounted for by the un-synced develop divergence
  this round removed.

Gates at the merged head: vulture CI-exact 1338 -> 1338 exit 0 (still nothing
unbanked — the mandated vulture-ledger amendment remains moot);
`check-shipped-surface-truth.py` exit 0; radon 143 -> 143 exit 0;
`check-convergence-matrix.py` OK (1268 modules, 174 unreachable attributed);
`RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` exit 1 on
exactly the two reachability provenance gates (NEW unreachable
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec`, NEW
dispositions; trusted base resolves to `9a5eb7ba6`, which has 11 reachability
grants, none admission). Probe re-executed at the post-sync head: merge
`730f71ff1d` = `b739b00dd` + grant `3235229f5fed` (branch
`probe/grant-1893-b739b`), `RATCHET_BASE_REV=3235229f5fed...` -> full
aggregator exit 0 (174 unreachable, dispositions "new debt uses prior
reachability authorization"), vulture + shipped-surface exit 0 under the same
base. The grant-landing unblock path is therefore re-proven at the current
head, not inherited from round 4.

## CI-repair round 6 (L1893, head 384c4f268 — revalidation after round-5 provider death)

Round 5's writer died on a provider timeout after its five driver checks had
already passed (jobs/644eaadd.../result.json: `failure_kind=provider_error`,
all five checks returncode 0); the merge-queue "block" to resolve was that
death, not a new gate signal. Every driver check re-executed independently at
the unchanged head `384c4f268`:

- `uv sync --locked --extra dev` ok; `ruff check .` clean; `ruff format
  --check .` 2926 files clean; focused `pytest packages/maistro-core/tests/
  tasks/test_admission_codec.py packages/maistro-core/tests/runs/
  test_root_admission_identity.py -q` -> 139 passed (66 + 73, matching both
  notes' inventory deltas); `check-suite-inventory.py --suite
  packages/maistro-core/tests` -> ok, 13429 collected node IDs.
- CI's exact nine-package `mypy` -> "Success: no issues found in 943 source
  files" (a bare `packages/maistro-core/src` run reports only cross-package
  `import-not-found` for `maistro_bootstrap`, which CI's form resolves).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` -> 1338 -> 1338 exit 0: nothing unbanked, so the
  round's conditional vulture-ledger amendment stays moot.
- `check-shipped-surface-truth.py` exit 0; `check-convergence-matrix.py` OK
  (1268 production modules, 174 unreachable attributed). The
  `reachability-baseline.json` `_generated_from` string still reads "1266"
  vs 1268 measured — informational only: no gate parses it (verified by
  grep across check-reachability*.py and check-convergence-matrix.py), and
  the count drifts with every develop sync by construction.
- Acceptance re-read against source at this head: all six required
  `admission_codec` interfaces present and conformant
  (frozen/slotted `AdmissionRowHeader`, header re-derivation mismatch ->
  `invalid_header`, fresh flat `encode_admission_record` mapping with
  `task_id` always NULL, six-value `AdmissionDecodeCode`,
  `AdmissionRowDecodeError` carrying only a hex64-validated `scope_key` with
  `__suppress_context__` asserted in tests); all ten prospective tests from
  the issue body exist by exact name; zero clock reads in either new module;
  legacy `completed_at` never read; three-dot diff vs `origin/develop`
  (`cd5618223...HEAD`) is exactly the ten declared B2 surfaces and touches
  no `quality/ratchet-authorizations.json` (no self-authorization).
- develop re-fetched before judging: still `cd5618223`; its
  `ratchet-authorizations.json` has no admission entries and its
  reachability baseline has no admission rows — the grant has still not
  landed upstream, so `check-ratchet-provenance.py` exit 1 persists on
  exactly the two reachability provenance gates (base resolves to the
  develop merge point `30677b185`). This remains the documented two-merge
  rule, not a repairable defect: the issue text forbids
  baseline/grant/gate modifications to make an unwired slice green, and the
  round's ledger-amendment exception names only the vulture ledger.
- Probe semantics re-verified, correcting a tempting shortcut: setting
  `RATCHET_BASE_REV=3235229f5fed...` on the bare branch head does NOT pass —
  `resolve_baseline` merge-bases the rev with HEAD and collapses to the
  grant's parent `94781cf6b`, where the grant is invisible (exit 1, same two
  gates). The grant must be an ancestor of the candidate. Fresh probe-merge
  `bf2075282` = `384c4f268` + `3235229f5fed` (detached worktree
  `~/Git/worktrees/probe-1893-round6`, left in place as evidence): after
  `uv sync --locked --extra dev`, `RATCHET_BASE_REV=3235229f5fed...` ->
  aggregator exit 0 (all nine ratchets OK; reachability-dispositions "new
  debt uses prior reachability authorization"; 49 quality-JSON consumers
  provenanced), and the other two exact-debt-ledger steps exit 0 under the
  same base. The grant-landing unblock path is therefore re-proven at this
  round's head for the third consecutive head.

Round-6 conclusion: unchanged from round 5 — the only remaining action is
campaign-level (land the two-entry `reachability` grant on develop, then
merge origin/develop here); no in-branch edit can or may change this.

## CI-repair round 7 (L1893, head e86ce9b19 — develop advanced, unblock path re-proven at the newest develop)

This round's lane brief re-issued the BLOCKED block and the merge-queue
"test: failure" signal; the only upstream change since round 6 is develop
itself. develop was re-fetched before judging: `origin/develop` advanced
`30677b185` -> `30144ad0f` (10 commits, including upstream B1-adjacent work —
`alembic/versions/055_task_admission_generations.py`) — and the grant is
STILL not upstream: develop's `quality/ratchet-authorizations.json` is
byte-identical to this branch's (no admission entries) and its
`reachability-baseline.json`/`reachability-dispositions.json` carry neither
admission module. The two-merge blocker therefore persists upstream; nothing
in-branch changed and none may.

Deterministic state at `e86ce9b19` re-executed independently (driver logs in
jobs/f628a257.../check-*.log concur): `uv sync --locked --extra dev` ok,
`ruff check .` clean, `ruff format --check .` 2926 files clean, focused
pytest (both files) 139 passed / 0 skipped, `check-suite-inventory.py --suite
packages/maistro-core/tests` ok (13429 node IDs), `mypy` on both changed
modules "Success: no issues found in 2 source files". Acceptance re-read
against source: all six required interfaces conformant, all ten prospective
tests present by exact name; 27 `AdmissionRowDecodeError` raisers — every
parsing-context raiser suppresses its chain (`from None`), the 4 direct
raises (`AdmissionRowHeader.__post_init__`, error `__init__`) have no active
chain to suppress; zero clock reads, zero SQL/HTTP/queue mutation; three-dot
diff vs the develop merge point `30677b185...HEAD` is exactly the ten
declared B2 surfaces.

New this round — the unblock path proven against the NEWEST develop, not
inherited: detached worktree `~/Git/worktrees/probe-1893-round7`, merge
`origin/develop` `30144ad0f` (clean, no conflicts; HEAD already carried
develop's four quality-file edits, verified by diffing the merge tree
against both parents — zero ledger-row loss in either direction), then merge
grant `3235229f5fed` (as if landed on develop), `uv sync --locked --extra
dev`, `RATCHET_BASE_REV=3235229f5fed...`:

- `check-ratchet-provenance.py` exit 0 — both admission identities
  explicitly "authorized" lines, 174 unreachable of 1279 modules, 49
  quality-JSON consumers provenanced, all nine ratchets OK;
- `check-shipped-surface-truth.py` exit 0;
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI's exact argv) exit 0, 1338 = 1338;
- focused pytest at the probe head: 139 passed; ruff clean — the B2 code is
  green on top of the new develop code (no production importer of either
  module arrived upstream; the alembic 055 DDL does not import them).

Worktree left in place as evidence (`26ff3378c` = develop + grant + head).
No `quality/` file was touched in the assigned worktree: the round's
conditional vulture-ledger amendment stays moot (nothing unbanked), and the
reachability grant may only arrive from develop (two-merge rule).

Round-7 conclusion: unchanged from rounds 4-6, now re-proven against
develop `30144ad0f` — the only remaining action is campaign-level (land the
two-entry `reachability` grant on develop, then merge origin/develop here);
no in-branch edit can or may change this. All five driver checks and all
other verified CI steps are green at the assigned head.

## CI-repair round 8 (L1893, head 30af7539b — develop merged; `test:` signal root-caused to the L41 stack sibling)

The round-8 brief named one CI gate failure — `test: failure` — plus the
standing vulture-ledger amendment authorization. Actions taken, in order:

1. **develop sync.** Merged `origin/develop` (`30144ad0f`, re-fetched and
   unchanged this round) into the assigned head `ed320bb2f` — clean, no
   conflicts, merge head `30af7539b`. Quality-ledger survival audited as a
   multiset diff against BOTH parents: zero rows lost in either direction;
   the only divergence is develop's stale informational `_generated_from`
   string ("1053 production modules") which the merge replaces with ours —
   no gate parses that scalar.
2. **`test: failure` root-caused from hosted-CI evidence** (read-only `gh
   run view 37310075429`): the red `test` check in this lane's snapshot is
   PR **#1325** (branch `auto-41`, the L41 integration this leaf stages on),
   job `111763032927`, completed 2026-10-05T12:52:10Z. Failing step 18:
   "Generated API types match the backend's OpenAPI document (#1048)" —
   `git diff --exit-code -- types.gen.ts` after `dump-hive-openapi.py` +
   `gen:api`. Every Python pytest step of that run (steps 7-15, including
   rsi/evolve) passed. Our own PR #1945 head `703543372` shows `test`
   SUCCESS in the same snapshot; its only red is `exact-debt-ledger`. The
   stale generated types live on the sibling branch and are that owner's
   fix under COORDINATION_REQUIRED — not reachable from this worktree.
3. **The whole `test` job reproduced green at the merged head** (first time
   covering its non-Python steps too): bootstrap 232p/6s; maistro-core
   12670p/888s/1xf; server 493p/9s; canvas 464p/75s; turing+backend 300p;
   design 540p/1s; rsi+evolve 2078p/6s; root `tests/` 4519p/107s with
   `RATCHET_BASE_REV=30144ad0f` (merge-group semantics, incl. the five
   `real_repository_ratchet_base` self-check files — 156p); cross-suite
   one-process step 8480p/114s; full 15-suite inventory ok (26493 node
   IDs); `check-test-duplicates.py` ok; hive-conductor frontend `npm ci` /
   `lint` (0 errors) / `build` ok and the #1048 gen:api step **exit 0**
   (types regenerate byte-identical here); canvas frontend ci / `test:ci`
   / lint / build / `npm audit --audit-level=high` (0 vulns) ok. The three
   evolve Docker-sandbox tests that fail with this box's dead mirrored
   `/var/run/docker.sock` pass against the live rootless daemon
   (`DOCKER_HOST=unix:///run/user/1000/docker.sock`): 46/46 in the two
   benchmark files — i.e. environmental, not code.
4. **exact-debt-ledger at the merged head.** `check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
   (CI-exact argv) exit 0, 1338 = 1338 — nothing unbanked, so the round's
   authorized `vulture-baseline.json` amendment is moot again (nothing to
   bank, nothing eliminated). `check-shipped-surface-truth.py` exit 0.
   `check-reachability-provenance.py` and
   `check-reachability-dispositions-provenance.py` each exit 1 — the two
   admission identities are NEW vs trusted base `30144ad0f` and not
   previously authorized — aggregating to `check-ratchet-provenance.py`
   exit 1. develop re-audited by exact module name: 0 occurrences of
   `admission_identity`/`admission_codec` in its ratchet-authorizations,
   reachability-baseline and reachability-dispositions (its 5 substring
   `admission` hits are unrelated, pre-existing identities). Two-merge
   blocker unchanged; round-7's probe `26ff3378c` remains the proven
   unblock.
5. **Static gates.** `ruff check .` clean, `ruff format --check .` 2955
   files clean, `mypy` on both changed modules "Success: no issues found
   in 2 source files", focused pytest 139 passed / 0 skipped.

Round-8 conclusion: every `test`-job behavior is green at this branch's
merged head, including the exact step that is red on the stack sibling; the
only reds are (a) the develop-side reachability grant (two-merge rule —
campaign-level, re-confirmed absent at `30144ad0f`) and (b) the sibling
`auto-41` branch's stale `types.gen.ts`. Neither is reachable from this
worktree; no code, test or `quality/` change is warranted or authorized,
and none was made beyond this note.

## CI-repair round 9 (L1893, head 7e1a1524b — develop 658a8f78c merged;
`test:` signal re-attributed to the sibling; unblock path re-proven)

The round-9 brief re-issued the `test: failure` signal, the standing
BLOCKED block and the vulture-ledger amendment authorization. develop had
advanced `30144ad0f` -> `658a8f78c` (#55 capabilities-as-effect-path, a
large upstream slice: new quota/capabilities modules and tests, quality
ledger updates, a new alembic revision re-parented onto 055). Actions, in
order:

1. **Grant check before judging.** develop `658a8f78c`'s
   `quality/ratchet-authorizations.json` has NO admission entries (its 5
   `admission` substring hits are unrelated pre-existing identities:
   `recover_stranded_chat_admissions`, the a2a transport route, the
   scheduling admitter, the canvas reconcile method); its reachability
   baseline/dispositions carry neither `maistro.runs.admission_identity`
   nor `maistro.tasks.admission_codec`. The two-merge blocker persists
   upstream.
2. **develop sync.** Merged `origin/develop` (`658a8f78c`) into `0b5d4909e`
   — clean, no conflicts, merge `7e1a1524b`. Ledger survival audited as a
   multiset diff against BOTH parents: reachability 170 (develop) + our 2
   admission rows = 172, develop losing zero rows; the merge correctly took
   develop's intentional removal of `maistro.events.publisher`/
   `maistro.events.wiring` (now reachable upstream). Vulture 1338 (ours) +
   develop's 5 new rows = 1343, zero rows lost in either direction.
   Dispositions likewise. Neither new module nor either test file changed
   in the merge (empty diff vs `0b5d4909e`).
3. **`test:` signal re-attributed from hosted evidence** (read-only `gh`):
   our PR #1945's `test` check is SUCCESS at its head `7035433722` — every
   production change on this branch since that head is docs + quality
   ledgers + develop syncs (the codec refactor `7a0669c7c` predates it). The
   red `test`/`integration-scope`/`workflow-lint` in the snapshot belong to
   sibling PR #1325 (branch `auto-41`, head `3c352e161448`) — that owner's
   fix under COORDINATION_REQUIRED, unreachable from this worktree. develop
   `658a8f78c` touches nothing under maistro-server/hive-conductor/canvas
   or any frontend, so the #1048 gen:api step (proved byte-identical here in
   round 8) is unaffected.
4. **Test-job Python steps re-run at the merged head** (CI's forms):
   focused both-files pytest -> 139 passed / 0 skipped; root
   `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop
   uv run pytest tests/ --ignore=tests/tools/registry` -> 4519 passed,
   107 skipped (includes develop's re-parented migration-stamp assertion);
   full `packages/maistro-core/tests` -> 12862 passed, 927 skipped,
   1 xfailed (grew by develop's new quota/capability suites; skips are
   PG/DSN-gated, not counted as proof); `check-suite-inventory.py --suite
   packages/maistro-core/tests` -> ok, 13790 node IDs.
5. **Static + quality gates at the merged head.** `ruff check .` clean,
   `ruff format --check .` 2975 files clean, `mypy` on both changed modules
   "Success: no issues found in 2 source files"; vulture at CI's exact
   argv -> exit 0, 1343 reviewed -> 1343 banked (**nothing unbanked, so the
   round's authorized `vulture-baseline.json` amendment is moot again —
   nothing to bank, nothing eliminated**); `check-shipped-surface-truth.py`
   exit 0; radon 138 -> 138 exit 0 (develop retired 5 baselined blocks);
   `check-reachability.py` exit 0 (1285 production modules, 172 unreachable,
   baseline matches the tree); `check-reachability-dispositions.py` exit 0
   (50 groups: 150 CONNECT, 20 LIBRARY, 2 RETIRE); `check-convergence-matrix.py`
   OK (52 subsystems, 172 attributed). The `_generated_from` "1266" string
   is stale-informational as before (no gate parses it; round-6 finding,
   drifts with every develop sync by construction).
6. **exact-debt-ledger at the merged head.** `RATCHET_BASE_REV=origin/develop
   check-ratchet-provenance.py` -> exit 1 on exactly the two reachability
   provenance gates (NEW unreachable `maistro.runs.admission_identity` +
   `maistro.tasks.admission_codec`, NEW dispositions; base `658a8f78c`).
   Every other sub-ratchet OK. Notably develop's #55 slice landed ITS OWN
   reachability grants upstream — the same landing mechanics this lane's
   probe uses.
7. **Unblock path re-proven at THIS head, not inherited** (detached
   worktree `~/Git/worktrees/probe-1893-round9`, probe merge `300718b20` =
   `7e1a1524b` + grant `3235229f5fed`, clean, +10 lines of grants only):
   `RATCHET_BASE_REV=3235229f5fed...` -> aggregator **exit 0**, both
   admission identities on explicit `authorized:` lines, "172 unreachable
   module(s), no candidate-approved expansion", all 10 sub-ratchets OK;
   `check-shipped-surface-truth.py` and CI-exact vulture (1343 = 1343) both
   exit 0 under the same base; focused pytest at the probe head -> 66
   passed. The grant payload and landing order remain proven end-to-end:
   campaign lands `3235229f5fed` (or equivalent two-entry reachability
   grant) on develop, this branch syncs it, exact-debt-ledger goes green
   with zero further change here.
8. **Acceptance spot re-checks at the merged head:** all 10 prospective
   tests present by exact name; zero clock reads in either module (the two
   `time`/`now` grep hits are docstring prose); legacy `completed_at`
   referenced only in docstrings stating it is deliberately not read; no
   SQL/HTTP/router tokens in the codec.

Round-9 conclusion: unchanged from rounds 4-8, now at develop `658a8f78c`:
all in-branch behavior and gates are green at the merged head; the only
reds are (a) the develop-side reachability grant (two-merge rule,
campaign-level, unblock path re-proven at this exact head via probe
`300718b20`) and (b) the sibling `auto-41` branch's failing checks. No code,
test or `quality/` change was warranted beyond the develop sync and this
note.

**Mid-round develop advance (final head `e96cd6b27`).** While this round
ran, develop advanced again `658a8f78c` -> `159fbafe9` (M6 cleanup #1980:
git-MCP transport hardening, builders TUI, RSI tests, one vulture row
retired). It was merged too (clean, no conflicts). Multiset audit:
vulture 1342 (develop's retirement of the `code_registry/types.py` unused
`trusted` row correctly taken — we never touched that row; no develop row
lost), reachability 170 + our 2 = 172 unchanged, dispositions unchanged.
Re-run at `e96cd6b27`: `ruff check .` clean, `ruff format --check .` 2976
files clean, CI-exact vulture -> exit 0 (1342 = 1342, still nothing
unbanked — amendment stays moot), `check-reachability.py` exit 0 (1285
modules / 172 unreachable), dispositions + convergence + shipped-surface
exit 0, focused pytest -> 139 passed / 0 skipped, suite inventory ok for
both maistro-core and maistro-rsi (develop's new #452 tests recorded
upstream). The grant probe was refreshed at this exact final head
(`9f10db267` = `e96cd6b27` + `3235229f5fed`, worktree
`probe-1893-round9b`): `RATCHET_BASE_REV=3235229f5fed...` aggregator exit 0
(all 10 sub-ratchets OK, both admission identities authorized),
shipped-surface and vulture exit 0 under the same base. Develop still
carries no admission grant at `159fbafe9`; the campaign landing action is
unchanged.

## Round 10 (repair, exact head `1a411d8da5e2`)

Driver checks at this head: sync/ruff/format green, focused pytest
139 passed (66 codec + 73 identity), suite inventory ok. Independently
re-run this round: `uv run pytest
packages/maistro-core/tests/tasks/test_admission_codec.py -q` -> 66 passed;
both changed files -> 139 passed; `ruff check .` and
`ruff format --check .` clean; `uv run mypy` on both changed modules -> no
issues.

CI-exact exact-debt-ledger steps at this head vs trusted base
`b672b799aba6` (`origin/develop`):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` -> exit 0, 1342 reviewed identities = 1342 findings,
  `unclassified: 0`. Nothing unbanked, so the lane brief's conditional
  ledger amendment is vacuous — no vulture row added, removed or edited
  (file byte-identical to develop, verified by row comparison).
- `check-shipped-surface-truth.py` -> exit 0.
- `check-ratchet-provenance.py` -> exit 1, exactly the two-merge finding:
  reachability 170 -> 172 and dispositions 170 -> 172, with
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec` NEW
  and "not covered by an already-landed reachability authorization". This is
  structural, not a banking defect: `ratchet_provenance.load_authorizations`
  reads grants from `merge-base(base, HEAD)`, and the grant (`3235229f5fed`)
  is not an ancestor of any worker branch until it lands on develop.

Grant-landing probe independently executed THIS round (previously
claimed-only): worktree `probe-1893-round10` at `50f9f4558` =
`1a411d8da5e2` + merge `3235229f5fed` (clean, grant rows only),
`uv sync --locked --extra dev`, then `RATCHET_BASE_REV=3235229f5fed...`:
aggregator exit 0 — all 10 sub-ratchets OK, reachability "172 -> 172, no
candidate-approved expansion", dispositions "172 -> 172, new debt uses
prior reachability authorization" — plus shipped-surface exit 0 and CI-exact
vulture exit 0 under the same base. The unblock path is therefore proven at
the exact final head: once develop carries the grant and this branch
syncs it, the exact-debt-ledger job passes unchanged content.

Multiset audit vs `origin/develop` (`git diff --numstat origin/develop --
quality/`): `vulture-baseline.json` untouched (0 rows changed);
`reachability-baseline.json` +2/-1 (the two module rows and the
informational `_generated_from` count, which remains stale-informational at
1266 vs 1285 measured — gates do not read it); `reachability-dispositions.json`
+11 (`runs-root-admission-contracts`, 2 modules, CONNECT). No ledger row
was lost in any merge.

Residual: the merge-queue `exact-debt-ledger` job stays red until the
campaign lands the grant on develop and this branch syncs it; no in-branch
action can or may substitute (issue text forbids gate modifications to
green an unwired slice, and the provenance gate is designed to refuse
self-authorization). All leaf acceptance criteria — interfaces, fail-closed
codes, error hygiene, header/record separation, the ten prospective tests,
inventory note, ruff/format/mypy, banking gates — are proven at this head.

## Round 11 (independent verifier re-validation, exact head `2176016b9232`)

Every round-10 claim re-derived independently at the final head (the
round-10 note commit on top of `1a411d8da5e2`; code and ledgers identical,
diff is this note file only). Locally re-executed: focused pytest both files
139 passed / 0 skipped (codec file alone 66); `ruff check .` and
`ruff format --check .` clean; `mypy` on both changed modules clean; CI-exact
vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'` ->
exit 0, 1342 = 1342; `check-shipped-surface-truth.py`,
`check-reachability.py` (1285 modules / 172 unreachable),
`check-reachability-dispositions.py`, `check-convergence-matrix.py`,
`check-radon-baseline.py` (138 -> 138), `check-test-duplicates.py`,
`verify-monorepo-layout.sh`, `check-suite-inventory.py --suite
packages/maistro-core/tests` -> all exit 0; baseline-pinning root tests
`tests/test_check_reachability.py tests/test_reachability_baseline_identity.py`
-> 38 passed. Mutation control (in-memory, no tree edit): loosening
`_coerce_format_version` to accept `True`/`1.0` makes
`test_unknown_format_cannot_be_reinterpreted_as_legacy` fail with
"DID NOT RAISE" — the parametrization discriminates the regression it names.

`check-ratchet-provenance.py` at this head (trusted base `b672b799aba6` ==
`origin/develop` tip, re-fetched and unchanged; the branch is fully synced,
the 10-surface diff is the entire delta): exit 1 on exactly the two
reachability provenance gates (`maistro.runs.admission_identity`,
`maistro.tasks.admission_codec` NEW unreachable / NEW dispositions), all
other sub-ratchets OK. The round-10 grant probe was independently re-executed
in the persistent worktree `probe-1893-round10` (`50f9f4558` =
`1a411d8da5e2` + merge `3235229f5fed`, grant rows only):
`RATCHET_BASE_REV=3235229f5fed...` -> aggregator exit 0, both admission
identities on explicit `authorized:` lines, "no candidate-approved
expansion", 49 quality-JSON consumers provenanced. Verifier-tooling footgun
recorded: piping this aggregator through `head` makes the truncated writer
die with `BrokenPipeError` and report exit 1 — redirect to a file before
judging. Multiset audit re-run: vulture byte-identical to develop;
reachability +3/-1 lines (2 module rows + the stale-informational
`_generated_from` "1266" vs 1285 measured — no gate parses it); dispositions
+11. Hosted status at `2176016b9232` (read-only refresh during review):
`exact-debt-ledger` FAILURE (the residual above), `test` and the remaining
checks still QUEUED — hosted green stays UNVERIFIED pending the run;
every locally equivalent step is green here. Acceptance re-read against
source: all six interfaces, six codes, fail-closed paths, error hygiene
(`__suppress_context__` + no token/snapshot bytes in messages), the ten
prospective tests by exact name, no clock/SQL/HTTP/queue code, legacy
`completed_at` unread — all confirmed. Handoff unchanged: land the grant on
develop, sync, and the exact-debt-ledger job passes with zero content change.

## Round 12 (CI-repair validation, exact head `a24eca85fc18`)

The current lane brief again requested the CI-exact vulture check before any
ledger amendment. Independently executed:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> exit 0: 1342 reviewed
  identities, 1342 findings, `unclassified: 0`, and `never_allowlist: 0`.

There is therefore no unbanked or eliminated vulture identity to amend in
`quality/vulture-baseline.json`; changing that ledger would be fabricated
rather than a repair.

At this same head, `uv run pytest packages/maistro-core/tests/tasks/
test_admission_codec.py packages/maistro-core/tests/runs/
test_root_admission_identity.py -q -x` -> 139 passed; `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run mypy
packages/maistro-core/src/maistro/tasks/admission_codec.py
packages/maistro-core/src/maistro/runs/admission_identity.py` were clean.
`check-suite-inventory.py --suite packages/maistro-core/tests` matched 13865
node IDs; reachability, reachability dispositions, convergence, and
shipped-surface checks all passed (1285 production modules, 172 unreachable
with dispositions).

`RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` still exits 1 solely because the trusted
base `b672b799aba6` lacks already-landed authorization for the two intentionally
unwired modules `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` and their dispositions. All other sub-ratchets
passed. This is the existing two-merge campaign blocker, not a vulture-ledger
defect; it remains unfixable by an in-branch amendment.

## Round 13 (real-pool durability repair)

The prior independent verifier correctly found that the prospective
`test_raw_and_production_pool_codecs_read_identical_text_snapshots` only
aliased an in-memory string; it did not prove the migrated SQL TEXT column or
the two asyncpg pool configurations. It is now an async PostgreSQL test that:

- requires both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` (and
  fails under `MAISTRO_REQUIRE_PG_LEGS=1` if either is absent);
- uses the production-codec `pg_pool` plus an independently-created raw pool,
  proves both point at the same server/database, writes an encoded v2 record
  to the migrated `task_idempotency` table, reads it through both pools, and
  decodes both mappings; and
- cleans up its uniquely-scoped SQL row in `finally`.

The local repair environment has neither required DSN and its Docker socket is
unavailable, so the live leg is intentionally reported as unverified here
until the disposable migrated database is supplied. The focused suite still
runs its unit contracts; it does not claim a skipped leg as durability proof.

## Round 14 (direct-header scalar-type repair)

A verifier reproduced that a caller could construct an `AdmissionRowHeader`
with `format_version=1.0`: Python compares that float equal to `1`, so the
dataclass equality check accepted it against an integer-decoded row header and
wrongly selected the legacy path. `AdmissionRowHeader.__post_init__` now
requires a non-boolean `int` before accepting values 1 or 2. The existing
`test_unknown_format_cannot_be_reinterpreted_as_legacy` parametrization now
also passes each invalid raw value (`3`, `True`, and `1.0`) to the public
header constructor; this preserves the suite inventory because it adds cases
to an existing collected test node rather than a test file/node.

On the local repair worktree rooted at `f4b5f01b6c`: `uv run pytest
packages/maistro-core/tests/tasks/test_admission_codec.py
packages/maistro-core/tests/runs/test_root_admission_identity.py -q -x` ->
142 passed, 1 PostgreSQL durability test skipped (DSNs unset); `ruff check`,
`ruff format --check`, targeted mypy, CI-exact vulture, and the core suite
inventory (`14070` nodes) pass. The trusted-base exact-debt-ledger remains
red only on the already-recorded, in-branch-unfixable reachability grants.

## Round 15 (current CI-repair revalidation, exact head `48ed2ed6b1d9`)

The lane's required CI-repair command was re-executed before considering a
vulture-ledger amendment:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> exit 0; 1336 reviewed
  identities equal 1336 findings, with `unclassified: 0` and
  `never_allowlist: 0`.

There is no actual vulture debt to bank or eliminate, so
`quality/vulture-baseline.json` remains untouched. Revalidation at this exact
head: focused codec test -> 69 passed, 1 skipped (the DSN-gated real-pool
leg); both admission suites -> 142 passed, 1 skipped; `ruff check .`,
`ruff format --check .`, targeted mypy, `check-reachability.py`,
`check-reachability-dispositions.py`, and core suite inventory (14070 nodes)
all pass. The real asyncpg two-pool test remains explicitly **UNVERIFIED**:
this worktree has no `MAISTRO_TEST_PG_DSN` or `MAISTRO_TEST_DATABASE_URL`, so
its skip is not durability evidence.

`RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` exits 1 only for the two known
reachability/disposition provenance entries: `maistro.runs.admission_identity`
and `maistro.tasks.admission_codec` are absent from the trusted merge base
`56332162cf63` and have no already-landed authorization. All other ratchets
pass. This branch cannot self-authorize the intentional unwired modules; the
remaining campaign action is still to land the prepared reachability grant on
develop and merge that base here.

## Round 16 (develop sync + real-database durability executed, head `658aba47c604`)

`origin/develop` moved to `3b8e090fe531` (M9-J1 extension catalog), so the
47/1 divergence was resolved by merging `origin/develop` into `auto-1893`
(automatic merge, no conflicts). Quality-ledger row counts were diffed after
the merge per the multiset hazard: `ratchet-authorizations.json` 318 grant
rows on both sides, vulture rules 15 on both sides, develop's tip touched no
quality ledgers, and the branch's 2 banked reachability rows + 11 disposition
rows survive intact.

The previously UNVERIFIED real-database legs were executed on a disposable
pgvector/pg17 container (`m1893-pg`, removed after the run):

- `DATABASE_URL=... uv run alembic upgrade head` applied the full chain,
  including `054 -> 055 Forward admission-generation representation on
  task_idempotency (#1892)`.
- Both admission suites with `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` on the same migrated DB: **143 passed, 0
  skipped** (the raw-vs-production two-pool durability test ran for real),
  and re-run under `MAISTRO_REQUIRE_PG_LEGS=1` the durability test alone
  reports PASSED (missing DSNs would fail, not skip).
- Destructive migration evidence on a second disposable database in the same
  server: `tests/migrations/test_migration_chain.py` plus
  `tests/migrations/test_task_admission_generation_upgrade.py` -> **27
  passed**, including the downgrade-refusal and legacy-only downgrade/upgrade
  round-trip cases.
- `tests/test_check_reachability.py` + `tests/test_reachability_baseline_identity.py`
  -> 38 passed at the merged head.

Post-merge revalidation: `ruff check .` and `ruff format --check .` clean;
suite inventory 16/16 suites match (maistro-core/tests 14466 collected, the
+14 coming from develop's own catalog suites with their shipped notes);
CI-exact vulture exit 0 at 1332 identities = 1332 findings (`unclassified: 0`,
`never_allowlist: 0`) against merge base `3b8e090fe531`; shipped-surface truth
complete; `RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` is
now 10 of 12 ratchets OK with the merge base moved to develop's tip, failing
only on the same two admission entries. Read-only probe of grant
`3235229f5fed` confirms its `ratchet-authorizations.json` carries exactly the
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
reachability grants (owner, issue #1893, CONNECT group
`runs-root-admission-contracts`); the gate reads authorizations from
`merge-base(RATCHET_BASE_REV, HEAD)`, so the grant must land on develop
before a develop merge here can authorize them. No ledger, grant, or gate
file was modified in this branch.

---
inventory-delta:
  packages/maistro-core/tests: +0
---
# Issue #1893 repair round at 29e3be4 (revert of broken reachability hack)

Snapshot: branch `auto-1893`, dispatch head `29e3be4ab07cf11a126633b2548bf5afbeaf698b`,
develop base `ab8b3737fa64f8d840f421ef87ca506c509444ff`. Clean worktree at
start; only issue #1893 is processed. No tests were added or removed; the
`inventory-delta` is zero (`scripts/check-suite-inventory.py`: 17 suites match,
0 duplicate/byte-identical groups).

## Named validation failure — root cause and repair

Driver check `uv run ruff check .` failed at 29e3be4 with 6 findings, all in
`packages/maistro-core/src/maistro/tasks/idempotency.py`: I001 (un-sorted
import block) plus F401 x5 for the `maistro.tasks.admission_codec` import
(`AdmissionRecordV2`, `LegacyAdmissionRecord`, `AdmissionRowDecodeError`,
`decode_admission_header`, `decode_admission_record`).

Root cause: commit 29e3be4 ("Make admission codec and identity reachable by
using them in pg_admission") added a production import of
`maistro.tasks.admission_codec` into `idempotency.py` but never used it, and
rewrote `_row_of`'s signature/docstring to claim codec decoding ("return None
if the row cannot be decoded") while leaving the body byte-identical to the
old positional `AdmissionRecord(...)` construction — the commit message's
central claim is not in its diff. Beyond the lint failure this:

- contradicted the module's own landed disposition, which states B2's scope
  "forbids any production import ... until the C leaf lands its consumer"
  (`quality/reachability-dispositions.json:609`, grant rationale at
  `quality/ratchet-authorizations.json:66-75`);
- broke `scripts/check-reachability.py` at this head: it reported "2 module(s)
  newly REACHABLE — drop them from the baseline" for exactly
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  (baseline rows `quality/reachability-baseline.json:131,147`), i.e. the
  baseline would have had to shrink in the same change;
- introduced a return annotation `AdmissionRecord | None` on `_row_of` whose
  None arm is unreachable, inviting callers to depend on behavior that does
  not exist.

Repair: reverted both hunks of 29e3be4 in `idempotency.py` — import block
removed, `_row_of` restored to its original signature and docstring
(`git diff 29e3be4^ -- <file>` is now empty). `admission_codec.py` itself is
untouched; it remains the inactive contract leaf its grant describes, with no
production importer (verified: only `packages/maistro-core/src/maistro/tasks/admission_codec.py`
mentions the module under `packages/*/src`).

## Gates re-run at the repaired tree

1. `uv run ruff check .` → **All checks passed!**
2. `uv run ruff format --check .` → 3301 files already formatted.
3. `uv run python scripts/check-reachability.py` → exit 0: "1403 production
   modules, 171 unreachable from any entry point"; the two admission modules
   are back to unreachable, matching the baseline rows.
4. `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` → exit 0: 1322 reviewed
   identities == 1322 findings, `unclassified: 0`, `never_allowlist: 0`.
   Raw `uv run vulture` confirms the removed imports were never vulture
   identities, so no `quality/vulture-baseline.json` amendment is applicable.
5. `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
   packages/maistro-core/tests/tasks/test_idempotency.py -q` → 195 passed,
   3 skipped (the 3 skips are the PG-DSN-gated legs).
6. `uv run pytest packages/maistro-core/tests/tasks -q` → 627 passed,
   20 skipped.
7. `uv run mypy packages/maistro-core/src` → after `uv sync --all-extras`
   (the driver's `--extra dev` sync omits maistro-bootstrap): **Success: no
   issues found in 791 source files.** Under the dev-only venv mypy reports 5
   pre-existing `import-not-found` errors for `maistro_bootstrap.*` in
   `cli/_install.py` and `cli/_builders_tui.py` — files this round did not
   touch; environmental, resolved by the all-extras sync as recorded in the
   091383496 round note.
8. `uv run python scripts/check-suite-inventory.py` → ok: 17 suites match the
   recorded inventory; 0 duplicate evidence groups.

## B2 acceptance surface re-checked (unchanged by this round)

- `packages/maistro-core/src/maistro/tasks/admission_codec.py` (662 lines)
  exports exactly the issue's interfaces: `AdmissionDecodeCode(StrEnum)`,
  `AdmissionRowDecodeError(ValueError)` with `code`/`scope_key`,
  frozen `AdmissionRowHeader`, `decode_admission_header`,
  `decode_admission_record`, `encode_admission_record`.
- All 10 prospective test names from the issue body exist in
  `packages/maistro-core/tests/tasks/test_admission_codec.py` (40 tests in
  the file); the focused file passes (included in the 195/627 above).

## Residual (unchanged, develop-side)

The two-merge wall documented at e655ec85 is untouched by this round:
`RATCHET_BASE_REV=origin/develop` provenance still cannot see this branch's
reachability grant because `load_authorizations` reads the merge base and the
grant rows (`quality/ratchet-authorizations.json`, baseline rows, CONNECT
disposition group `runs-root-admission-contracts`) exist only here. Landing
them on origin/develop first remains an owner/integration action outside
worker authority; this repair removes the branch-side violation that would
have made the wall moot by breaking the reachability gate outright.

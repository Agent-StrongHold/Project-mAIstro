---
inventory-delta:
  packages/maistro-core/tests: 0
---

# auto-966 — salvage finiteness guard, sync to origin/develop d99e598e1, revalidate

Round starting at exact head `dc1480df6c37` (develop base at capture
`d99e598e1084`). Three things happened, in this order:

## 1. The prior session's uncommitted work was validated and committed

The worktree carried two modified files: `_require_finite_number` in
`extensions/packs.py` plus matching rejection tests. Verified the guard is
load-bearing, not cosmetic: `json.loads("1e400") → inf`, and the canonical
`RubricDimension` accepts `weight=inf` (`gt=0` is an ordering constraint
infinities satisfy) — proven by direct construction against the canonical
model. One `ruff format` nit from the prior session's final write was
applied (same condition collapsed to one line), and the work was committed
as `66287bc00`.

## 2. Guard hardening: the bool arm is now exercised

No test exercised `isinstance(value, bool)` — JSON `true` is a bool that
`isinstance(True, int)` admits, so that rejection arm was unproven. Added a
`gate_pass_threshold: True` rejection case *inside the existing test node*
(`test_manifest_inspection.py` rejection battery), so the suite count is
unchanged. Coverage re-measured over the two extensions suites: every line
and branch arc of the changed hunks is now hit; packs.py stands at 99%
lines with only pre-existing misses (953, 1236, 1443->1436, 1470) outside
the changed regions.

## 3. The develop sync was completed

`origin/develop` had advanced 2 commits past the previously merged
`82097f6b7acc`, tip `d99e598e1084` (M8-E1/M8-E3 research harnesses, #2078,
#2081). Merged cleanly as `dda6316ce` — **zero conflicts**; branch is 0
behind. Post-merge ledger hygiene: `git diff --numstat origin/develop --
quality/` shows exactly one row, additive only —
`quality/ac-state-notes/auto-966.json` (+17/0, this lane's AC note). No
`quality/*.json` ledger lost rows in the merge.

## Revalidation battery (all at dda6316ce)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass
  (3204 files).
- `uv run pytest packages/maistro-core/tests/extensions/` — 1010 passed,
  2 failed: the environmental CLI 80-column wrap tests
  (`test_cli_certification.py::test_certify_refuses_a_malformed_signing_key`,
  `test_cli_compat.py::test_compat_preflight_rejects_unreadable_input`),
  byte-identical to `origin/develop` and unchanged by this lane; reproduced
  the documented geometry dependence (`--basetemp=/tmp/pt` moves the failure
  to a different assertion because the tmp-path length shifts the wrap
  point, inserting `\n` inside the asserted prose substring).
- Focused: `test_pack_contracts.py` + `test_manifest_inspection.py` +
  `test_lifecycle_proof.py` — 185 passed.
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  — ok, 1 suite matches the recorded inventory (count unchanged: the bool
  case extended an existing node).
- Radon ratchet — 137/137 blocks, 0 new, 0 regressed, base `d99e598e1084`.
- Vulture ledger, CI-exact args (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) — 1323 → 1323, no new identities.
- `uv run mypy packages/maistro-core/src` after
  `uv sync --locked --all-extras` (CI's env; the earlier 5
  `maistro_bootstrap` import-not-found errors were the missing bootstrap
  extra, not code) — clean, 772 files.
- `check-doc-links.py` — pass.
- Diff coverage of the changed hunks — proven directly (see §2); the
  publish-set aggregate floor is producer-combined and was green in CI on
  the identical surface at `dc1480df6` (all check-runs success, including
  "Quality gate (Pillars 1–4, 7, 8)" and "Coverage gate").

No suite-count delta from this round; `inventory-delta: 0` above records
that the bool rejection case lives inside an existing test node.

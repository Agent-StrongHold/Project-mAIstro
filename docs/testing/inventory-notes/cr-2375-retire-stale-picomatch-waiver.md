---
inventory-delta:
  tests/: +2
---

# CR-2375 — retire the stale picomatch waiver from the npm audit gate

## Why (the actual CI evidence)

The `test` job (ci.yml run 44355086265, job 134980905857, head 37736539e3)
failed at its final step — `python scripts/npm_audit_gate.py /tmp/npm-audit.json`
— with `npm audit waivers are stale — the advisories are no longer reported:
GHSA-fc5q-39xc-vjpf`. Every pytest leg in the same job had already passed
(659 + 225 + 138 + 662 + 273 + 147 passed; the root `tests/` leg ran to
completion), and the "Event loop is closed" lines in the log are
`PytestUnhandledThreadExceptionWarning` annotations from an aiosqlite worker
thread, not failures.

Develop-borne drift, not branch-borne: develop's own ci.yml runs at
6a1ef1c79 (17:13) and f6f4250737 (17:28) fail at the same step, while
ac4a7667ba (16:39 — this branch's merge base) was green. Sometime between
16:39 and 17:09 UTC on 2026-11-18 npm's advisory database stopped reporting
GHSA-fc5q-39xc-vjpf.

Reproduced locally at the branch head (2026-11-18):

- `npm audit --json` in `packages/maistro-canvas/frontend`:
  `metadata.vulnerabilities.total = 0` — zero advisories on the identical
  committed lock, which still pins `picomatch 4.0.7` (the exact version the
  advisory's range `<=4.0.7` covers, and still the newest release). The
  advisory became unreported without upstream shipping a fix; the waiver
  therefore cannot be refreshed, only retired — which is exactly what the
  gate's two-way ratchet demands ("delete it from ALLOWED").
- `uv run python scripts/npm_audit_gate.py /tmp/npm-audit.json` with the
  pre-edit gate: exit 1, stale waiver — matches CI byte for byte.

## Behavior change

- `scripts/npm_audit_gate.py`: the `GHSA-fc5q-39xc-vjpf` entry is deleted
  from `ALLOWED` (empty again); waiver-ledger history moved to the module
  docstring; the allowlist-extension hint no longer cites the retired waiver
  as its worked example. Nothing else about the verdict changes.
- `.github/workflows/ci.yml`: the comment above the canvas audit steps now
  records the retirement instead of asserting the waiver is live.

## Test delta

- `tests/test_npm_audit_gate.py` (+2, same file, 12 → 14):
  - `test_a_fully_clean_report_passes` (new): the post-retirement production
    shape — zero advisories, empty allowlist — exits 0 and prints the OK
    verdict. No existing test covered the clean-report branch.
  - `test_the_retired_picomatch_waiver_is_gone_from_the_production_allowlist`
    (new): regression pin — fails before the fix (waiver present), passes
    after; re-adding the waiver without an actively reported advisory
    re-breaks CI the same way.
  - Reworked in place (no count change): the three tests that previously
    depended on the production `ALLOWED` containing the picomatch waiver now
    inject their waivers explicitly (`test_a_triaged_waiver_passes_the_real_
    cascade`, `test_a_new_advisory_on_the_same_chain_is_not_covered_by_the_
    waiver` — which additionally asserts the waived ID still prints as
    allowed while the new ID blocks — and `test_a_waiver_whose_advisory_
    stopped_being_reported_is_stale`, now exercising the staleness path with
    its own injected stale waiver instead of piggybacking on the production
    entry). Pure unit tests over canned JSON — no npm invocation, no network.

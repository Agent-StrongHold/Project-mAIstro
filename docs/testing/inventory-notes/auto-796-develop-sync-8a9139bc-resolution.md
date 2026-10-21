---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-796-develop-sync-8a9139bc-resolution

Repair round for #796 ([M7-A7] Map Evolve/RSI as consumers of the same eval; forbid a
second loop). The round synced `origin/develop`'s tip (`8a9139bc5`) into `auto-796` and
re-validated the M7-A7 contract on the merged head. **No test was added or removed by
this branch** — the develop advance is a dependency-only supply-chain unblock
(`packages/maistro-core/tests` keeps the `+7` recorded in `m7-a7-eval-consumer-map.md`,
unchanged here), so the suite count is unchanged.

## Why the sync was the fix

`8a9139bc5` — `fix(deps): trunk CI unblock — certifi 2026.10.19, pillow 13.0.0, npm
audit fix (launch-editor)` — is develop's pip-audit-driven trunk unblock:

- `certifi 2026.4.22 -> 2026.10.19` (GHSA-6q48-6c7w-9gw2);
- `pillow >=12.3.0,<13 -> >=13.0.0,<14` (9 CVEs fixed; canvas tests still 465 passed
  against pillow 13);
- canvas `package-lock.json` npm audit fix (`launch-editor`).

Three files, all dependency manifest/lock state (`uv.lock`,
`packages/maistro-canvas/pyproject.toml`,
`packages/maistro-canvas/frontend/package-lock.json`); no production source or test
code. Syncing brings those supply-chain fixes onto the branch so the supply-chain gate
is green against the current advisory set rather than against develop's older lock.

## The merge

`a57dca433` — `Merge commit '8a9139bc5fc19f0d35ee28036a201dc8f721d28c' into
auto-796'`. Conflict-free; nothing was hand-edited. The branch's delta against
`develop` is still the issue surfaces only, and the merge introduced **no**
production-code or ledger delta:

```
$ git diff --numstat origin/develop...HEAD -- 'packages/*/src' quality/    # empty
$ git diff --numstat 1226a5a86 HEAD -- docs/testing/inventory             # empty
$ git merge-base --is-ancestor origin/develop HEAD && echo synced         # synced
```

The inventory ledger (`docs/testing/inventory/baseline.json` + every note) is
byte-identical to `origin/develop`; this branch's only inventory delta remains the `+7`
contract tests in `m7-a7-eval-consumer-map.md` (already recorded in earlier rounds).

## Suite inventory

```
$ uv run python scripts/check-suite-inventory.py
ok: 21 suite(s) match the recorded inventory
Unique-evidence report (21 suite(s) collected):
  collected node IDs: 32470
  unique test identities (cross-suite): 32470
  duplicate evidence from copied test files: 0
  byte-identical test files: 0 group(s), 0 redundant file(s), 0 redundant bytes
```

Per the gate's own docstring the node-ID / unique-evidence block is **report-only**
("the node IDs feed #396's unique-evidence report and gate nothing"); the authoritative
check is the per-suite count and all 21 are `ok` against the unchanged ledger. The
develop advance is dependency-only, so it moved no count.

## Exact-debt-ledger re-verified (base = develop `8a9139bc5`)

- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  → exit 0 — `0 accepted lifecycle violation(s) -> 0 current lifecycle violation(s)`,
  `OK: 0 lifecycle violation(s), no candidate-approved expansion`, `OK: 53 quality
  JSON consumer(s) have explicit provenance` (`base 8a9139bc5fc1 / candidate a57dca433825`).
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py`
  → exit 0 — `Shipped-surface truth matrix is complete.`
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments) → exit 0 —
  `1326 reviewed identities -> 1326 findings` (no ledger amendment).
- `uv run python scripts/check-reachability.py` → exit 0 — `1420 production modules,
  168 unreachable` (unchanged since round 6).
- `uv run python scripts/check-convergence-matrix.py` → exit 0 — 52 subsystems /
  1420 modules, 168 unreachable attributed.

No ledger row was added, removed or re-banked: `quality/` is byte-identical to
`origin/develop`.

## Supply chain (pip-audit)

```
$ uv pip freeze --exclude-editable > deps.txt
$ pip-audit --strict --format=json -r deps.txt -o pip-audit.json || true
$ uv run python scripts/pip_audit_gate.py pip-audit.json
allowed: ecdsa==0.19.2 PYSEC-2026-1325
pip-audit OK (1 known, all triaged in ALLOWED)
direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions
```

The only advisory in the graph is `ecdsa==0.19.2` / `PYSEC-2026-1325` (Minerva P-256
timing side channel; upstream states side-channel attacks are out of scope with no
planned fix). The pair is allowlisted in `scripts/pip_audit_gate.py:ALLOWED` with
rationale that `maistro.identity` derives on Ed25519/secp256k1 only and never touches
P-256, so the advisory is not reachable as used. The `certifi`/`pillow` advisories that
develop's `8a9139bc5` bump fixes are gone with the sync.

## Clean tree

`git status --porcelain` is empty for tracked files — no `ac-state.json` or other
local-only artifact was generated this round (`tests/test_branch_independence_repository.py`
passes as-is), so there is nothing to move aside.

## Residuals

- Acceptance criterion "PR is `feat/m7-a7-eval-consumer-map` off `develop`" is
  dispatcher-owned GitHub state; lane workers may not push or open PRs, so it is
  unverifiable locally by construction. The branch *is* off `develop`
  (`git merge-base --is-ancestor origin/develop HEAD` → true; the only branch commit
  ahead of `origin/develop` is the sync merge `a57dca433` itself).
- The coverage publish-set floor (87%) and diff-coverage thresholds need CI's coverage
  producers' artefacts (not run locally). The diff-coverage half is vacuous for this
  branch — `packages/*/src` is untouched — and the supply-chain fixes are verified by
  the pip-audit gate above.
- `pip-audit` was run locally against the installed environment (`--extra dev`), a
  subset of CI's `--all-extras` install; the allowlisted advisory is the only one in
  the graph here, but a CVE restricted to an extra-only dependency would not be visible
  locally.

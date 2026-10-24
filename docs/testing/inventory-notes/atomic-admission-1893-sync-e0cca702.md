---
inventory-delta:
  packages/maistro-core/tests: +0
---
# atomic-admission-1893 — develop sync to e0cca7024, round-4 exact-debt-ledger re-validation

Round: repair lane L1893, job 0aaaf7b122134308a4f7162123cab536, branch auto-1893.
Prior head `1a6077543336` (round 3), develop base `e0cca7024ef7`.

## What moved

`origin/develop` advanced from the previously synced `35a72ff54` to `e0cca7024`
(3 commits: #2180 operator YAML pre-Container load, #2204 consistency-evaluator
complexity refactor, #2165 sandbox writable-host-path constraints). Merged
`refs/remotes/origin/develop` into auto-1893 as merge `aa4fc2abac4a`,
conflict-free.

## Ledger integrity after the merge

Per the quality-merge hazard, quality/ rows were diffed before/after:

- The deletions the merge diffstat shows against our prior head are develop's
  own reviewed hygiene, not row loss: #2204 removed the three
  `maistro-design/consistency.py` radon rows **and their grants together**,
  exactly as those rows' rationale prescribed ("#1791 tracks taking it back
  under the C ceiling, at which point this row and its grant are removed
  together"); develop also dropped one vulture identity (code fixed) and the
  dispositions rows that moved with it.
- Branch vs develop stays purely additive, zero deletions:
  `git diff --numstat origin/develop -- quality/` → `10 +0`
  `ratchet-authorizations.json` (the two #1893 grants),
  `2 +0 reachability-baseline.json`, `11 +0 reachability-dispositions.json`.
- Both grant entries survive intact in the merged
  `quality/ratchet-authorizations.json`.

## exact-debt-ledger at CI argv on merged head aa4fc2abac4a

All three steps of `.github/workflows/vulture-ratchet.yml::exact-debt-ledger`
re-run at exact argv (`RATCHET_BASE_REV` resolves to the new merge base
`e0cca7024ef7`):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0, exact 1321==1321 against base e0cca7024 (count moved 1322→1321
  because develop fixed one identity). Zero unbanked identities, so the round
  brief's "amend quality/vulture-baseline.json" still has no target.
- `check-shipped-surface-truth.py` → exit 0.
- `check-ratchet-provenance.py` (umbrella) → exit 1, failing only on the two
  delegated adapters (`check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py`), on exactly
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
  ("NEW disposition absent from trusted ledger and not covered by an
  already-landed reachability authorization").

Grant-first proof re-run on the merged tree: `RATCHET_BASE_REV=6af21c54e`
makes the full umbrella exit 0 (all 10 ratchets OK), isolating the sole red
ingredient to the grant's absence from the trusted base. Fresh owner-state
check: `git merge-base --is-ancestor 6af21c54e refs/remotes/origin/develop`
is false at develop tip e0cca7024, and none of the 3 new develop commits
touches `quality/ratchet-authorizations.json`. The two-merge rule
(`ratchet_provenance.load_authorizations` reads base-only) therefore still
requires the owner-side grant-first landing on develop; no in-branch edit can
substitute for it without either gaming the reachability ratchet (importing
the inactive contract leaves from a live entry point) or deleting the #1893
deliverable — both rejected as gate-weakening.

## Battery on merged head aa4fc2abac4a

- `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .`
  → 3332 files already formatted.
- Focused pytest (driver five-file set):
  `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  → 346 passed, 3 skipped (skips are DSN-gated PG legs).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  → ok, 16696 unique node IDs (+26 absorbed from develop's #2165/#2204/#2180
  tests, their own inventory notes ride the develop commits; this branch's
  delta remains +0).
- `uv run mypy <ci.yml argv: 10 package src trees>` → "Success: no issues
  found in 1064 source files".

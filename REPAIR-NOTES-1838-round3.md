# REPAIR-NOTES-1838 round 3 — exact-debt-ledger gate repair (job 0d7630e9)

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; develop base `4de7e906d9dc`; starting head `dc8a0fe120d4`.

## What failed (reproduced locally, not guessed)

`exact-debt-ledger` (CI `vulture-ratchet.yml` job, exact args from the workflow) failed at
`dc8a0fe120d4` on the **contract-markers ratchet**, not on vulture:

```
uv run python scripts/check-ratchet-provenance.py
...
FAIL: contract-marker ratchet moved away from trusted state
  - declares-contracts-without-tests::docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md:
    NEW contract-marker gap absent from trusted base and not previously authorized
  - declares-contracts-without-tests::docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md:
    missing from candidate ledger
```

Cause: the round-2 ADR front matter declared `contracts: [boundary, behavioral]` with
`tests: []`. ADR-032's cross-check (enforced by `scripts/check_contract_markers_impl.py`)
classifies exactly that combination as a `declares-contracts-without-tests` gap: the
trusted base (develop) banks 358 gaps, none of them this file, so the candidate moved the
count to 359.

Why it was **not** fixed by amending ledgers: `check-contract-markers-provenance.py` reads
`quality/ratchet-authorizations.json` **from the merge base** (`prov.load_authorizations` on
`trusted_ref.base_sha`), so a grant committed on this branch can never authorize a gap this
branch introduces ("a floor raise takes two merges"). The only in-branch repair is to not
produce the gap.

## Fix

`docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md`, two edits:

1. Front matter: `contracts: []` (the ADR-000-template default) with a comment pointing at
   the ADR-032 cross-check; `tests: []` unchanged with its intent stated.
2. The "Acceptance criteria" paragraph now records *both* fields stay empty until the owner
   accepts the contract and an implementation task is assigned; the AC kinds remain recorded
   in prose (AC-1 boundary; AC-2–AC-6 behavioral) and the implementation change declares the
   kinds together with the marked tests that prove each.

No contract content was removed: the adapter selection, pin evidence, maintainer-signal
gate, interface contract, AC-1…AC-6, vector corpus requirements, test plan and acceptance
record are unchanged. `quality/*` ledgers are untouched.

## Validation executed (all green at the repaired tree)

Exact-debt-ledger job, CI's exact steps and arguments:

- `uv run python scripts/check-ratchet-provenance.py` → exit 0; all 9 ratchets OK
  (`OK: 358 contract-marker gap(s), no candidate-approved expansion`)
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0 (`1302 reviewed identities -> 1302 findings`)

Issue #1838's own deterministic acceptance:

- `uv run python scripts/check-adr-status-language.py && git diff --check` → exit 0

Adjacent gates:

- `uv run python scripts/check-contract-markers.py` → OK, 358 gaps (develop's count)
- `uv run python scripts/check-adr-index.py` → OK
- `maistro_registry.validator.validate_file` on the ADR → 0 errors, 0 warnings, 0 debts
- `uv run pytest tests/test_check_contract_markers.py tests/test_check_ratchet_provenance.py`
  → 53 passed
- `uv run ruff check .` / `uv run ruff format --check .` → pass

## Remaining CI failures at dc8a0fe120d4 assessed as not this branch's

The branch diff vs develop is three markdown files (notes + ADR + one index row); no
Python, dependency, lockfile, workflow or JS changes, so:

- **security / Supply chain (pip-audit)**: CI log says "pip-audit produced no usable report
  after 3 attempts — registry/network outage; retry the job". Environmental; also nothing
  new to audit — the ADR defers the `biscuit-python` dependency line to the implementation
  task. Needs a CI rerun, not a tree change. UNVERIFIED locally (no network reproduction
  attempted).
- **test job**: `npm audit --audit-level=high` failures (JS supply chain, no JS on this
  branch) plus a pytest `RuntimeError: Event loop is closed` excerpt among otherwise passing
  tests — trunk-level flake class also seen on other jobs per prior findings. No test on
  this branch exists to break. UNVERIFIED locally (needs CI rerun on the repaired head).
- **Quality / Contract markers** and **Quality gate (Pillars 1–4, 7, 8)**: both reduce to
  the contract-marker failure fixed above (`check-contract-markers.py` now exits 0; the
  Quality gate failed only because its `quality-contract-markers` dependency failed).

## Test/inventory deltas

None. No test files added or changed; no inventory note required.

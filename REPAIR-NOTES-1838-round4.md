# REPAIR-NOTES-1838 round 4 — salvage commit + firsthand API verification of the adapter contract

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; develop base `4de7e906d9dc`; starting head `9afefc341fd8`.

## Incoming state

Round 3 (job `0d7630e9`) committed `9afefc341` with a clean worktree. The three
salvage jobs that followed (`60850f36` wall-clock timeout after ~90 min,
`9896b565` provider 429, `e9836204` provider 429) all died with `checks: []` —
but the timed-out run had already edited
`docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md` without committing.
Those uncommitted edits (backed up to `/tmp/incoming-1838-salvage.patch` before
any further work) correct the ADR's binding-API facts:

1. limits pattern: retrieve via `AuthorizerBuilder.limits()`, mutate fields, set
   back through `set_limits(limits)` (instead of constructing `AuthorizerLimits`);
2. stub-lag list extended with `AuthorizerBuilder.limits()`;
3. `PrivateKey.from_bytes` / `PublicKey.from_bytes` require a mandatory
   `Algorithm.Ed25519` argument in 0.4.0.

No prior run had verified these claims: the timed-out run was still searching
the local disk for the wheel when it died. Per the round brief ("do not assume
earlier verification claims are true"), every claim was re-derived firsthand.

## Firsthand verification (job 312e6094)

Downloaded the exact pinned wheel from PyPI,
`biscuit_python-0.4.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`,
sha-256 `dd8a012ff384e750e312cd8f9d4d9b4654a4f0c9fff40e42e4a7ddbead3b5ce9`
(matching the PyPI JSON metadata digest), installed into an isolated
Python 3.12.14 venv under `/tmp/biscuit-verify` (project venv untouched), and
probed the live extension:

- `AuthorizerBuilder.limits()` exists; returns the limits object whose
  `max_facts`/`max_iterations`/`max_time` fields are writable; `set_limits(obj)`
  accepts the mutated object. `AuthorizerLimits` is **not** exported from the
  `biscuit_auth` module (`AttributeError`; the PyO3 class is
  `builtins.AuthorizerLimits`), so no Python constructor is reachable — one
  wording amendment was applied to the ADR accordingly (the incoming salvage
  said "would raise `TypeError`"; the observable failure is `AttributeError`
  because the name is absent from the module).
- `PrivateKey.from_bytes(raw)` → `TypeError: ... missing 1 required positional
  argument: 'alg'`; `from_bytes(raw, Algorithm.Ed25519)` OK. Same for
  `PublicKey.from_bytes` (roundtrip `to_bytes()` verified). The salvage's
  "algorithm argument is mandatory" claim is confirmed for both key types.
- `set_time()` takes no argument and stamps the host clock; full
  mint (`BiscuitBuilder(...).build(private_key)`) → attenuate
  (`append(BlockBuilder(...))`) → verify (`from_base64` + `AuthorizerBuilder`
  + `set_limits` + `authorize()`) path succeeds in-scope and DENIES expired,
  out-of-scope and tampered tokens (`AuthorizationError` /
  `BiscuitValidationError`).
- All six exception classes the ADR names are exported: `AuthorizationError`,
  `BiscuitValidationError`, `BiscuitSerializationError`, `BiscuitBuildError`,
  `BiscuitBlockError`, `DataLogError`.
- `set_root_key_id(k)` works at mint and the token still verifies with the base
  key; `revocation_ids` is an attribute list on both `Biscuit` and
  `UnverifiedBiscuit`; `UnverifiedBiscuit.block_source(index)` takes a block
  index.
- The shipped `biscuit_auth/__init__.pyi` stub contains **no** `set_time`,
  `set_limits`, or `limits` declarations and no `AuthorizerLimits` class — the
  stub-lag claim (now including `limits()`) is confirmed.
- PyPI metadata for 0.4.0: `requires_dist: None`; cp312
  `manylinux_2_17_x86_64` and `musllinux_1_2_x86_64` wheels present — the ADR's
  platform and transitive-surface rows hold as written.

## Gate evidence at the salvaged tree (all executed this round)

`exact-debt-ledger` job, CI-exact argv (`RATCHET_BASE_REV=origin/develop` for
the PR-style base):

- `uv run python scripts/check-ratchet-provenance.py` → exit 0; all 9 ratchets
  OK; contract-markers 358 reviewed → 358 current (round-3 fix holds).
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; 1302 reviewed
  identities = 1302 findings; unclassified 0; never_allowlist 0.

Issue #1838's deterministic acceptance:

- `uv run python scripts/check-adr-status-language.py && git diff --check` →
  exit 0.

Adjacent gates:

- `scripts/check-adr-index.py` → OK (index row at `ADR-INDEX.md:233` agrees
  with front matter).
- `scripts/check-contract-markers.py` → OK.
- `check-adr-status-language-provenance.py` / `check-citation-status-provenance.py`
  → exit 0, no candidate-approved expansion.
- `generate-spec-ac-defined-index.py` + `git diff --exit-code
  docs/specs/README.md` → in sync.
- `check-suite-inventory.py` → 21/21 suites match the recorded inventory.
- `maistro_registry.validator.validate_file` on the ADR → 0 errors, 0 warnings.
- `uv run ruff check .` / `uv run ruff format --check .` → pass.
- `uv run pytest tests/test_check_contract_markers.py
  tests/test_check_ratchet_provenance.py` → 53 passed.

## Commit

The salvaged edits plus the one wording amendment are committed on this round;
worktree left clean. Branch delta vs develop remains markdown-only:
`REPAIR-NOTES-1838-round2.md`, `REPAIR-NOTES-1838-round3.md`,
`REPAIR-NOTES-1838-round4.md`, `docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md`,
one `docs/adr/ADR-INDEX.md` row. No Python, dependency, lockfile, workflow, JS
or test changes.

## Test/inventory deltas

None. No test files added or changed; no inventory note required.

## Open by design

The decision gate itself stays open: owner `@BlakeMatthews-dev` (or a
designated architecture/security reviewer) must accept the contract per the
ADR's Decision-acceptance record. Hygiene-command success cannot resolve it, by
the issue's own terms. The hosted pip-audit / npm-audit / event-loop CI
failures cited at `dc8a0fe120d4` are trunk-level and environmental (markdown
-only branch, no dependencies added); they need a CI rerun at the repaired head,
not a tree change.

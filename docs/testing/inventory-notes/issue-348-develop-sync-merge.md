---
inventory-delta:
  tests/: +6
---
# issue-348-develop-sync-merge

The develop sync this branch was carrying (`MERGE_HEAD=5647c34b`, develop's
`[M3-A]` develop-sync merge) was resolved in the worktree, and the merged
tree was rebuilt and re-verified from scratch. This note records what moved
and what the evidence says; the earlier rounds live in
`issue-348-verify-develop-sync-9dc62e0b.md`.

## What moved

**The conflict resolution.** Five files conflicted. The resolution keeps
HEAD's lock-enforced install mechanism — `uv export --locked` plus
`--require-hashes` — and adopts develop's newer base-image digests, the
`dockerclibuild` stage, the license-inventory gate, the cache clean and the
prune steps:

- `Dockerfile`, `Dockerfile.research`, `Dockerfile.rsi-runner`,
  `packages/hive-conductor/Dockerfile`, `deploy/sbx/template/Dockerfile`:
  develop's unpinned build-time installs are gone. `Dockerfile.rsi-runner`'s
  second, unpinned `uv pip install coverage bandit radon interrogate vulture
  pylint` step is dropped rather than kept: the `rsi-fitness` extra already
  names those tools, and the extra is installed from the lock.
- `.github/workflows/security.yml`: the two runtime assertions move to
  develop's Python (`3.13.16`) and to `bip-utils 2.12.2` — the merged lock's
  pin, which develop's own `2.12.1` contradicts. Develop's license-inventory
  upload sits next to HEAD's "Reconcile installed packages to uv.lock" step;
  the old `pip-licenses` step is dropped in favour of the checked-in policy
  gate (`scripts/check-license-inventory.py` + `quality/license-policy.json`).
- `packages/maistro-server/pyproject.toml`: the `image` extra gains
  `sqlite`. The engine image boots `SqliteCampaignStore` /
  `SqliteWorkspaceLogStore` and the backlog history import pulls `aiosqlite`;
  without the extra the locked export for that image carried no SQLite driver
  at all. Re-locked: `uv lock` → 468 packages, `uv lock --check` clean.

**A merge-introduced break, found by building.** Develop's root
`pyproject.toml` carries `constraint-dependencies = ["aiohttp>=3.14.4"]` (the
CVE-2026-111064 floor the pip-audit gate needs over the dev environment, where
aiohttp arrives through cosmic-ray). `uv pip install` run inside the project
folds that floor into the install request, and `--require-hashes` rejects an
unpinned requirement:

    error: In `--require-hashes` mode, all requirements must have their
    versions pinned with `==`, but found: aiohttp>=3.14.4

Every production image build died on it (the floor names a package none of
them ship aiohttp for). The fix is `--no-config` on the hash-verified
installs: the install consumes the exported lock and nothing else. The floor
still binds where it belongs — `uv lock`/`uv sync` read the manifest, and the
lock is what the images install.

**The research test follows the mechanism.** Develop's
`test_research_reasserts_pillow_security_floor_after_browser_install` read the
security floors off the second, unpinned `uv pip install --system` step — the
step that could land a dependency set no scanner audited. That step is gone,
so the test now reads the floors out of `uv.lock` (PEP 440 comparison, so
9.x does not pass as "newer" than 13.x) and asserts the image installs the
locked browser stack, with no `uv pip install --system` left to re-resolve.
The test is renamed
`test_research_ships_the_locked_browser_stack_above_the_security_floors`;
the floors are develop's, unchanged (aiohttp ≥ 3.14.4, anyio ≥ 4.14.2,
pypdf ≥ 6.19.0, pillow ≥ 13.0.0, browser-use ≥ 0.1.40).

**One new contract test** (`tests/test_image_lock_contract.py`): every
hash-verified install must carry `--no-config`. Six parametrized cases, one
per image Dockerfile.

## Evidence (executed in this worktree, docker 29.1.3)

- `uv lock --check` clean (468 packages); `ruff check .` and
  `ruff format --check .` clean (3409 files).
- `uv export --locked` for all four image contracts, each with hashes.
- All four production images build from the merged tree and reconcile to the
  lock (`scripts/check-image-lock-reconciliation.py`):
  - `maistro-engine:verify-348` → 128 distributions, 3 members;
  - `maistro-engine-research:verify-348` → 148 distributions, 2 members;
  - `maistro-rsi-runner:verify-348` → 220 distributions, 4 members;
  - `hive-conductor:verify-348` → 72 distributions, 6 members.
  The engine image runs Python 3.13.16, carries `aiosqlite 0.22.1`, and
  imports `maistro_server.main`.
- AC-2 red directions, in throwaway copies of the build context: a pyproject
  floor above the locked version makes `uv export --locked` exit 1 ("No
  solution found … httpx>=99.0 … unsatisfiable"); zeroing every hash of one
  pinned package makes the hash-verified install exit 1 ("Hash mismatch for
  `sniffio==1.3.1`").
- AC-5 emulated locally: two independent `--no-cache` builds of the engine
  image produced byte-identical dependency manifests (128 distributions).
- The new contract test fails when `--no-config` is removed from
  `Dockerfile.research` ("reads the project at install time") and passes when
  it is restored.
- Gates: `check-merge-markers`, `check-build-context`, `check-image-inventory`,
  `check-image-pins`, `check-uv-setup`, `check-workflow-inventory`,
  `check-suite-inventory`, `check-backlog-consistency`, `check-required-checks`,
  `check-branch-protection` — all exit 0.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0 (1321 findings against 1326 reviewed
  identities, 0 unclassified).

## Residual

- The lock resolves `browser-use` to 0.5.9, not the 0.13.11 develop's
  unpinned install would have fetched: browser-use ≥ 0.11.13 requires
  `openai>=2.7.2,<3` and the workspace pins `openai>=1.40,<2`. This is the
  repository's own constraint, not a #348 decision — and develop's unpinned
  install could have shipped a browser-use/openai combination that violates
  it. `maistro.tools.browser.client` lazy-imports `browser_use` and probes
  its API with `getattr` fallbacks, so the older release is import-compatible
  by construction, but the browser tool's behaviour on 0.5.9 is not exercised
  by any test in this repository.
- `browser-use` is not in the `aiohttp`/`pillow` floors' dependency set, so
  the research image ships neither aiohttp nor pillow: the floors are
  asserted against the lock, not against a package the image installs.
- The license-inventory gate (`scripts/check-license-inventory.py`) needs
  syft-generated SBOMs and was not run locally in this round; the CI job that
  runs it against the built images is unchanged by this merge. The #348 half
  of AC-3 — the scans and the shipped set describing the same packages — is
  what the reconciliation above proves.

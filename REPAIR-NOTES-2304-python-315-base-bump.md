# Repair notes: #2304 — `python:3.13.16-slim-bookworm` → `3.15.0-slim-bookworm` in `packages/hive-conductor`

Verdict: **NEEDS-REPAIR** — the dependabot bump cannot be completed or made green by a
focused, evidence-respecting change. Every red gate on head
`c5ee70aa85d98cd18fd6cc15ef2ed7af4a88695e` traces to two root causes, both inherent to
the bump itself. This file records the evidence chain; it changes no production file.

## What the PR changes

Exactly one commit of content (`63a7c8c2c`): two `FROM` lines in
`packages/hive-conductor/Dockerfile` (stages `pybuild` and `runtime-apt`) move from
`python:3.13.16-slim-bookworm@sha256:73aa5fae…` to
`python:3.15.0-slim-bookworm@sha256:0e019bbd…`. The digest is genuine: the manifest
list of the tag `python:3.15.0-slim-bookworm` (docker manifest inspect, 2026-10-26) is
byte-identical to the digest-only pull. The problem is not the pin; it is what the pin
does to the contracts layered on it.

## Root cause 1 — the bump breaks the pinned CPython 3.13 identity contract (6 gates)

`packages/hive-conductor/Dockerfile` documents and enforces the contract the bump
violates:

- lines 5–8: "The Conductor identity contract is pinned to CPython 3.13: coincurve
  21.0.0 publishes the required Linux wheels for cp313, but not cp314. Keep the exact
  patch version here so a moving base tag cannot silently change that contract."
- line 122: `uv venv --python 3.13 /app/venv` — on a `3.15.0` base there is no
  `python3.13` binary, so uv silently downloads a **managed** CPython 3.13.
- line 172: the build-time smoke asserts `sys.version_info[:3] == (3, 13, 16)` and the
  identity pins (`bip-utils==2.12.2`, `coincurve==21.0.0`, `pynacl==1.6.2`), "and fail
  if a native wheel was not selected".
- lines 227–229: pip pruning paths are hardcoded to `python3.13`.

CI evidence (job logs fetched read-only via the API, runs of 2026-10-24):

- `docker-build` (job 120894220166): `AssertionError: 3.13.15 (main, Sep 29 2026 …)` at
  `[hive pybuild 11/12]` → "docker buildx build failed with exit 1 on attempt 2/2".
- `hive-conductor-e2e` (120894220066), `hive-conductor-e2e-ui` (120894220125),
  `Container scan + SBOM + cosign` (120893927184), `Gate C — canonical clean install`
  (120893926800): the identical assert failure on the identical build step.
- `integration-scope` (120893927095): "hive-conductor-e2e is required by integration
  scope but concluded failure" — purely downstream.

Local reproduction of the mechanism (uv from the pinned `ghcr.io/astral-sh/uv:0.12.21`
generation, fresh `UV_PYTHON_INSTALL_DIR`): `uv venv --python 3.13` resolves to
**CPython 3.13.15** — the exact version CI rejected. The managed-3.13 fallback can never
satisfy the `(3, 13, 16)` pin, and even if it resolved 3.13.16, the shipped image would
be a 3.15 base with a downloaded, unpinned-by-digest interpreter — a silent contract
change of exactly the kind lines 5–8 forbid.

Why the contract cannot simply move to 3.15: PyPI (`pypi.org/pypi/coincurve/21.0.0/json`,
queried 2026-10-26) lists coincurve 21.0.0 wheels for cp39–cp313 only — **no cp314 and
no cp315 wheels exist**. A true 3.15 venv cannot install the identity stack as native
wheels, and the `slim` builder carries no toolchain to build it from source. Completing
this bump therefore requires a new coincurve release with cp315 wheels, new identity
pins, a rewritten Dockerfile contract, `quality/image-pins.json`, the distribution
contract and CI smoke surfaces, and full e2e/scan proof — a reviewed identity-contract
migration, not a dependabot base bump.

Policy precedent: #2099 (landed) refreshes patch releases "rather than introducing a
Python minor-series migration" and retains "the CPython 3.13 native-crypto
compatibility contract"; #2118, the same-shape 3.14 bump (Dockerfile-only), was closed
unmerged.

## Root cause 2 — the pins ledger was not moved with the Dockerfile (4 gates)

`quality/image-pins.json` is the approval authority that "holds the registry and the
tree closed" (#349): a base update is always a change to this file plus the Dockerfiles
together. Dependabot changed only the Dockerfile, so:

- `uv run python scripts/check-image-pins.py` → 2 violations (exit 1, reproduced locally):
  1. `python:3.13.16-slim-bookworm@sha256:73aa5fae…`: used_by drift — registry names
     `['Dockerfile', 'packages/hive-conductor/Dockerfile']`, the tree uses `['Dockerfile']`;
  2. `python:3.15.0-slim-bookworm@sha256:0e019bbd…`: pinned digest not registered
     (used by `packages/hive-conductor/Dockerfile`).
- `Quality / Image pins` (job 120893927735): the same two violations.
- `test` (120893926847): exactly one failed test,
  `tests/test_check_image_pins.py::test_dunder_main_entrypoint_runs_the_real_gate`
  (`assert [1] == [0]`) — it runs the real gate; reproduced locally
  (`uv run pytest tests/test_check_image_pins.py -x -q`: 1 failed, 37 passed).
- `Coverage gate (publish-set floor + diff coverage)` (120898249475): the same two
  violations in its check leg.
- `Quality gate (Pillars 1–4, 7, 8)` (120896835261): "quality-image-pins: dependency
  did not succeed" — purely downstream.

Registering the 3.15.0 row would fix these four gates mechanically, but it would have
the ledger approve a base that root cause 1 proves cannot build — the ledger must move
together with a *working* contract, not paper over a broken one.

## Resolution paths (decision owner: maintainer, via GitHub — not executable from this lane)

1. **Close #2304** following the #2118 precedent and refresh within the 3.13 line when
   the next patch release lands (the #2099/#1152/#2238 shape: both Dockerfiles, ledger
   row, smoke CONTROL_IMAGE, contract test — one reviewable change).
2. **Fund the CPython 3.15 identity-contract migration**: unblocked upstream only when a
   coincurve release with cp315 wheels exists; then change contract pins, Dockerfile
   contract block (lines 5–8, 122, 172, 227–229), ledger row, distribution-contract and
   CI smoke surfaces together, with e2e + container-scan evidence.

No production file is modified by this notes-only commit; weakening the line-172 smoke,
editing the ledger, or reverting dependabot's commit are all refused on evidence (gate
weakening / ledger approval of a broken base / falsifying the PR's purpose).

## Commands run in this repair (all local, `uv`-managed)

- `uv run python scripts/check-image-pins.py` → exit 1, the 2 violations above.
- `uv run pytest tests/test_check_image_pins.py -x -q` → 1 failed, 37 passed (same test as CI).
- `uv run ruff check .` / `uv run ruff format --check .` → pass (job check logs 1–2).
- `uv venv --python 3.13` (fresh managed install dir) → CPython 3.13.15 (reproduces the CI assert).
- `docker manifest inspect python:{3.15.0-slim-bookworm, sha256:0e019bbd…}` → identical manifest lists.
- PyPI coincurve 21.0.0 wheel inventory → cp39–cp313 only.

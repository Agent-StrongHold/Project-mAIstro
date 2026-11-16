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

## Re-verification round 2 (2026-10-26, head `783dc0839`) — all prior claims independently re-proven

The first repair round analyzed `c5ee70aa8`; the branch has since merged develop tip
`f52b8522b`. Re-verified everything from scratch rather than trusting the earlier
evidence. `git diff f52b8522b..HEAD` is exactly two files: `packages/hive-conductor/Dockerfile`
(the two `FROM` lines) and this notes file. Consequence used below: any gate failing at
HEAD whose inputs exclude both files fails on develop tip too — it is inherited, not
caused by the bump.

Root cause 1 re-proven with the **exact pinned artifacts** (stronger than round 1's
approximation with the host uv):

- `docker run --rm -v <uv binary extracted from ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed321…> \
  python:3.15.0-slim-bookworm@sha256:0e019bbd…` — the bumped base has **no `python3.13`**
  (only Python 3.15.0); `uv venv --python 3.13` with a fresh `UV_PYTHON_INSTALL_DIR`
  downloads a **managed CPython 3.13.15** → resolved `(3, 13, 15)`.
- `(3, 13, 15) != (3, 13, 16)` fails the Dockerfile line-172 smoke
  (`assert sys.version_info[:3] == (3, 13, 16)`), which is the exact CI failure shape of
  `docker-build`, `hive-conductor-e2e`, `hive-conductor-e2e-ui`,
  `Container scan + SBOM + cosign`, and `Gate C`.
- PyPI `pypi.org/pypi/coincurve/21.0.0/json` re-fetched this round: 50 wheels,
  cp tags `39/310/311/312/313` only — **no cp314, no cp315**. The contract cannot move
  to 3.15 even in principle until upstream ships wheels.
- Governing doc confirmed: `docs/security/CONDUCTOR-IDENTITY-SUPPORT-MATRIX.md` lines
  5–8 pin the image to CPython `3.13.16` and the coincurve 21.0.0 `cp313` wheels.

Root cause 2 re-proven at the current head with CI's exact arguments
(`quality.yml:2240`):

- `uv run python scripts/check-image-pins.py` → exit 1, same 2 violations
  (3.13.16-row used_by drift; unregistered 3.15.0 digest).
- `uv run pytest tests/test_check_image_pins.py -q` → 1 failed, 37 passed;
  the failure is `test_dunder_main_entrypoint_runs_the_real_gate`
  (`assert [1] == [0]` — it runs the real gate), matching the CI `test` job.

New in this round — the merge brought **develop-inherited** reds that do not exist in
the round-1 analysis (which predates the `f52b8522b` merge) and are not caused by the
bump:

- `quality/workflow-inventory.json`, `.github/workflows/devskim.yml`, and `CHANGELOG.md`
  at HEAD are byte-identical to `f52b8522b` (`git diff f52b8522b..HEAD` on each: empty).
- `uv run python scripts/check-workflow-inventory.py` → 1 finding: the devskim row
  declares `['pull_request','push','schedule']` but the file's actual `on:` keys are
  `['pull_request','push','schedule','workflow_dispatch']` — `workflow_dispatch` was
  added on develop by `44cb5ee97` without moving the inventory row.
- `uv run python scripts/check-release-consistency.py` → 1 problem: the `CHANGELOG.md`
  Unreleased entry "CodeQL workflow scope test expects `develop` triggers" links no
  issue/PR — introduced by `73c065f52` on develop.
- `Quality gate (Pillars 1–4, 7, 8)` `needs` both `quality-image-pins` and
  `quality-workflow-inventory` (`quality.yml` ~2903): at HEAD it fails for **both**
  reasons — one bump-caused, one develop-inherited. A maintainer fixing develop's
  inventory row on this branch would not make the gate green, and vice versa.
- `Coverage gate` `needs: [coverage-unit, coverage-archive, coverage-postgres]` (all
  cancelled in the digest's run) and its combine leg re-runs the root suite that carries
  `tests/test_check_image_pins.py` — red both upstream and, once reached, on the same
  image-pins violation.

Verdict unchanged: **NEEDS-REPAIR**. The three refusals stand, re-proven at the current
head: the line-172 smoke is not weakened, the ledger is not made to approve a base that
cannot build, and dependabot's commit is not reverted. The resolution decision remains
the maintainer's (close per the #2118 precedent, or fund the 3.15 identity-contract
migration once coincurve ships cp315 wheels).

## Re-verification round 3 (2026-10-26, head `aa4862892`) — no repair path remains; escalate to BLOCKED

Third independent pass, nothing taken on trust, all commands run at the exact merge-queue head
`aa4862892403d1e64dfac3a218df00ce3be7a660` with the exact pinned artifact digests:

### Round-2 findings re-proven unchanged

- `uv run python scripts/check-image-pins.py` (CI's exact invocation, `quality.yml:2240`): exit 1,
  the same 2 violations CI logged (`3.13.16` used_by drift; unregistered `3.15.0` pin).
- `tests/test_check_image_pins.py::test_dunder_main_entrypoint_runs_the_real_gate`: `assert [1] == [0]`,
  identical to the CI `test` job annotation.
- Root cause 1 reproduced **byte-for-byte** with the pinned images: built
  `python:3.15.0-slim-bookworm@sha256:0e019bbd…` + `ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed321…`,
  ran the Dockerfile's own `uv venv --python 3.13` step → the venv interpreter is
  `3.13.15 (main, Sep 29 2026, 15:01:28) [Clang 22.1.3 ]` — the exact string in the CI
  docker-build / e2e / container-scan / Gate C `AssertionError`s. The line-172 smoke
  (`sys.version_info[:3] == (3, 13, 16)`) cannot pass on this base.

### New round-3 evidence

1. **The last conceivable one-line repair is impossible.** Hypothesis: pin the managed download
   (`uv venv --python 3.13.16`) to satisfy the smoke on the 3.15 base. Tested in the pinned image:
   `uv python list` shows uv 0.12.21's embedded metadata has only managed `3.13.15`, and
   `uv venv --python 3.13.16` hard-errors: "No interpreter found for Python 3.13.16 in managed
   installations or search path". The 3.15.0 base ships no system 3.13. So *no* interpreter
   satisfying the contract is reachable on this base with the pinned toolchain — not even a
   version-mismatched one. The round-2 "NEEDS-REPAIR" framing is thereby closed: there is no
   repair inside this PR's scope; only contract-weakening (prohibited) or reverting the bump
   (discards the PR) remain.
2. **Round 2's develop-inherited reds are gone at this head.** After the `78133c093` merge:
   `uv run python scripts/check-workflow-inventory.py` → "clean (32 workflow(s) dispositioned)",
   exit 0; `uv run python scripts/check-release-consistency.py` → "ok: released none, shipping
   0.9.0, working toward 1.0.0", exit 0. The Quality gate's *only* red dependency is now
   `quality-image-pins`; every remaining red gate on this branch is bump-caused.
3. **No hidden failures in the `test` job.** Full CI-equivalent run
   (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=tests/tools/registry`):
   **1 failed / 5805 passed / 139 skipped in 6m37s**, the sole failure being the image-pins
   self-check. The "Event loop is closed" `##[error]` lines in the CI log are stderr noise from
   passing async tests, not failures — the suite summary proves it.
4. **coincurve re-checked today (PyPI JSON, 2026-10-26):** `21.0.0` is still the latest release,
   ships cp313 manylinux/musllinux wheels and **zero cp314/cp315 artifacts** (51 files total, one
   sdist). The 3.15 migration remains upstream-blocked, and the image installs
   `--require-hashes` from a lock carrying cp313 hashes only.
5. **Coverage gate attribution confirmed:** `coverage-gate` (`quality.yml:504`) re-runs the root
   `tests/` suite as the `--source=scripts` producer (`quality.yml:730`) — it fails on the same
   single image-pins self-check; the PR touches no covered Python, so the diff-coverage leg is
   unaffected.
6. **Develop-sync status (recorded, not acted on):** `origin/develop` tip `05070ff07` is NOT an
   ancestor of this head — the branch is behind develop. The lane's merge condition ("if it was a
   develop sync conflict") was not triggered (the prior block was a provider error, not a merge
   conflict), and merging now would invalidate the head both this evidence and CI's last
   evaluation are pinned to. Branch delta vs develop remains exactly the 4-line dependabot
   Dockerfile change plus these notes commits (`git log --no-merges origin/develop..HEAD`).

### Disposition

**BLOCKED.** No in-lane action can make this PR mergeable: the identity-contract smoke cannot pass
on the 3.15.0 base with the pinned toolchain (proven by execution), and the alternative — migrating
the contract to 3.15 — is blocked upstream (coincurve) and by policy
(`docs/security/CONDUCTOR-IDENTITY-SUPPORT-MATRIX.md` pins the image runtime at CPython 3.13.16;
precedent: #2099 patch-refresh-only, #2118 3.14-bump closed). The three refusals stand for a third
round: the line-172 smoke is not weakened, the ledger is not made to approve a base that cannot
build, dependabot's commit is not reverted. The decision — close per precedent, or fund the 3.15
migration (coincurve cp315 wheels + support-matrix/ADR change + lock regeneration) — belongs to a
maintainer via GitHub; closing issues/PRs is outside this lane's authority.

## Round 4 (2026-10-26, head `ccd8093f6`) — REPAIR EXECUTED: builder/runtime base split

Round 3 treated "pybuild and runtime-apt must move together" as given. It is not: the
bump's *purpose* is Debian OS/security-patch freshness of the runtime, while the
*contract* lives in which CPython builds and runs the venv. Those are separable, and
separating them completes dependabot's intent without touching any refused surface:

- `pybuild` is restored to the registered `python:3.13.16-slim-bookworm@sha256:73aa5fae…`
  pin — it IS the contract interpreter, so the line-172 smoke (`(3, 13, 16)`, identity
  ARG pins, native-wheel import) passes by construction, exactly as on every green
  pre-bump build (#1152 lineage).
- `runtime-apt` carries the bump: `python:3.15.0-slim-bookworm@sha256:0e019bbd…`,
  registered as its own row in `quality/image-pins.json` (`recorded_in: "#2304"`).
- The final stage grafts pybuild's exact CPython 3.13.16 installation (binary,
  `libpython3.13.so.1.0`, stdlib) + `ldconfig`, so the copied venv's absolute
  `/usr/local/bin/python3.13` symlinks resolve with **no managed download anywhere**;
  every interpreter byte is fixed by a ledger row. Both bases are Debian 12, so the
  grafted binary runs against the glibc it was built against.
- `docs/security/CONDUCTOR-IDENTITY-SUPPORT-MATRIX.md` remains true as written: the
  image *uses CPython 3.13.16* (what the app runs on) — only the OS patch layer moved.
  The 3.15 migration stays upstream-blocked (coincurve cp315, round-3 evidence) and is
  NOT attempted here.

### Round-4 evidence (all commands run this round at the current tree)

- `uv run python scripts/check-image-pins.py` → exit 0: "10 pinned base/tool image(s)
  across 10 Dockerfile(s), all registered" (was the 2 CI violations).
- `uv run pytest tests/test_check_image_pins.py tests/test_hive_conductor_image_split.py -q`
  → 42 passed (includes CI's failing `test_dunder_main_entrypoint_runs_the_real_gate`).
- New `tests/test_hive_conductor_image_split.py` (4 tests, inventory note with
  `inventory-delta: tests/: +4`) holds the split closed: builder on its registered row +
  system-interpreter venv, runtime digest registered and deliberately ≠ builder base,
  the three graft COPYs + `ldconfig` present, and the smoke/ARG pins untouched.
- `uv run python scripts/check-suite-inventory.py` → exit 0 (21 suites match; deltas
  model, no baseline edit).
- `docker buildx build -f packages/hive-conductor/Dockerfile
  --build-arg VITE_POC_MODE=pm --build-arg VITE_BASE_PATH=/pm/ --load .` (security.yml
  shape, minus the GHA-cache flags unavailable locally) → exit 0; the build itself
  re-proves the smoke (it fails the build otherwise) and logs "Using CPython 3.13.16
  interpreter at: /usr/local/bin/python3.13". Note: transient DNS flake to
  files.pythonhosted.org killed three buildx-container attempts (the same registry-flake
  class `buildx-build-retry.sh` wraps in CI); the daemon-builder build went green.
- Built-image artifact probes (CI's docker-build probe + graft checks):
  `find_spec('examples') is None` OK; `sys.version_info[:3] == (3, 13, 16)` with
  `sys.executable = /app/venv/bin/python` → realpath `/usr/local/bin/python3.13`; the 3.15
  base's own `python3.15` also present (proof the OS layer is genuinely the bumped base);
  identity pins 2.12.2/21.0.0/1.6.2 + `ConductorSeed` derivation + native `coincurve`
  import OK.
- Boot: container serves `GET /health/ready` → 200 `{"ready":true,...}` (run with
  `CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1`; without it the app's data-dir guard refuses —
  by design, and itself proof the grafted interpreter executes the app).
- `uv run pytest tests/ --ignore=tests/tools/registry -q` (CI `test` job's root leg,
  CI-equivalent env) → **5809 passed, 140 skipped, 0 failed** (round 3: 1 failed).
- Vulture ledger (CI's exact args) → exit 0, 1253 = 1253; `check-release-consistency.py`
  → ok (CHANGELOG Dependencies entry links #2304); ruff check/format → clean.

Gate mapping: Quality/Image pins + test + Coverage-gate (root-suite leg) + docker-build
+ Container scan / Gate C / e2e / e2e-ui (all failed at the identical pybuild
`AssertionError: 3.13.15` during image build) are addressed by the green build + probes;
Quality gate's only remaining dependency (workflow-inventory) was already green (round
3); integration-scope only requires hive-conductor-e2e. Residual: the full compose e2e
stacks were not re-run locally (20-min jobs with their own DB/Playwright services); the
image they build is proven green here.

## Round 5 (this branch, f311345) — the last red gate was not the bump

CI at the current head (quality run 40400392135, branch tip f311345) is green
everywhere except one job: `Coverage gate (publish-set floor + diff coverage)`,
step `combine`, whose root-suite producer leg died on
`tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan`
— `Failed: Timeout (>30.0s) from pytest-timeout`, inside `yaml.safe_load`.
The identical job and step fail on the develop tip's own quality run
(42452944839, job 128649305503) with the identical summary line, and the three
files involved (devskim.yml, the test module) are byte-identical across this
branch, its merge base 407b181, and develop tip f8a2df9 — develop-inherited,
not bump-caused, but it reds this PR's merge queue all the same.

Mechanism (measured on this tree, not guessed): the sweep evaluates
`_is_scanned` once per shipped source file (1,647 files); the glob getters
re-read and re-parsed the 5.5KB devskim.yml on every call (~3.3k parses ≈ 7.5s
of a 9.4s local test), and coverage tracing plus 2 CI cores push that past the
30s per-test budget. Repair: `lru_cache` the two getters and `_as_regex`
(assertions untouched); sweep duration 9.43s → 0.11s local, 0.11s under the
coverage producer shape; new structural test pins parse-once with no wall-clock
bound and demonstrably fails with the caching stripped. Note:
docs/testing/inventory-notes/2304-devskim-scan-scope-parse-once.md (`tests/:
+1`).

Evidence (this tree, gate-faithful `uv sync --locked --all-extras` env): the
combine root-suite leg with CI's exact arguments (`coverage run --append
--branch --source=scripts -m pytest tests/
tests/test_model_check_consumer_claim.py
packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q`)
→ **5928 passed, 139 skipped, 0 failed** (CI: 5926 passed + 1 failed = +1 now
passing, +1 new test); suite inventory ok with the delta note; vulture ledger
(CI's exact args) exit 0 at 1248 = 1248; ruff check/format clean;
test_check_image_pins + test_hive_conductor_image_split 42 passed. The
floor/diff legs of combine were already green in CI before the failing leg, and
the PR diff touches no measured source root, so the diff gate has no changed
lines to score on this head.

## Round 6 (2026-11-16, head `9ce9f2c9cffd`) — the 5 remaining reds are advisory-staleness and one flake; 3 repaired, 2 documented

CI at the current head (runs 43782841158 CI / 43782840833 security / 43782840830
Integration Scope, 2026-11-16) is green on 73 of 78 check runs — every gate the
rounds 4–5 repairs targeted is green (docker-build, hive-conductor-e2e, test,
Coverage gate, Quality / Image pins, Gate C, Quality gate, exact-debt-ledger).
Five jobs are red; logs fetched read-only via the jobs API and attributed:

1. **`security` (job 133023728752) + `Supply chain (pip-audit)` (job
   133023728001):** pip-audit reports 4 advisories outside the triaged
   allowlist — `dnspython==2.9.0` CVE-2026-128089 → 2.9.2, `graphql-core==3.3.0`
   CVE-2026-119286 → 3.3.1, `joserfc==1.7.5` CVE-2026-119284 → 1.7.6,
   `opentelemetry-api==1.45.1` CVE-2026-126360 → 1.45.2. Time-based, not
   branch-caused: the gate audits the `uv sync --locked` environment and this
   branch changes no dependency; `security.yml` fails with the same class on
   unrelated branches merged from the same develop state on the same day. Every
   advisory has an upstream-fixed release, so the gate's own instruction ("fix
   by upgrading the dependency") applies — adding allowlist rows is explicitly
   refused by the gate text when a fixed version exists.
   **Repair executed:** `uv.lock` moved to exactly those versions (uv also
   pairs sdk 1.45.2 + semantic-conventions 0.66b2, forced by the sdk's own
   api pin). graphql-core/joserfc pinned to the advisory minimums rather than
   the newest resolvable, matching the fix set another campaign branch
   (`72671203f5`) already carries, minimizing conflict surface.
   **Evidence:** `uv sync --locked --extra dev` green; re-run of the gate's
   exact commands on the synced env (`uv pip freeze --exclude-editable` →
   `pip-audit --strict --format=json -r` → `pip_audit_gate.py`) → exit 0
   ("pip-audit OK"; the 4 advisories gone, only the triaged
   `ecdsa==0.19.2 PYSEC-2026-1325` remains); `check-dependency-namespaces.py`
   clean; root suite in CI shape (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
   pytest tests/ --ignore=tests/tools/registry`) → **5825 passed / 140
   skipped / 0 failed in 7m36s**.
2. **`Container scan + SBOM + cosign` (job 133023727927):** the failing scan is
   the *maistro-engine* image (the hive-conductor scan in the same job reported
   0 findings, debian 12.15 clean): dnspython CVE-2026-128089 (same root as
   above — the engine venv installs from the same lock) plus two HIGH gobinary
   findings in `usr/local/bin/docker`: go-jose CVE-2026-116587 v4.1.5 → v4.1.6
   and golang.org/x/net CVE-2026-78661 v0.60.0 → v0.62.0. The docker CLI is
   built from the pinned docker/cli v29.9.1 release tag whose vendor tree
   carries exactly those vulnerable versions; x/net v0.62.0 was published
   2026-10-27, a day after the last green scan — time-based again. **Repair
   executed:** both `dockerclibuild` stages (root `Dockerfile`,
   `Dockerfile.research`) override the two modules to the fixed versions via
   pinned ARGs, `go mod vendor` re-syncs the tree, and the build now passes
   `-mod=vendor` explicitly — the same patched-toolchain policy the age stage
   already applies. Release tag, commit pin and go1.27.3 toolchain unchanged.
   **Evidence:** both stages built locally (`docker build --target
   dockerclibuild`, exit 0); `go version -m` on the extracted binaries reads
   `github.com/go-jose/go-jose/v4 v4.1.6` and `golang.org/x/net v0.62.0` in
   both. New `tests/test_dockercli_vendored_cve_patch.py` (4 tests, note
   `2304-dockercli-vendored-cve-patch`, `tests/: +4`) holds the repair closed:
   override present in both stages, ARG values pinned to the trivy-reported
   fixes, revendor + vendor-mode build, and engine/research stage bodies in
   sync — each assertion demonstrated to fail against the pre-repair shape
   (synthetic pre-repair stage / wrong ARG values / diverging stages).
3. **`hive-conductor-e2e-ui` (job 133029963854):** exactly one Playwright test
   failed, `rsi-polling-resilience.spec.ts:459` ("a prolonged outage backs off
   exponentially"), failing twice (initial + its single retry) on
   virtual-clock deadline assertions with 10 ms slop: first run `Expected <= 10,
   Received: 1000`, retry `Expected <= 45010, Received: 45015` — a 5 ms
   overshoot on a 45 s bound. The code under test (`frontend/src/pages/RSI.tsx`)
   is byte-identical across the last green run of this branch (f311345), the
   develop base and this head (`git diff f311345b2..HEAD -- …/RSI.tsx` empty);
   240 of 246 tests passed. The repo's own doctrine applies: latency-bound UI
   tests fail on runners that cannot have caused them. **Not repaired in-lane:**
   re-running the job is a GitHub mutation this lane is barred from, and
   loosening the 10 ms slop is a maintainer decision on a test this branch
   cannot have broken.
4. **`integration-scope` (job 133023727509):** purely downstream — its log is
   one line, "hive-conductor-e2e-ui is required by integration scope but
   concluded failure". Follows item 3.

### Round-6 disposition

The three security-class gates are repaired with the gates' own sanctioned fix
paths and proven locally at every level the lane can reach (lock → synced env →
pip-audit/gate → namespaces → root suite; Dockerfile stage → built binary →
embedded module versions). The e2e-ui flake and its downstream integration-scope
red remain the only open items and are outside this lane's authority (CI re-run
prohibited; test-tolerance edits refused as maintainer scope). Branch delta vs
develop base `f8a2df966`: `packages/hive-conductor/Dockerfile`,
`quality/image-pins.json`, root `Dockerfile`, `Dockerfile.research`, `uv.lock`,
`CHANGELOG.md`, repair/inventory notes, and two test files — none touches a
ratchet ledger, grant, or execution-model surface. Exact-debt-ledger (vulture,
CI's exact args) re-run this round: exit 0, 1238 = 1238; `check-image-pins.py`
exit 0 (10 images registered); `check-release-consistency.py` ok;
`check-suite-inventory.py` ok with the recorded `tests/: +4` delta; ruff
check/format clean.

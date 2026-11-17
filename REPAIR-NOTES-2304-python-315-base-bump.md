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

## Round 7 (2026-11-16, head `76b145407` repair) — the one red gate is trivy
## python-pkg staleness on maistro-engine-research; the grype cross-check's next
## findings are pre-empted with registry-verified digest refreshes

CI at head `76b145407` (check-run snapshot captured 2026-11-16 ~10:38 UTC, run
started 06:21) is green on 77 of 78 checks — every gate rounds 4–6 targeted is
green. The single red job is `Container scan + SBOM + cosign` (job
133128530798). Full job log fetched read-only and re-read from scratch: the
npm audit lines quoted in the earlier dispatch evidence are the tail of the
frontend stage's *passing* `RUN npm ci` (`#29 DONE 37.8s`, "7 moderate severity
vulnerabilities" is advisory noise, npm ci exits 0 on it); the actual failure
is the third `trivy-action` step at 06:34:36:

- **Failed scan: `maistro-engine-research:pr-2304` (debian 13.7), Python
  (python-pkg): 13 HIGH, all `fixed`** — `oauthlib` 4.0.0 → 4.0.1
  (CVE-2026-49272), `pyasn1` 0.6.4 → 0.6.5 (CVE-2026-119194/195/196/197),
  `pypdf` 6.21.2 → 6.21.3/6.21.4 (CVE-2026-119203…119209), `soupsieve` 3.0.3
  → 4.0.0 (CVE-2026-126190). The first two scans in the same job
  (hive-conductor, maistro-engine) passed; the rsi-runner scan never ran (job
  aborted at research). The research image installs `maistro-server --extra
  observability --extra browser` from this `uv.lock`, so the lock is the
  surface, and the gate's own policy (upgrade when a fixed release exists)
  applies.
- **Repair executed:** targeted `uv lock` bumps of exactly those four
  packages, pinned to the advisory minimums (pypdf 6.21.4, soupsieve 4.0) per
  the round-6 policy of minimal conflict surface. `playwright` 1.64.0 → 1.65.2
  moves as uv's own resolution side effect of touching the graph (re-run
  `uv lock --upgrade-package …` reproduces the same 1.65.2 landing; neither
  pip-audit nor trivy flags 1.64.0).
- **Proof (scanner-faithful):** trivy v0.73.0 (the gate's pinned version,
  DB 2026-11-16 07:10 — *fresher* than the failing job's 06:33 DB) against
  old/new version fixtures via `trivy rootfs --severity HIGH,CRITICAL
  --ignore-unfixed`: old fixture → exactly the 13 CI findings, byte-for-byte
  (same CVE IDs, same fixed versions); new fixture → 0 findings. pip-audit on
  the `uv sync --locked --all-extras` env (the pip-audit gate's own shape)
  → only the triaged `ecdsa==0.19.2 PYSEC-2026-1325`; `pip_audit_gate.py`
  exit 0.

### The grype cross-check's next reds, pre-empted with evidence

The failing job died before its grype step ran, so the gate would have failed
again on the next run even with the lock fixed. Verified with the gate's exact
pinned tools (grype v0.116.0, sha256-checked, `--only-fixed --fail-on high`):

1. **`python:3.13.16-slim-bookworm@sha256:73aa5fae…`** (the registered
   contract digest powering both the engine image and the Conductor pybuild
   stage): grype exit 2 — **CVE-2026-115557, Critical, python 3.13.16
   binary, fixed 3.13.18** — plus libssl3/openssl/apt HIGHs
   (CVE-2026-84782, CVE-2026-109518, fixed 3.0.22-1~deb12u2 / 2.6.2).
   The refreshed **`python:3.13.18-slim-bookworm@sha256:a5a7017e…`**: grype
   exit 0 (only Medium/Low python-binary advisories remain, below the gate's
   high threshold). Digest verified against the registry manifest list before
   use (`docker buildx imagetools inspect`: tag resolves to this exact
   digest).
2. **`python:3.12-slim@sha256:a0f57064…`** (research/RSI/e2e/sbx bases):
   resolves to **CPython 3.12.15 on Debian 13.7 (trixie)**; grype exit 2 —
   the same **CVE-2026-115557 Critical on the 3.12.15 binary (fixed
   3.12.16)** plus trixie apt/zlib HIGHs. The refreshed
   **`python:3.12.16-slim-bookworm@sha256:935c3c5b…`** (registry-verified):
   grype exit 0. Moving the pin from the floating tag to the exact patch tag
   also returns these images to bookworm, keeping the bookworm-scoped
   `.trivyignore.yaml` triage prose (brotli CVE-2026-111497 entries) true.
3. **docker CLI vendor tree (root `Dockerfile` and `Dockerfile.research`
   `dockerclibuild` stages):** the round-6 overrides cover go-jose and
   x/net, but grype flags a third module — **GO-2026-6865, High,
   klauspost/compress v1.20.1, fixed v1.20.2** — in the stage built from
   head `76b145407` (trivy's DB does not carry this advisory yet; the CI
   log's own dockercli build downloads v1.20.1). Repair: add
   `KLAUSPOST_COMPRESS_FIXED_VERSION=v1.20.2` to the `go get` override set in
   both stages (release tag v29.9.1, commit pin dfc520d, go1.27.3 toolchain
   unchanged). Proof: both stages built locally — old (2 overrides) grype
   exit-flagged GO-2026-6865 High in the built binary; new (3 overrides)
   klauspost finding gone.

Every moved digest is registered as its own row update in
`quality/image-pins.json` (`recorded_in: "#2304"`), and every consumer of the
contract moved with it: the Dockerfile build smokes and security.yml probe
asserts now read `(3, 13, 18)`, the support matrix documents CPython 3.13.18,
`scripts/smoke-engine-canvas.sh`'s control image uses the new digest,
`tests/test_distribution_contract.py` pins both root-image FROM tags to
3.13.18, and `tests/test_hive_conductor_image_split.py` holds the pybuild row
and smoke pin. `tests/test_dockercli_vendored_cve_patch.py` asserts the third
override and its fixed version in both stages. No test counts changed
(assertions moved inside existing tests; suite inventory re-run: `tests/:
6058` unchanged, exit 0).

Round-7 validation battery (this tree, `uv sync --locked` envs):
`check-image-pins.py` exit 0; targeted suite `test_check_image_pins.py
test_hive_conductor_image_split.py test_dockercli_vendored_cve_patch.py
test_distribution_contract.py test_pinned_digest_references.py
test_devskim_scan_scope.py` → 82 passed; ruff check + format clean; suite
inventory ok (no delta); vulture ledger (CI's exact args) exit 0 at
1238 = 1238; release consistency ok (CHANGELOG Dependencies/Security entries
updated for this round's bumps and refresh); workflow inventory ok (32
workflows dispositioned); pip-audit gate (`--all-extras` env, gate-faithful)
exit 0; root suite in CI `test` job shape (`REQUIRE_AUTH=false
MAISTRO_DRY_RUN=1 pytest tests/ --ignore=tests/tools/registry -q`) → **5825
passed, 140 skipped, 0 failed in 7m50s**.

Residual: the four image builds behind `docker-build`/e2e/Gate C were not
taken through a full local `buildx` cycle this round (the contract-critical
pybuild change is `FROM` + smoke-assert constant only, with the venv build,
identity ARG pins and graft steps untouched, and the trivy/grype proofs above
run at scanner level); the e2e-ui rsi-polling-resilience flake documented in
round 6 remains maintainer scope.

### Round-7 addendum — the build-cycle gap this round *did* catch: the
### runtime-apt base itself

The salvage had refreshed the 3.13 and 3.12 pins but left the Conductor's
`runtime-apt` on the original `python:3.15.0-slim-bookworm@0e019bbd`. The
round-7 local build cycle caught it: grype v0.116.0 on the freshly built
hive-conductor image flags **CVE-2026-115557, Critical, python 3.15.0
binary, fixed 3.15.2** — the OS python of the 3.15 base stays in the final
image (only its pip is pruned), so the binary is scanned even though the app
runs on the grafted 3.13.18 build. The same build also showed apt
CVE-2026-109518 HIGH — a local stale-`apt`-layer artifact: the rebuild's fresh
`apt-get upgrade` installs 2.6.2 and the rescan is clean (CI's 06:33 scan of
the old image already showed debian 0).

**Repair executed:** `runtime-apt` moved to the registry-verified
`python:3.15.2-slim-bookworm@sha256:96599df8…` (manifest list inspected;
CPython 3.15.2, still Debian 12.15 bookworm so the graft's glibc assumption
holds; grype `--only-fixed --fail-on high` on the base itself: exit 0). The
ledger row, the Dockerfile stage comments, the split test and the CHANGELOG
moved with it. **Proof on the rebuilt image** (`docker build -f
packages/hive-conductor/Dockerfile --build-arg VITE_POC_MODE=pm
--build-arg VITE_BASE_PATH=/pm/ -t hive-conductor:round7 .`, exit 0 — the
build-time smoke `(3, 13, 18)` + identity pins + seed derivation pass inside
the build): trivy `--severity HIGH,CRITICAL --ignore-unfixed` → 0 findings;
grype `--only-fixed --fail-on high` → exit 0; built-image probes →
`sys.version_info[:3] == (3, 13, 18)` with `sys.executable` realpath
`/usr/local/bin/python3.13`, identity pins 2.12.2/21.0.0/1.6.2 +
`ConductorSeed` derivation + native coincurve import, base OS python reads
3.15.2 with apt installed 2.6.2; boot: `GET /health/ready` → 200
`{"ready":true,…}` with `CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1`.

This closes the loop the earlier rounds could not: the PR's own purpose
(Debian/CPython freshness of the 3.15 OS layer) now ships in a state both
scanners of the gate accept.

### Round 8 (2026-11-16, head `094944a81` tree) — the last red: the research image
### build dies at `playwright install chromium` (libatomic.so.1)

CI at `094944a81` (check runs captured 2026-11-16 ~12:58) is down to exactly
three red jobs, all one root cause: `Container scan + SBOM + cosign` (job
133267675340) and `docker-build` (job 133270207586) both fail building
`maistro-engine-research` — `Dockerfile.research:211`
`RUN python -m playwright install chromium` exits 127 with
`playwright/driver/node: error while loading shared libraries:
libatomic.so.1` — and `integration-scope` (job 133267675417) is purely
downstream (`docker-build is required by integration scope but concluded
failure`). Everything else at that head is green (Coverage, Gate C, Image
pins, all Quality pillars, e2e, e2e-ui, test, exact-debt-ledger).

**Root cause:** round 7's advisory-minimum lock bumps moved playwright
1.64.0 → 1.65.2. The 1.65.2 wheel's bundled Node driver (v26.13.1) links
`libatomic.so.1`; the 1.64.0 driver does not (`ldd` on both wheels, run
locally). `production-apt`'s Chromium-stack apt list names no package that
pulls `libatomic1` transitively, and the slim base doesn't carry it — so the
first execution of the driver dies before the browser downloads. This also
corrects the round-6 reading quoted in earlier findings: the `npm audit fix`
block in job 133128530798's log was informational stderr from a *succeeded*
`npm ci` (`#29 … 7 moderate severity vulnerabilities` → the frontend build
continued at `#47 RUN npm run build`); round 6's actual blocker was the
trivy python-pkg reds on the research scan (oauthlib, pyasn1, pypdf,
soupsieve), which round 7's bumps fix — the current lock reads oauthlib
4.0.1, pyasn1 0.6.5, pypdf 6.21.4, soupsieve 4.0.

**Repair executed:** `Dockerfile.research` names `libatomic1` explicitly in
the `production-apt` install list — the same "installed explicitly, not left
to dependency resolution" posture as the libbrotli1 entry above it — with the
header comment documenting the playwright-driver linkage and the CI evidence.
`tests/test_research_image_playwright_runtime.py` (new, +2 tests,
`docs/testing/inventory-notes/2304-research-image-playwright-libatomic.md`)
holds the package in the stage and the playwright-in-lock ⇒ libatomic1
coupling closed; the regression test fails against the pre-fix Dockerfile
(the exact state that shipped the exit-127 CI failures) and passes on the
worktree.

**Proof on rebuilt images (local `docker build`, 2026-11-16):**

- `docker build -f Dockerfile.research` → exit 0; the previously failing step
  downloads Chromium 159.0.8154.6 / FFmpeg / headless shell; image exports.
- In-image probes: `libatomic.so.1 => /lib/x86_64-linux-gnu/libatomic.so.1`
  in the driver's `ldd`; `node --version` → v26.13.1 (exit 0);
  `playwright --version` → 1.65.2; `sys.version_info[:3] == (3, 12, 16)`;
  `libatomic1 12.2.0-14+deb12u1` present via dpkg.
- The gate's own reconcile step:
  `check-image-lock-reconciliation.py` → OK (147 distributions = the locked
  set) for research; same step for a locally rebuilt `hive-conductor` → OK
  (73 distributions), with the build-time smoke `(3, 13, 18)` passing inside
  its pybuild stage.
- Trivy 0.73.0 (CI version; HIGH/CRITICAL, `--ignore-unfixed`, repo
  `.trivyignore.yaml`) on the rebuilt research image → exit 0, zero
  findings; same scan on the rebuilt hive-conductor image → exit 0, zero
  rows (its `python:3.15.2-slim-bookworm` runtime base and CPython 3.13.18
  venv had no completed CI scan at round 7 — the gate died at the research
  build first).

**Coverage of the other images:** `maistro-engine` and the observability
variant built green in CI at `094944a81` in both red jobs before the research
build failed; their round-7 deltas are scan-improving (vendored docker-cli CVE
patches, patched-toolchain build). `Dockerfile.rsi-runner`'s only delta is the
same `python:3.12.16-slim-bookworm` digest the research build exercises above,
and it ships no playwright. `check-image-pins.py` stays exit 0 (no new base).

**Residual:** grype was not re-run by this round on the rebuilt research
image (trivy is green on the exact bytes; round 7 ran grype clean on the
rebuilt hive image and refreshed both 3.12 bases to the registry-verified
digest that fixes grype's CVE-2026-115557 Critical); engine/rsi-runner scans
not re-run locally. The next CI run of the gate re-executes both scanners on
all four images against these bytes.

## Round 9 (2026-11-16, head `89534e50` tree) — the residual grype reds were
## the drivers' bundled Node binaries; the image now ships a pinned system
## Node instead

The prior run committed the Node swap (`89534e50`) but died before emitting
any result, leaving the commit unverified and undocumented. This round
re-proved it end to end at the exact head, corrected its comment (it claimed
"both ship a bundled Node 24.21.0"; measurement shows playwright 1.65.2
bundles **v26.13.1** and patchright 1.64.1 bundles **v24.21.0**), and held
the repair closed with tests.

**Finding:** grype v0.116.0 flags the Node binaries the research image's
venv ships *inside the wheels* — playwright 1.65.2's bundled Node v26.13.1
and patchright 1.64.1's bundled Node v24.21.0 — including CVE-2026-111497
(Critical) and CVE-2026-105482/105483/106069 (High) on the v24.21.0 build,
all fixed upstream in Node 24.22.1. Both drivers are JavaScript launched
through Node, and both playwright and patchright consult
`PLAYWRIGHT_NODEJS_PATH` before their bundled `driver/node`
(`playwright/_impl/_driver.py` / `patchright/_impl/_driver.py`, read from
the locked wheels), so the vulnerable binaries can simply not ship.

**Repair (from `89534e50`, comment corrected here):** `Dockerfile.research`
downloads the Node 24.22.1 tarball over `urllib` with a sha256 literal
verified against nodejs.org this round (match), extracts to `/usr/local`,
sets `PLAYWRIGHT_NODEJS_PATH=/usr/local/bin/node`, deletes
`{playwright,patchright}/driver/node`, and prunes npm's vendored tree
(nothing in the image uses npm at runtime; its bundled dependencies are pure
scan surface). corepack stays: the scans show no findings from it.

**Proof (this round, scanners with the gate's exact pinned versions):**

- Full build `docker build -f Dockerfile.research --no-cache-filter
  production-apt --load .` → exit 0 (the previously-failing playwright
  step downloads Chromium 159.0.8154.6; the node swap steps execute).
- trivy 0.73.0, CI's exact shape (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml`) → **exit 0, zero
  findings** on `maistro-engine-research:round9`.
- grype 0.116.0, CI's exact shape (`--fail-on high --only-fixed`) →
  **exit 0**; the node rows are gone (remaining rows are Medium/Low/
  Unknown python-binary and otel-go-module advisories, below the high
  threshold).
- In-image probes as shipped (uid 10001, no extra env): `node --version`
  → v24.22.1 at `/usr/local/bin/node`; `find / -name node -type f` → only
  `/usr/local/bin/node` (no bundled driver binaries, no npm tree);
  `playwright.sync_api` launches Chromium, navigates a data: URL and
  returns the page title — the driver runs on the system Node.
- Patchright's driver likewise *starts* on the system Node; its launch
  error is a pre-existing browser-revision gap (it wants
  `chromium_headless_shell-1248`; the Dockerfile has only ever run
  `playwright install chromium`, which fetches 1255). No production code
  imports patchright (`grep -rn patchright packages/ --include='*.py'` →
  nothing outside tests), so nothing regressed.
- Tarball integrity re-checked from this machine: sha256 of
  `node-v24.22.1-linux-x64.tar.xz` matches the Dockerfile literal
  (`6c172a9a…95e6`).

**Held closed:** `tests/test_research_image_playwright_runtime.py` +3 tests
(note `2304-research-image-driver-node-runtime`, `tests/: +3`): the direct
regression (pinned URL + sha256 literal + `PLAYWRIGHT_NODEJS_PATH` + both
driver-node removals + npm prune present), checksum verification (the
downloader must assert the digest before extracting), and the coupling
(playwright in the lock ⇒ the swap block exists). All three demonstrated to
fail against the pre-round-9 Dockerfile by running the module against a
copy with the swap block stripped.

**Gate mapping:** this closes the grype leg of `Container scan + SBOM +
cosign` for the research image — the gate's last red scanner finding class
after rounds 6–8 cleared trivy python-pkg, gobinary, and the base CVEs.
Round 8's residual (grype not re-run on the rebuilt research image) is now
closed by execution: the rebuilt image scans clean under both scanners.

**Residual:** CI has not yet run on this head; the other three images were
green through the research build in the round-8 CI run and their bytes are
unchanged by the Node swap except where noted (root `Dockerfile` untouched
this round). The e2e-ui rsi-polling-resilience flake documented in round 6
remains maintainer scope.

## Round 10 — develop-sync merge (8cd840ab) re-points the dockercli repair at CR1373's v29.9.3

The in-place merge of origin/develop (157c3f61, M1-E2 + CR1373 base-pin
refresh) replaced the `dockerclibuild` stages' three-module override recipe
(docker/cli v29.9.1 + `go-jose@`/`x/net@`/`klauspost@` `go get` overrides)
with the CR1373 refresh: docker/cli **v29.9.3** (commit `5457199`), whose
upstream vendor tree already carries go-jose v4.1.7 (≥ the CVE-2026-116587
fix) and klauspost/compress v1.20.2 (the GO-2026-6865 fix), leaving only the
**x/net v0.62.0 override** load-bearing (v29.9.3 upstream still vendors the
CVE-2026-78661-vulnerable v0.60.0 — verified against the stage comment and
kept under test). The committed `tests/test_dockercli_vendored_cve_patch.py`
still asserted the superseded recipe and **failed at the merged head**
(demonstrated: `git show HEAD:…` run from the merged tree → 2 failed of 4:
`test_every_docker_cli_stage_overrides_both_vulnerable_modules`,
`test_override_versions_are_the_trivy_reported_fixed_versions` — exactly the
two encoding the v29.9.1 mechanism).

**Repair (this round's commit):** the test module was rewritten to assert the
same CVE posture through the new mechanism — tag+commit pin (binds the
vendor-tree facts to the exact release; a silent tag move fails), the x/net
override at the CVE-2026-78661 fix, re-vendor + `-mod=vendor`, and the
engine/research stage-sync. 5 tests, +1 node ID vs the old 4; inventory note
`2304-dockercli-vendored-cve-patch.md` updated to `tests/: +5` and
`scripts/check-suite-inventory.py` green (21 suites match).

**Local validation at head 07887c3bec (this machine):**
- ruff check / ruff format --check: green.
- Branch test modules (`test_dockercli_vendored_cve_patch`,
  `test_hive_conductor_image_split`, `test_research_image_playwright_runtime`,
  `test_devskim_scan_scope`, `test_distribution_contract`): 42 passed.
- `scripts/check-image-pins.py`: 10 pinned images, all registered — green.
- `scripts/check-radon-baseline.py` (base 157c3f61): 126 = 126 — green.
- `scripts/check-execution-lifecycles.py`: 19/19 classified — green.
- `mypy --strict packages/maistro-core/src` (bootstrap installed editable to
  match CI's `--all-extras`): 839 files, no issues — green.
- Root suite, CI's exact scope (`pytest tests/ --ignore=tests/tools/registry`,
  REQUIRE_AUTH=false MAISTRO_DRY_RUN=1): **5832 passed, 139 skipped**, 8m55s.
- `hive-conductor-e2e` (CI's compose command, image built from this branch's
  Dockerfile): exit 0, 10 passed / 13 skipped.
- `hive-conductor-e2e-ui` (CI's compose command): exit 0, **243 passed** (7.1m).
- Trivy 0.73.0 (gate version), HIGH/CRITICAL, `--exit-code 1`,
  `--ignore-unfixed`, `.trivyignore.yaml`, on the freshly built conductor
  image (`hive-conductor-hive:latest` from the compose build): **exit 0**.
- In-image probe (gate's identity contract, venv interpreter of record):
  python 3.13.18, bip-utils/coincurve/pynacl pins hold, ConductorSeed
  did:key operational — exit 0.
- Canvas frontend `npm audit --audit-level=high` (the round-6 red's shape):
  3 moderate, exit 0 — below the high threshold.
- integration-scope classification (`ci_merge_group_scope.py` +
  `check-integration-scope.py` on this branch's changed paths): resolves to
  {docker_build, durable_events, hive_e2e, object_storage, postgres,
  strike_ladder, wheel_imports} → required set as expected, no drift.

**Residual (not locally reproducible, unchanged by this round's salvage):**
the full container-scan matrix (engine/research/rsi images' trivy+grype+SBOM
+cosign — the merged dockercli stage is develop's own CR1373 change, proven
on develop's CI; rounds 8–9 hold the pre-merge local proofs for the rest),
the coverage producers (MinIO/Postgres service legs), Gate C clean install,
the formal/ hypothesis suite, and the postgres/strike-ladder/wheel-imports/
durable-events specialized legs. None of these consumes a file this round's
commit touches.

## Round 11 — develop-sync merge of origin/develop (a660bc2a9): resolve the
## graft×tz-Dockerfile and devskim-glob conflicts in place

origin/develop moved two commits past this branch's last sync
(f927334a2): 202bcf3383 (M1-B2b #2355, reclaim-attempt RECOVERED cause —
touches `tests/test_devskim_scan_scope.py`) and a660bc2a9 (M1 closeout #290,
scheduler tz database in the shipped image — touches
`packages/hive-conductor/Dockerfile`, `packages/hive-conductor/tests/Dockerfile`,
`scripts/check-image-pins.py`, `tests/test_check_image_pins.py`,
`docker-compose.test.yml`, `uv.lock`). Both overlap files this branch owns, so
the sync was merged in place (the branch's established pattern) with two
content conflicts:

1. `packages/hive-conductor/Dockerfile` (final stage): develop's #290 adds
   `PYTHONTZPATH=/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo` to
   the ENV block; this branch's base split grafts pybuild's CPython 3.13
   (binary + libpython + stdlib) into the 3.15.2 runtime-apt base.
   **Resolution keeps both**: the PYTHONTZPATH env points at the venv's
   tzdata wheel — the venv is 3.13 in both designs (pybuild 3.13.18 keeps
   being the contract interpreter), so develop's tz contract and this
   branch's graft are complementary, not competing. The pybuild stage's
   `tzdata==2026.3` pin and the build-time tz smoke auto-merged unchanged;
   the tz smoke now runs on the grafted interpreter (PATH resolves
   /app/venv/bin/python3.13 → grafted binary), which the compose build below
   exercises for real.
2. `tests/test_devskim_scan_scope.py`: the branch's ef46c0ad8d (parse-once
   via `lru_cache(maxsize=1)` + `list`) and develop's #290-era rewrite
   (parse-once via `@cache` + immutable `tuple`) are the same optimization;
   **resolution takes develop's canonical form** (stronger: tuples enforce
   the no-mutation rule the branch's docstring only asked for). The branch's
   structural parse-once test merged unchanged and works against `@cache`
   (`cache_clear` exists on both decorators).

No new tests were added by this round, so no new inventory note is required:
the merged tree's suite inventory (including develop's own 290-*/p2a-* notes
for develop's tests) reconciles green, see below.

**Local validation at the resolved merge tree (this machine):**
- `uv sync --locked --extra dev` and `--all-extras` (+ maistro-evolve
  editable, CI-exact): green — the auto-merged `uv.lock` resolves.
- ruff check / ruff format --check: green.
- Focused merged-seam tests (resolved devskim file, develop's expanded
  `test_check_image_pins` + `test_prepull_base_images`, branch's
  dockercli/image-split/playwright modules): **105 passed**.
- `scripts/check-suite-inventory.py`: **21 suites match** (develop's new
  tests arrive with develop's own notes; branch notes compose).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact args): 1236 = 1236 — green.
- `scripts/check-image-pins.py`: 10 pinned images, all registered — green.
- `scripts/check-compose-secrets.py`: 9 tracked compose files clean.
- develop's core/backend seam tests: reclaim/lease + spine conformance
  **316 passed**, scheduler-tz/degraded/canonical-admission **41 passed**.
- Root suite, CI's exact scope (`pytest tests/ --ignore=tests/tools/registry`,
  REQUIRE_AUTH=false MAISTRO_DRY_RUN=1): **5835 passed, 140 skipped**, 7m10s.
- Backend + design + ext-harness + ext-sdk suites: **5266 passed, 30 skipped**.
- `mypy --strict packages/maistro-core/src` (CI-exact env): **842 files,
  no issues** — develop's core changes typecheck on the merged tree.
- integration-scope classification (CI-exact base a660bc2a9): changed set is
  exactly this branch's 20 PR files; required legs
  {docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui,
  object storage, postgres ×2, strike-ladder, wheel-imports} — no drift.
- **hive-conductor-e2e, CI-exact, on the merged image** (compose up --build
  from the merged Dockerfile + merged docker-compose.test.yml): phase 1
  **14 passed / 14 skipped** — including all of develop's #290 container
  timezone proofs (UTC/Berlin persistence, wall-time & DST offsets,
  invalid-zone 422, tz-database health) running against the base-split
  graft image; restart phase: hive restarted → healthy →
  `test_restart_recovery_preserves_schedules_and_recomputes_next_run`
  **1 passed**. This is the direct proof that the graft×PYTHONTZPATH
  conflict resolution builds and behaves: the tzdata wheel is present in
  the grafted-3.13 venv, the tz smoke passed at build time, and the
  scheduler reads zones through the deliberate wheel source in the 3.15.2
  OS-layer image.
- Trivy 0.73.0 (gate version), HIGH/CRITICAL, `--exit-code 1`,
  `--ignore-unfixed`, `.trivyignore.yaml`, on the freshly built merged
  conductor image (`hive-conductor-hive:latest`): **exit 0** — the new
  `tzdata==2026.3` wheel introduces no finding.
- Grype 0.116.0 (gate version), `--fail-on high --only-fixed` on the same
  image: **exit 0** — only Medium/Low advisories whose fixes land in future
  CPython releases (3.15.0a6/3.16.0), the posture rounds 7–9 recorded.

**Residual (CI-proven at a8b50f0839, not locally re-run):** hive-conductor-
e2e-ui (develop's pm-workflow spec changes against this branch's image —
the compose+image seam it depends on is proven above), Gate C, the coverage
service legs, and the specialized postgres/strike-ladder/wheel-imports/
durable-events legs; the engine/research/rsi image scans (no file this round
touches enters those images).

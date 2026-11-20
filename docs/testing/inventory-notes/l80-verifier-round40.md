---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-core/tests: +0
---

# L80 verifier round 40 — independent re-verification at f6839657e0; SECURITY.md M2-B5 evidence chain reconciled onto the M2-B1 architecture; seed symlink boundary pinned (+1 test, own note)

Head under validation: `f6839657e080` (round-39 note's commit, clean tree).
Base: `f927334a2e` (M2-B1, = origin/develop — `git merge-base HEAD
origin/develop` re-confirmed equal to origin/develop, so the carried
develop-sync block stays resolved; origin/develop has not moved).

## 1. Round-39 claims re-verified independently (this job's driver ran no checks — empty `checks: []`, no `check-*.log` files; the immediately prior job `8f32f833` died on a provider error before doing anything)

- `uv run pytest packages/maistro-core/tests/sandbox/ -q` → **248 passed,
  38 skipped** (skips = live-backend opt-ins, by design).
- `uv run pytest packages/maistro-bootstrap/tests -q` → **277 passed,
  2 skipped** (Windows-only escape proof + opt-in rootless lane test).
- `uv run pytest tests/test_distribution_contract.py
  tests/test_unit_suite_execution_partition.py tests/test_devskim_scan_scope.py
  -q` → **33 passed**.
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .`
  → 3570 files already formatted.
- CI-exact vulture: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **RC=0**
  (1236 = 1236, balanced against base f927334a). No ledger amendment.
- Gate scripts RC=0: `check-image-pins.py`, `check-test-duplicates.py`,
  `check-branch-protection.py`, `check-required-checks.py`,
  `check-image-inventory.py`, `check-workflow-inventory.py`,
  `check-workflow-write-safety.py`, `check-ac-state.py`,
  `check-security-inventory.py`. `bash -n scripts/ci-rootless-mountns.sh` →
  syntax OK.
- `check-suite-inventory.py` (bootstrap suite): expected **319** (318
  CI-expected + this round's recorded +1), collected **279** — the same −40
  environmental gap round 39 proved reproduces identically on untouched
  origin/develop; this round's delta moves both sides by exactly one. Not a
  regression; CI's runner collects the full suite (last merge-queue
  evaluation green).

## 2. Actual finding repaired: SECURITY.md §8 cited evidence deleted by the M2-B1 merge

The M2-B5 paragraph (branch-added) still described the pre-merge Docker-backed
suite: "attacks against real containers", "the suite refuses a daemon where
container root maps to host root", "the writable surface is pinned down to
`/workspace` and `/tmp`". All three describe tests the M2-B1 reconciliation
deleted (`cr1450-develop-sync-m2b1-reconciliation.md` records the replacement:
the fail-closed `NoSuitableBackendError` selector proof is "the merged
architecture's replacement for the deleted rootful-daemon refusal test").
Against an issue whose acceptance includes "SECURITY.md can cite conformance
evidence for the real backend", the citation had drifted from reachable
behavior. Rewritten (no inventory/counted claims touched;
`check-security-inventory.py` RC=0): the paragraph now names the actual
evidence chain — fail-closed selector refusal proven in CI's
`sandbox-conformance` lane, the rootless-daemon image contract (non-root uid,
`--network=none`, enforced `--memory`), the production adapter suite
(`test_container_sandbox.py`, stub-backed everywhere + Kata-host live lane),
and the kernel-level conformance/escape coverage in
`packages/maistro-core/tests/sandbox/` executed by quality.yml's
`coverage (no services)` producer (bubblewrap installed; the five-suite
partition's only executor).

## 3. Second gap repaired: "unrelated host secrets" seeding criterion lost its test in the merge

The M2-B1 merge replaced the index-driven seed — and the indexed-path
hardening plus sentinel tests of `l80-seed-path-replacement.md` — with a plain
host-side `tar` traversal. That traversal is structurally safe (tar archives
a symlink as a symlink; nothing beneath it becomes an archive entry), but
nothing pinned that property anymore: the acceptance criterion's "unrelated
host secrets" half was untested. New test:
`test_container_sandbox.py::
test_seed_never_materializes_what_a_worktree_symlink_points_at` — production
seed path, real tar, asserts both a directory symlink and a leaf symlink
arrive in the seed as symlinks (`stat.S_ISLNK`), never materialized. Teeth
proven in a scratch reproduction: production layout passes; a dereferencing
seed (`tar -h`, the `copytree(symlinks=False)` equivalent) materializes the
external sentinel as DIR/REG and fails the assertions. Details and delta in
`m2-b5-seed-symlink-boundary.md` (bootstrap +1).

## 4. M2-B5 acceptance mapping (all evidence reachable at this head)

- **Escape suite covers filesystem / process / namespace / network / device /
  host-socket / credential / privilege**: `test_escape_conformance.py`
  (kernel-backed where bwrap builds a namespace; flag assertions everywhere),
  `test_kata_live_conformance.py` (same surfaces against the selected vm tier),
  `TestOnAKataHost` in `test_container_sandbox.py`. ✔
- **Network/credential default-deny proven**: `test_network_default_deny.py`
  (empty namespace; scoped grants refused, not approximated),
  `test_credential_boundary.py` (construction-level: ambient env never read),
  `TestOnAKataHost.test_agent_commands_cannot_reach_any_network_by_default`,
  CI image contract with `--network=none`. ✔
- **Seed receives no `.env` / `.git` / unrelated host secrets**:
  `test_seed_leaves_ambient_credentials_on_the_host` (denylist at any depth,
  `.git/config`+`hooks` excluded while `HEAD` survives) + the new symlink
  materialization test. ✔
- **Untrusted work not container root**: Kata live conformance asserts
  `CapEff:0` + `NoNewPrivs:1`; bwrap escape conformance
  `test_every_capability_is_dropped` / setuid cannot escalate; CI lane runs
  the image as uid 65532 non-root. ✔
- **Writable scope minimized/read-only by default**:
  `test_the_only_writable_host_path_is_the_workdir` + read-only runtime dirs
  (bwrap); Kata live denies host paths/sockets. ✔
- **Timeout/kill/cleanup + resource exhaustion**:
  memory budget becomes real cgroup limit, memory hog refused, busy loop
  killed, output bounded, `test_a_timeout_leaves_nothing_running`,
  setsid grandchild cannot outlive the timeout, destroy removes the workdir. ✔
- **CI / designated conformance lane runs the suite**: quality.yml
  `coverage (no services)` (bubblewrap + AppArmor relaxation + pre-pulled
  image; sole executor of the partition) and ci.yml `sandbox-conformance`
  (fail-closed proof + rootless userns daemon + image contract). ✔
- **SECURITY.md cites conformance evidence for the real backend**: §8
  paragraph rewritten this round to the reachable evidence chain. ✔
- **Conformance instantiates the production `ContainerBuilderSandbox` /
  supported backend, not a separate fixture**:
  `test_container_sandbox.py` drives the production adapter (production path
  pinned to `build_selector` by
  `test_production_path_uses_the_canonical_build_selector`); Kata live
  conformance selects via `build_selector` on the evidenced profile. ✔

No production code changed this round. Changed: `SECURITY.md`,
`test_container_sandbox.py` (+1 test), two inventory notes.

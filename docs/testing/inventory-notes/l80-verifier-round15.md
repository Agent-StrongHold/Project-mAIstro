---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 15 (independent review) — develop-sync head `5449b1406`

Re-review after the develop merge `730857f1c1` into `auto-80`. The verified
head for this record is exactly `5449b1406cf48660de518c5a036aa5105935862b`.

## Prior findings resolved at this head (re-executed, not assumed)

- **Vulture baseline (round-14 finding at `40b051af`)**: the exact CI-scoped
  command both call sites run — `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exits **0**
  at this head (1404 == 1404, unclassified 0, base `730857f1c1b9`, candidate
  `5449b1406cf4`). The 60 previously-unbanked identities are vendored
  `third_party/` sources, excluded by the flag now present at
  `.github/workflows/quality.yml:836-843` and
  `.github/workflows/vulture-ratchet.yml:80-86`.
- **CI execution**: live `gh pr view 1450` refresh at this head — 0 failures;
  `exact-debt-ledger` (Vulture Ratchet) COMPLETED/SUCCESS at `5449b1406cf4`;
  17 checks SUCCESS, 9 IN_PROGRESS, 3 QUEUED, 1 SKIPPED. The conformance/test
  jobs were still running at review time, so GitHub-side conformance execution
  remains UNVERIFIED by policy; every command they run is proven green locally
  at the exact head (below).

## Develop-merge drift check

`git diff 66dee91a..HEAD` over the sandbox/security surfaces
(`packages/maistro-bootstrap`, `packages/maistro-rsi`,
`packages/maistro-core/tests/sandbox`, `SECURITY.md`,
`.github/workflows/ci.yml`, `quality/`) touches **no #80 code or evidence** —
only foreign-lane inventory notes and quality JSON landed with develop.

## Acceptance re-validation at this head (executed live)

- `pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q`
  (Docker 29.7.2) → **33 passed, 0 skipped**: filesystem escape
  (`test_path_escape_blocked`), network default-deny (live
  `NetworkMode == none` inspect + egress probe asserting DENIED for
  1.1.1.1/IPv6/169.254.169.254/10.0.0.1 and DNS, with per-path probed
  assertions), credential default-deny (HOME-only env + 10 proxy spellings
  blank), seed exclusion of indexed `.env`/`.env.*`/`.envrc` under a split
  index plus untracked host secrets and `*.pem` at depth
  (`test_seed_leaves_ambient_credentials_on_the_host`), non-root exec
  (uid pinned; `/etc` write and `chown` refused; single justified root exec =
  pre-seed chown of the empty workspace, `container_sandbox.py:244-251`),
  read-only rootfs with live `/proc/mounts` enumeration (only `/workspace` and
  `/tmp` writable; `/dev/shm` + `/dev/mqueue` pinned RO), namespace/kernel/
  device/host-socket probes (PID-ns isolation, mount/chroot/mknod refused,
  `/dev/kvm` and both docker.sock paths absent, `CapEff` empty,
  `NoNewPrivs=1`), timeout kill incl. detached descendants, context cleanup,
  and memory-limit containment.
- `pytest packages/maistro-core/tests/sandbox/test_escape_conformance.py -q
  -rs` → 4 passed, 24 skipped fail-closed ("this host cannot build a
  bubblewrap sandbox"); the CI lane installs bubblewrap and relaxes the
  apparmor userns restriction to execute those kernel assertions
  (`.github/workflows/ci.yml:441-452`).
- `uv run python scripts/check-security-inventory.py` → exit 0 (60 cited
  paths resolve, 23 rows match); SECURITY.md:324-339 cites both suites.
- Production parity: tests import `ContainerBuilderSandbox` from
  `maistro_bootstrap.builders.container_sandbox` (test
  `test_container_sandbox.py:21-27`); production callers unchanged
  (`maistro_rsi/local_loop.py:804-806`,
  `maistro_rsi/contained_validation.py:73-80`); CI builds the same production
  image from the tests-only context and runs the same test file
  (`ci.yml:466-474`).
- Driver checks at this head: `uv sync`, `ruff check .`, `ruff format
  --check .`, the 33-test run above, and both suite inventories
  (maistro-bootstrap 249, maistro-rsi 793) — all green.
- Closure keywords: branch commits `730857f1c1..HEAD` and the live PR body
  scanned — none (body says "Refs #80" only).

Residual: GitHub-side completion of the conformance/test jobs at this head
remains UNVERIFIED by policy (IN_PROGRESS at review time, not advanceable
from this environment).

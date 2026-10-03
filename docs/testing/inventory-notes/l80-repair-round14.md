---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 repair round 14 — verifier vulture finding is a third-time invocation-scope artifact; CI-scoped gate exits 0 at exact head; full live battery re-proven

Verifier job `5534861ca96a41dfa1b5b2edae04ae99` (head `40b051afa52624fc9c205c3cd2058fe3abc33439`,
base `20e6cd4a7f8b57273fa090b5afe9f2c39a9fb923`) returned NEEDS-REPAIR. This
round re-derived the single failed-command finding from primary evidence at
the same head and re-ran the full live conformance battery. No code delta was
warranted: the tree at the exact head is unchanged and every gate is green.

## Finding 1 — "check-vulture-baseline.py exited 1; 1464 vs 1404, 60 unbanked": the command run is not the CI command

The verifier executed:

    uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60

Both CI invocation sites run a strictly narrower, documented scope:

- `.github/workflows/quality.yml:837-843` — `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
- `.github/workflows/vulture-ratchet.yml:81-86` — identical argv

The exclusion is deliberate policy (quality.yml comment block, lines ~826-836):
`third_party/` is vendored upstream source (Google's IFEval verifier, BFCL's
AST checker) kept byte-faithful; linting it "measures nothing we can act on".

Evidence at exact head `40b051afa526`:

- WITH the exclude (the CI argv): **exit 0 — 1404 reviewed identities ->
  1404 findings**, per-bucket summary printed, `unclassified: 0`,
  `never_allowlist: 0`.
- WITHOUT the exclude: exit 1 — but every unbanked identity location
  (44 unique `packages/...:line` paths deduplicated from the 60 findings)
  is under `packages/maistro-evolve/src/maistro_evolve/benchmarks/third_party/`;
  `grep -cv third_party` over the deduplicated list is **0**. No product
  identity is unbanked.

This is the third verifier round tripping over an invocation-scope variant of
the same gate (round 13 recorded the no-path-arguments variant). The gate as
CI actually invokes it is green at the exact head under test. No ledger
amendment and no dead-code fix are warranted: `quality/vulture-baseline.json`
is byte-identical to the develop base on this branch (`git diff
20e6cd4a..HEAD -- quality/vulture-baseline.json` is empty).

## Finding 2 — "CI QUEUED; CI execution at reviewed SHA UNVERIFIED": externally unreachable from this environment

GitHub Actions execution state cannot be advanced from here (no-push /
no-mutation rule). What CAN and was re-proven at the exact head is every
command that CI's conformance path runs (see battery below), plus the workflow
wiring itself:

- ci.yml:441-452 — bubblewrap installed and
  `kernel.apparmor_restrict_unprivileged_userns=0` set so the Tier-3 kernel
  assertions actually execute on the runner.
- ci.yml:468-474 — builds the real image from
  `packages/maistro-bootstrap/tests/Dockerfile.sandbox` (never the repo as
  build context) and runs `test_container_sandbox.py` against the production
  `ContainerBuilderSandbox`.
- ci.yml:475-476 — full `packages/maistro-bootstrap/tests` (includes the
  hardening suite) and `packages/maistro-core/tests` (includes
  `tests/sandbox/test_escape_conformance.py`).

## Acceptance battery re-run at this head (all fresh executions, freshly built image)

- Image rebuilt exactly as ci.yml:468-472: `docker build --tag
  maistro-builders:latest --file packages/maistro-bootstrap/tests/Dockerfile.sandbox
  packages/maistro-bootstrap/tests` → success (Docker server 29.7.2).
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -v` →
  **26 passed in 37.97s**, covering: filesystem isolation, path escape,
  network default-deny, non-root exec, ambient-credential seed denylist
  (`.env`, `.env.*`, `.envrc`, `.git`, id_rsa/`.ssh` classes), env
  credential default-deny (blanked Docker proxy variables, both case
  spellings), read-only rootfs with `/dev/shm` + `/dev/mqueue` tmpfs pinned
  read-only and `/proc/mounts`-enumerated writable scope (`/workspace`,
  `/tmp` only), process/namespace/device/host-socket unreachability,
  timeout kill incl. detached descendants, context cleanup, memory
  exhaustion containment, split-git-index seed allowlist, harness-refusal,
  gitdir-marker validation, create-flag pinning (--network=none, --user
  65532, read-only tmpfs), sole-root-exec (pre-seed chown only),
  host-side-tar seed allowlist+denylist, and cleanup on enter/seed failure
  at every transfer stage.
- `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py
  -q` → **7 passed in 0.55s**.
- `uv run pytest packages/maistro-core/tests/sandbox/test_escape_conformance.py
  -q` → 4 passed, 24 skipped; skip gate `requires_bwrap`
  (`detect_host_capabilities().supports("bubblewrap")`) and the probe's
  reason captured on this host: "bwrap: Creating new namespace failed:
  Resource temporarily unavailable" — a genuine host limitation under the
  probe's configured budgets (#1328 fail-closed contract), NOT a detector
  bug (a bare `bwrap --unshare-all true` succeeds here, but the production
  probe reproduces spawn conditions and the host cannot sustain them; the
  CI runner relaxes the apparmor restriction so the skipped assertions
  execute there, ci.yml:447-452).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0** (1404 == 1404).
- `uv run python scripts/check-security-inventory.py` → OK (60 cited paths,
  23 inventory rows match code, 2 counted claims recomputed).
- `uv run ruff check .` → clean; `uv run ruff format --check .` →
  "2590 files already formatted".
- Suite inventories: `scripts/check-suite-inventory.py` for
  `packages/maistro-bootstrap/tests` and `packages/maistro-rsi/tests` → ok.
- Conformance instantiates production: tests import and construct
  `ContainerBuilderSandbox` from `maistro_bootstrap.builders.container_sandbox`
  directly (test_container_sandbox.py:21,48,68,112,143...); no hardened
  fixture.
- Closure keywords: `git log 20e6cd4a..HEAD` scanned — no
  fixes/closes/resolves #80.
- SECURITY.md limitation #8 block (lines ~314-339) cites the production
  Docker backend's full escape-class coverage and the Bubblewrap lane.

Residual: GitHub CI execution at the PR head remains QUEUED and is not
advanceable from this environment; every command it runs is proven green
locally at the exact head.

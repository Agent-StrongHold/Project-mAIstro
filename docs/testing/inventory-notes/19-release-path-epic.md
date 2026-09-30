---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
---
# Issue #19 [EPIC M3-A] Reconcile and prove the release path

Validation-only lane: no tests were added or removed, so every suite delta is
zero. This note records the executed acceptance evidence for the epic's
locally reachable criteria at head `c5e070d97`, because the driver ran no
deterministic checks for this job (`checks: []` in the job manifest).

Executed evidence (all exit 0):

- `uv run python scripts/bump_version.py --check` — all 38 version sites agree
  on `0.9.0` (#83 lockstep metadata).
- `uv run python scripts/check-release-consistency.py` — "ok: released none,
  shipping 0.9.0, working toward 1.0.0"; VERSION/CHANGELOG/README/tags release
  story is one checked fact, per ADR-073126-c4e1 (#83, #90 truthfulness).
- `uv run pytest tests/test_release_guard.py -q` — 23 passed; the non-YAML
  logic of the publish path (`scripts/release_guard.py`,
  `scripts/release_notes.py`) is unit-proven (#84).
- Both `.github/workflows/release.yml` and `release-installer.yml` parse as
  valid YAML, and every `scripts/` file they reference exists
  (`bump_version.py`, `check-compliance.py`, `check-release-consistency.py`,
  `release_guard.py`, `release_notes.py`, `verify-wheel-imports.py`) (#84
  static verification; the workflows remain unexercised end-to-end by design
  until a real tag is pushed — stated in the workflow header).
- `uv run python scripts/check-branch-protection.py` — ruleset agrees with the
  workflows (18 required on `develop`, 30 on `main`); every PR check is
  required or explicitly advisory (#85 offline rules; live `--verify` needs an
  admin token and stays opt-in).
- `uv run python scripts/check-install-functions.py` — pass (#86 install
  surface); `shellcheck -S error scripts/install-maestro.sh` — clean.
- `uv run ruff check .` and `uv run ruff format --check .` — clean at this
  head.

Not provable in this lane (operational children, each tracked as its own
issue): a real tag-driven run of `release.yml` (#84 end-to-end), clean-machine
install on fresh hardware (#86), authenticated real-model Graph E2E (#87),
backup/restore proof (#88), RC soak and promotion (#89). The wizard
unification is child #443 with its own implementation lane.

## CI-repair round at `28dc96d92` (merge-queue evidence, not scanner guesses)

CI at this head failed two real gates; both were reproduced locally, fixed,
and re-proven:

- `test` job, step `npm audit --audit-level=high`
  (`packages/maistro-canvas/frontend`): reported `brace-expansion` 5.0.9
  (high, GHSA-q2hr-2g5m-vwhr / GHSA-qhr7-859c-m2p7 / GHSA-6j4f-fj2g-mc7p)
  and `ip-address` 10.7.0 (moderate). Both are transitive deps whose parents
  (`minimatch ^5.0.5`, `express-rate-limit ^10.2.0`) already admit fixed
  versions, so the fix is lock-only: brace-expansion -> 5.0.12,
  ip-address -> 10.7.2. Re-proven: `npm audit --audit-level=high` ->
  "found 0 vulnerabilities" (exit 0); `npm ci && npm run test:ci` -> 79
  passed; `npm run lint` -> 0 errors (13 pre-existing warnings, budget 13);
  `npm run build` -> ok.
- `security` job, step `python scripts/pip_audit_gate.py`: urllib3 2.7.0
  flagged by CVE-2026-97687/88/89 with fix 2.8.0 -> `uv lock
  --upgrade-package urllib3` (2.8.0). Re-proven with CI's exact recipe:
  `uv pip freeze` + `pip-audit --strict -r` + gate -> "pip-audit OK (1 known,
  all triaged in ALLOWED)"; only the reviewed ecdsa dispositions remain.
- vulture per-identity ledger (exact-debt-ledger): ran the named invocation
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) — 1402 findings, 0 unclassified, 0
  never-allowlist, ratchet stable base `c5e070d97d07` -> candidate. Zero
  unbanked identities, so the ledger is deliberately NOT amended.
- regression sweep after the bumps: `uv run ruff check .` /
  `ruff format --check .` clean; `uv run pytest packages/maistro-canvas/tests
  -x -q` 399 passed; `tests/test_release_guard.py` 23 passed;
  `tests/ --ignore=tests/tools/registry` 3219 passed with a transient local
  contention artifact (fixture errors that all pass on `--lf` re-run and that
  CI runs green at this head); `scripts/check-reachability.py` exit 0;
  `bump_version.py --check` and `check-release-consistency.py` still agree on
  0.9.0.

inventory-delta: still +0 (dependency lockfile repair only; no tests added or
removed).

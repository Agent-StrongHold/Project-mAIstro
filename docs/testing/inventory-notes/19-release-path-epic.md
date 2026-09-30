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

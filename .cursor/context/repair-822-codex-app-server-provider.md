# auto-822 lane notes (issue #822 — Codex App Server HarnessRunner provider)

Worktree `/home/dev/Git/wt/auto-822`, branch `auto-822`, base `fad17a87c34193a91c568eb8b0a910e8e6384ccd`.

## State at end of repair round

HEAD `f6a2b5de8` (on top of `b3f2fe727`). Worktree clean. Not pushed.

Branch surfaces (vs base): `capabilities/__init__.py`, `capabilities/providers/__init__.py`,
`capabilities/providers/codex_app_server.py` (new, 403 lines),
`tests/capabilities/test_codex_app_server_harness.py` (new, 33 tests),
`docs/security/HARNESS-SUPPORT-MATRIX.md`, `docs/testing/inventory-notes/auto-822-codex-app-server-provider.md`,
plus `uv.lock` (aiohttp 3.14.5 / yarl 1.25.1).

## Merge-queue blockers and what fixed them

1. **Diff coverage (publish-set floor + diff coverage).** `codex_app_server.py`
   was at 76.7% of 30 changed branch arcs (floor 80%). Six tests added for the
   closed legs: non-object create output, object create output without
   `session_id`, unparseable create output, raising create `exec`, blank and
   non-object stream lines. Now 28/30 branch arcs (93%), lines 127/129.
   The 3 remaining partials are the defensive `thread_id is None` (send) /
   `thread_id is None` (stream) / `thread_id is not None` (stop) guards — the
   public API cannot reach them (start_session always correlates before
   returning, and its failure path stops the session). Not worth white-box
   tests.
2. **Supply chain (pip-audit) + security.** `aiohttp==3.14.3` (transitive via
   `cosmic-ray`, not a direct pin) reported CVE-2026-111064 / CVE-2026-111063 /
   GHSA-2g87-pp6c-29x5. Fixed by `uv lock --upgrade-package aiohttp`. Only
   aiohttp + yarl rows change. **This advisory is also red on the develop base
   commit** — pre-existing debt, not branch-introduced; it lands here because
   the gate is in this lane's blocking set. `ecdsa==0.19.2 PYSEC-2026-1325` is
   the only remaining advisory and is in `scripts/pip_audit_gate.py` ALLOWED.
3. **Develop sync conflict.** Already resolved before this round (merge commit
   `b1fe63f00`); no conflict markers, `check-merge-markers.py` clean.

## Salvage note

`start_session` in `codex_app_server.py` carries a `try/except BaseException`
around the create `exec` that was **not authored in this round** — it appeared
in the worktree during the run (uncommitted, alongside a `git reset` reflog entry
at 22:43:44). Preserved per the salvage rule, verified correct (releases the
orphan sandbox/registry entry before propagating the original failure), and
covered by `test_create_exec_failure_releases_sandbox_and_propagates`.

## Reproduction commands (all `uv run` from the worktree)

    # diff coverage
    coverage run --branch --source=packages/maistro-core/src/maistro -m pytest \
      packages/maistro-core/tests/capabilities/test_codex_app_server_harness.py -q
    coverage xml -o /tmp/cov.xml
    python scripts/check-diff-coverage.py /tmp/cov.xml \
      --base fad17a87c34193a91c568eb8b0a910e8e6384ccd --branch-fail-under 80

    # pip-audit / security
    uv pip freeze --exclude-editable > /tmp/deps.txt
    pip-audit --strict --format=json -r /tmp/deps.txt > /tmp/pip-audit.json
    python scripts/pip_audit_gate.py /tmp/pip-audit.json

    # other gates that pass
    python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 \
      --exclude '*/third_party/*'   # 1321 -> 1321, never_allowlist 0
    python scripts/check-suite-inventory.py        # 21 suites match
    python scripts/check-dependency-namespaces.py  # no unreviewed namespaces
    python scripts/check-merge-markers.py          # ok

## Gotchas

- `uv run mypy packages/maistro-core/src` alone FAILS with 5 `maestro_bootstrap`
  import-not-found errors in `cli/_install.py` / `cli/_builders_tui.py`. That is
  an invocation artifact, not a defect: `maistro_bootstrap` is an optional
  workspace package that the CI mypy step lists explicitly. Use the CI argument
  list (`packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src
  packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src`)
  — that passes clean over 899 files.
- The full tree has ~34 pytest collection errors without all services up; scope
  pytest to `packages/maistro-core/tests` (or narrower).
- `pip-audit` is not in the lock; `uv sync` uninstalls it. Reinstall with
  `uv pip install pip-audit` before re-running the gate.

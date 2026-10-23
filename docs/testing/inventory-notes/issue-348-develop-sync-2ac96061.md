---
inventory-delta:
  tests/: +0
---
# issue-348-develop-sync-2ac96061

Validation round for #348 in worktree `auto-348` at head `e937e24734c9` —
the merge of develop `2ac9606142` (#1945 admission-generations work) into
the lane after the prior verify round concluded at `88e3344b0964`. No tests
were added or removed (`tests/:` is +0); this note records that the merge
left the #348 acceptance surface intact and re-proves the core criteria
against the merged tree, first-hand.

## Why no test delta

`git diff 88e3344b0..e937e2473` touches none of the lock-enforcement
surfaces: no Dockerfile, no `uv.lock` (byte-identical through the merge),
no `scripts/check-image-lock-reconciliation.py`, no
`.github/workflows/{security,ci}.yml`, none of
`tests/test_image_lock_contract.py` /
`tests/test_check_image_lock_reconciliation.py` /
`tests/test_check_license_inventory.py` / `tests/test_check_image_pins.py` /
`packages/maistro-rsi/tests/test_gate_evidence.py`. The merge's only
`quality/` deltas come from develop's own side
(`vulture-baseline.json` −5 rows, `ratchet-authorizations.json` +10) and
the branch's additive rows survived: `quality/license-policy.json` still
carries the `pkg:pypi/markdown-pdf@*` MIT resolution, and the
`direct-dependency-exceptions.json` / `image-pins.json` rows diff cleanly
against the develop base.

## Evidence (all executed first-hand at this head)

- `uv lock --check` clean (468 packages) — the merge introduced no lock
  drift.
- Built the real engine image from this tree:
  `docker build -f Dockerfile -t maistro-engine:pr-e937e247 .` → success;
  then ran security.yml's exact reconciliation:
  `uv export --locked --package maistro-server --extra image --no-dev
  --no-emit-workspace` + `scripts/check-image-lock-reconciliation.py
  --image maistro-engine:pr-e937e247 --expected-file … --member
  maistro-core==0.9.0 --member maistro-server==0.9.0 --member
  maistro-canvas==0.9.0` → `OK: … ships exactly the locked set (128
  distributions, incl. 3 workspace member(s))`, exit 0.
- The image ships the merged sources: `docker run --entrypoint python …
  -c "from maistro.tasks import admission_codec; import maistro,
  maistro_server, maistro_canvas"` → `shipped-code-ok` (the #1945 module
  develop added is present in the production image and imports).
- `uv run pytest tests/test_image_lock_contract.py
  tests/test_check_image_lock_reconciliation.py
  tests/test_check_license_inventory.py
  packages/maistro-rsi/tests/test_gate_evidence.py` → 169 passed.
- `uv run pytest tests/test_check_image_pins.py` → 38 passed.
- `uv run pytest packages/maistro-rsi/tests -q` → 1729 passed, 4 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` → clean
  (3470 files formatted).
- `scripts/check-merge-markers.py` → ok (no conflict markers in any
  tracked file).
- Merge-sensitive ratchets re-run at the merge head with CI's exact
  arguments: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0 (1309 reviewed identities → 1309
  findings); `check-radon-baseline.py` → exit 0 (128 → 128);
  `check-reachability.py` → exit 0 (157 unreachable, within tolerance);
  `check-promotion-surface.py` → ok.
- `scripts/check-suite-inventory.py` (full) → ok: 21 suites, 33892 unique
  test identities, 0 duplicates.

## Residual risks

- Hosted CI has run at parent `88e3344b0964`, not yet at this merge head;
  every file the ACs depend on is byte-identical across the two, and the
  merge head's own deterministic gates (above) are green. The GH006
  merge-queue block resolves when the updated branch re-enters the queue.
- `templates/autonoetic/Dockerfile.jinja:14` still uses a bare
  `pip install .` — Copier downstream product scaffold, not a repo-built
  production image; unchanged by this merge and out of #348's repo-build
  scope (previously recorded).

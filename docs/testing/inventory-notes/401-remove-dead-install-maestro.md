---
inventory-delta:
  tests/: +4
---
# Issue #401 — Remove the dead install-maestro.sh curl-pipe-bash placeholder

`scripts/install-maestro.sh` is gone (file deletion only; no Python source
packages touched) together with its references: the SPEC-180 out-of-scope
bullet now names the real remote-fetch owners (`get.sh` verifies the
downloaded `install.sh` against the published `SHA256SUMS` before executing
it; `get.ps1` boots WSL, hands off to `get.sh`, and forwards
`MAISTRO_SHA256SUMS_URL`), and `19-release-path-epic.md` gained an addendum
because its shellcheck line pointed at the removed file.

`tests/test_installer_entrypoints.py` pins the two properties whose loss
would recreate the defect: the dead script stays removed and the repo-root
product entrypoints are exactly `get.sh` / `get.ps1` / `install.sh`; and no
documented/executable installer path (the three entrypoints + `README.md` +
`docs/install/default-installer.md` + `docs/install/resolver-matrix.md` +
`maistro_bootstrap/plan.py`) contains a placeholder URL
(`https?://...<...>` slots or `<YOUR`/`YOUR_REPO`/`<org>`/`<ORG>` tokens).
The last case proves the detector against the literal removed content, not
only against the already-clean tree.

Executed evidence: `uv run pytest tests/test_installer_entrypoints.py -q` →
4 passed; the delta below was measured by
`check-suite-inventory.py --update` and the gate agrees in check mode.

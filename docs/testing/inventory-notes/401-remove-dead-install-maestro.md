---
inventory-delta:
  tests/: +5
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

## Salvage round at `41f5230c8` — generic unfilled-slot detector

The original token list (`<YOUR`, `<org>`, …) only caught the removed file's
exact spellings. The committed tree still carried the same defect class under
a renamed placeholder: `maistro_bootstrap/plan.py` generated the paste-verbatim
guidance `git clone <maistro-engine-url>`. Three changes, all proven before/after:

1. A generic `GENERIC_SLOT` detector (lowercase `<slot>` argument tokens,
   comment lines skipped, three notation slots allowlisted) joined the surface
   scan, and `test_slot_detector_catches_renamed_placeholders` proves the
   token list alone reports the renamed shape as clean — only the generic
   detector enforces the invariant.
2. `plan.py` now generates a paste-runnable default that reuses the one
   documented repo override (`get.sh` usage: `MAISTRO_REPO`, default
   `Agent-StrongHold/Project-mAIstro`) instead of an unfilled slot — and not
   an invented second env var for the same checkout.
3. The allowlist's legacy-key entry was widened to the literal install.sh
   shapes (`API_KEYS=[\"<secret>\"]`, `API_KEYS=[\"ops:<secret>\"]`, lines
   839–840); the first detector run failed on exactly those two lines until
   the pattern covered the `[...]` brackets.

Executed evidence: `uv run pytest tests/test_installer_entrypoints.py -q` →
5 passed; the detector run against `git show HEAD:…/plan.py` flags line 183
`<maistro-engine-url>` while the fixed tree is clean under the same scan;
`uv run pytest packages/maistro-bootstrap/tests -x -q` → 237 passed,
1 skipped; `uv run ruff check .` / `ruff format --check .` clean;
`scripts/check-install-functions.py` exit 0; `shellcheck --severity=warning
install.sh get.sh` clean (CI's exact invocation); the suite-inventory gate
agrees in check mode with the `+5` delta above.

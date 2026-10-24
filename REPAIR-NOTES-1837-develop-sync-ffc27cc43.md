# L1837 repair round — develop sync to ffc27cc43 (Biscuit ADR lands on trunk)

Round: post-merge-queue develop sync, lane L1837 (issue #1837, WebAuthn
verification adapter decision). Starting head `165d2580c`; develop had moved
to `ffc27cc43` ("WIP: Decision: Select Biscuit verification adapter (#2269)").

## What conflicted

Only `docs/adr/ADR-INDEX.md`: both sides appended a `Proposed` verification-
adapter row after `ADR-101726-e4bb`. HEAD carried the lane's WebAuthn row
(`ADR-101826-c3f1`, #1837); develop carried the Biscuit row (`ADR-101826-2a63`,
#2269). Resolution is a **union of both rows** (2a63 first, c3f1 second) — the
two decision gates are parallel Hybrid legs (WebAuthn human presence / Biscuit
delegated authority per accepted ADR-090726-9a4e) and neither supersedes the
other. Everything else in the merge was additive develop content
(REPAIR-NOTES-1838 rounds 2–9, the Biscuit ADR, its inventory note); no Python
source, test, lockfile, or workflow changed on either side of the conflict.

Merge commit: `5057de80b`.

## Re-validation at 5057de80b (all executed this round)

- `uv run python scripts/check-adr-index.py` → OK (every row agrees with front
  matter — proves the unioned Biscuit row too).
- Issue hygiene command: `uv run python scripts/check-adr-status-language.py &&
  git diff --check` → ok, exit 0.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → 39 passed.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run python scripts/check-suite-inventory.py` → 21/21 suites match.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1297 = 1297, exit 0
  (base now ffc27cc43).
- `uv run python scripts/check-adr-status-language-provenance.py` → 0
  contradictions, exit 0.
- `gitleaks detect --log-opts="ffc27cc43..HEAD"` (8.30.1) → no leaks found.
- Vector re-execution (independent of prior rounds): the ADR's **canonical
  recorded blobs** replayed against `webauthn==3.0.1` (isolated
  `uv run --with webauthn==3.0.1 --python 3.12`): registration verifies
  (fmt packed, sign_count 0, UV required satisfied, aaguid all-zero,
  credential_id bytes base64url-match the recorded id) and assertion verifies
  (counter 0→1, UV). The appendix simulator reproduces all outcomes: 2 valid
  ceremonies + I1–I6 refusals **verbatim** against the recorded message table.
- Gate-stays-open evidence re-confirmed at this head: `webauthn` absent from
  `uv.lock` (0 matches) and `packages/*/src`; ADR status `Proposed`; no
  issue-closure keyword on any branch commit; issue #1837 open in dispatch
  capture. The decision remains with ADR owner @BlakeMatthews-dev.

## Carry-over

This round touched no lane surface (security.yml, .gitleaksignore, lane tests
all byte-identical to the prior MERGE-READY head), so the prior round's
gate-exact image-lock reconciliation evidence (real uv export + pip-faithful
shim, negative control reproducing the hosted beartype error) stands. Hosted
CI at the new head is UNVERIFIED by the no-push rule, as before.

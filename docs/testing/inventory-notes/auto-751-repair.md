---
inventory-delta:
  tests/: +1
---
# Issue #751 compliance validator repair

Adds regression coverage for a pipe-less control row and a nonexistent GitHub Actions
execution. The latter proves that a repository-owned receipt cannot make an invented
run ID support an implemented claim; the validator must inspect the canonical run.

Re-validation (2026-09-22, head 2f0a8505f): `uv run python scripts/check_compliance.py` OK
(twice, byte-identical; deterministic via the registry `as_of` snapshot),
`uv run python scripts/check-suite-inventory.py --suite tests/` OK (3534),
`uv run pytest tests/test_check_compliance.py -q` 28 passed, ruff check/format clean.
Staleness semantics exercised end to end with `--as-of 2028-01-01T00:00:00Z`
(134 findings, exit 1). No new tests in this entry; deltas unchanged.

## Repair round 2026-09-25 (head afd658c64, digest refresh)

Merged topic commits (`84d937add`, `c0f5bf794`, `f546365fa`) changed artifacts cited by
`docs/compliance/claims.json` after the 09-22 refresh, so the deterministic validator
failed with 5 stale SHA-256 digests: `ev-at-02`/`ev-govern-1`
(packages/maistro-core/tests/security/test_sentinel_policy.py), `ev-govern-2`
(packages/maistro-core/tests/security/sentinel/test_audit.py), `ev-manage-3`
(.github/workflows/ci.yml), `ev-eu-art-17` (.github/workflows/quality.yml).

Repair: recomputed the five digests against the current worktree, re-observed those
records at the new registry snapshot `as_of 2026-09-25T12:00:00Z`, and bumped
`last_verified` to 2026-09-25 for AT-02, GOVERN-1, and GOVERN-2 after actually running
their cited tests (`uv run pytest packages/maistro-core/tests/security/test_sentinel_policy.py
packages/maistro-core/tests/security/sentinel/test_audit.py -q`: 45 passed). Workflow
digests were re-observed only (no local execution is claimed for CI definitions).

Re-validation (head afd658c64 + this repair): `uv run python scripts/check_compliance.py`
OK (twice, byte-identical), `--as-of 2028-01-01T00:00:00Z` 134 findings exit 1,
`uv run pytest tests/test_check_compliance.py -q` 28 passed,
`uv run python scripts/check-suite-inventory.py --suite tests/` OK (3644, resolving the
earlier 3537-vs-3532 drift), ruff clean on tracked files. Prior findings closed: the
README now states that provider-side run retention is outside this local validator, and
the production registry carries only repository-artifact records (no self-authored
execution receipt). Untracked scratch `check_evidence_shas.py` from the timed-out prior
run is superseded by `scripts/check_compliance.py`; kept out of the commit (it alone
fails ruff), preserved at /tmp/salvage-check_evidence_shas.py. No new tests; deltas
unchanged. No CI topology change.

## Repair round 2026-09-25 (head 60d382c07, final validation)

Re-validated at the exact assigned head, after the digest-refresh commit:

- `uv run python scripts/check_compliance.py` OK, byte-identical across two
  consecutive runs (registry `as_of` snapshot, no wall clock).
- `--as-of 2028-01-01T00:00:00Z` -> 134 findings, exit 1 (staleness semantics
  exercised end to end).
- `uv run pytest tests/test_check_compliance.py -q` 28 passed (inventory deltas
  +21 +3 +1 +2 +1 = 28 collected).
- `uv run python scripts/check-suite-inventory.py --suite tests/` OK (3644,
  recorded inventory matches).
- `uv run ruff check` over every tracked .py changed by the branch: all checks
  passed. The two findings under a bare `ruff check .` come only from the
  untracked scratch `check_evidence_shas.py` (kept out of the commit; the
  identical copy at /tmp/salvage-check_evidence_shas.py remains the salvage
  record).
- `scripts/check-doc-links.py` OK; `git diff develop...HEAD -- .github/` is
  empty (no CI-topology change); no closure keywords in branch commit
  messages; PR #1459 is OPEN and DRAFT.

Integration seam left to the parent (#362): two red gates remain at this
head, both caused solely by registering the deliberately-unwired validator
as honest debt —

- `scripts/check-reachability-provenance.py`: "@tool/check_compliance: NEW
  unreachable module absent from trusted base and not previously authorized".
- `scripts/check-reachability-dispositions-provenance.py`:
  "@tool/check_compliance: NEW disposition absent from trusted ledger and not
  covered by an already-landed reachability authorization".

The baseline and disposition rows are already in this branch. The
authorization half cannot come from this child: `load_authorizations` reads
`quality/ratchet-authorizations.json` from the trusted base revision by
design (`scripts/ratchet_provenance.py` — "a new grant does not take effect
in the change that introduces it"), so a grant landed here could never turn
these gates green in the same merge, and shared ratchet grants are outside
this child's declared bounds. Handoff to #362: land a `reachability`
authorization grant for `@tool/check_compliance` (owner, issue, reason per
the grant schema) in a ledger-owners merge on the trusted base; this
branch's baseline + disposition rows then complete the debt transaction once
its base contains the grant. No new tests; deltas unchanged.

## Independent re-verification 2026-09-25 (head 1511eb381, salvage resolved)

Re-checked every acceptance criterion against production behavior at the assigned
head, without trusting the earlier rounds' claims:

- `uv run python scripts/check_compliance.py` OK, byte-identical across two
  consecutive runs; `--as-of 2027-06-01T00:00:00Z` still OK (inside the
  registry's 365-day windows) and `--as-of 2027-10-01T00:00:00Z` -> 134 stale
  findings, exit 1, proving staleness semantics on the live registry.
- All eight cited test artifacts executed at this head (`uv run pytest
  formal/models/test_{composite_auth,dangerous_tools,flag_response,jwt_auth,
  memory_scopes,pii_filter,sentinel_policy,sentinel_validator}.py -q`):
  113 passed. The registry carries only `repository_artifact` records (66;
  zero self-authored execution receipts) and zero `implemented` claims, so no
  row outruns its evidence.
- `uv run pytest tests/test_check_compliance.py -q` 28 passed; note deltas
  +21 +3 +1 +2 +1 +0 = 28 collected, matching the file exactly.
- `scripts/check-suite-inventory.py --suite tests/` OK (3644);
  `check-reachability-dispositions.py` OK; `check-doc-links.py` OK;
  `ruff check .` and `ruff format --check .` clean.
- Re-ran both provenance gates: still exit 1 on `@tool/check_compliance`
  exactly as documented above; the grant belongs to a ledger-owners merge on
  the trusted base (#362), which this child may not author.
- Salvage resolved: the untracked scratch `check_evidence_shas.py` from the
  timed-out prior run duplicated the digest checking already committed in
  `scripts/check_compliance.py` (its purpose — locating the stale digests —
  was completed by 60d382c07). Copies preserved at
  `/tmp/salvage-check_evidence_shas.py` and
  `jobs/75c8e46a296542ec97dd83c15bbf16e4/salvage/`; removed from the worktree
  so `ruff check .` passes tree-wide. Precision fix to the 60d382c07 entry
  above: the empty `.github/` diff is against `origin/develop...HEAD`; against
  the stale local `develop` ref, topic-merge workflow deltas appear. This
  child's own commits touch no `.github` paths (verified per-commit). No new
  tests; deltas unchanged.


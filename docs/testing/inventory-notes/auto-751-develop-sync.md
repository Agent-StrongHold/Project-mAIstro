---
inventory-delta:
  tests/: +125
---

# #751 develop-sync merge resolution (auto-751)

Resolves the preserved `origin/develop` (b906cc577) merge conflicts in this worktree. Develop's
#1464 lane shipped a second, independent compliance stack (`scripts/check-compliance.py`,
`quality/compliance-registry.json`, `.github/workflows/compliance-evidence.yml`); this lane owns
the evidence-model stack (`scripts/check_compliance.py`, `docs/compliance/claims.json`). The
resolution keeps both stacks intact and independently validated.

## Conflict resolutions

- `tests/test_check_compliance.py` (both-added): develop's 97-test registry-gate suite keeps the
  canonical path because `quality/compliance-registry.json` `test_refs` and the evidence producer
  execute that exact path in CI. This lane's 28-test evidence-validator suite moves verbatim
  (byte-identical to its pre-merge content) to `tests/test_check_compliance_claims.py`. The two
  modules cannot share a file: both define a module-level `SCRIPT` constant pointing at their
  respective validator.
- `COMPLIANCE.md` (both-modified): keeps develop's marker-delimited control registry and
  Maintenance/release-binding prose AND this lane's six-status legend, detailed OWASP/NIST/EU AI
  Act/SOC 2 evidence tables (restoring section headings silently dropped by the merge), and the
  maintenance/deferral sections. A bridge paragraph documents that the two registries use
  disjoint control-ID namespaces and are validated independently.

## Machine-checked updates

- `docs/compliance/claims.json`: refreshed three repository-artifact digests drifted by the merge
  (`ev-map-2` -> COMPLIANCE.md, `ev-manage-3` -> .github/workflows/ci.yml, `ev-eu-art-17` ->
  .github/workflows/quality.yml); `ev-map-2.observed_at` re-anchored to the registry `as_of`. No
  status changed.

## Validation evidence (executed at this resolution)

- `uv run python scripts/check_compliance.py` -> OK (exit 0).
- `uv run python scripts/check-compliance.py` -> "compliance registry and COMPLIANCE.md are
  valid" (exit 0).
- `uv run pytest tests/test_check_compliance.py tests/test_check_compliance_claims.py -q` ->
  125 passed (97 develop + 28 this lane).
- `uv run ruff check` on both test modules and both validators -> clean.
- Prior recorded evidence in this directory citing
  `tests/test_check_compliance.py::test_*` now refers to
  `tests/test_check_compliance_claims.py::test_*`; the 28 test IDs are unchanged.

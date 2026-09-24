---
inventory-delta:
  tests/: +0
---

# Issue #751 independent verification (review head 0577de92f)

Executed at the exact review head (merge of develop 60862b6c5 into auto-751). Two gates are red;
everything else required by the child issue passes.

Red gate 1 — `uv run python scripts/check_compliance.py` exits 1 with 5 stale-sha256 findings:
`ev-at-02` and `ev-govern-1` (packages/maistro-core/tests/security/test_sentinel_policy.py),
`ev-govern-2` (packages/maistro-core/tests/security/sentinel/test_audit.py), `ev-manage-3`
(.github/workflows/ci.yml), `ev-eu-art-17` (.github/workflows/quality.yml). The digests were
refreshed at defe7aaf1 but the develop merge changed all five files afterwards; the earlier
re-validation recorded in auto-751-repair.md was taken at head 2f0a8505f, not this merge head.
Six `partially_implemented` claims (AT-02, AT-08, GOVERN-1, GOVERN-2, MANAGE-3, EU-ART-17) cite
the stale records. Repair path verified viable: the two cited sentinel test files still pass at
this head (45 passed), so refreshing digests + observed_at after re-running the cited evidence is
legitimate; no status correction is forced by current results.

Red gate 2 — `uv run python scripts/check-reachability-dispositions-provenance.py` fails:
"@tool/check_compliance: NEW disposition absent from trusted ledger". The disposition entry added
to quality/reachability-dispositions.json for the new validator is not covered by the provenance
authorization ledger. This is shared-quality-ledger territory the child issue declared out of
bounds; coordinate the provenance authorization with the topology owners (#362) or revert the
disposition pair if the ledger owners require it.

Green (executed at this head): `uv run pytest tests/test_check_compliance.py -q` 28 passed;
`uv run ruff check .` and `ruff format --check .` clean; `scripts/check-suite-inventory.py
--suite tests/` OK (3644); `scripts/check-reachability.py` OK (189 unreachable, all dispositioned);
`scripts/check-reachability-dispositions.py` OK (51 groups); staleness semantics exercised
end-to-end (`--as-of 2028-01-01T00:00:00Z` -> 139 findings, exit 1). No `.github/workflows`
changes in the branch diff; no GitHub closure keywords in branch commits or the PR body.

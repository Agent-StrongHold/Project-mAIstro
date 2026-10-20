---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, HEAD a2ac279bc)

Independent verification of the two repair commits on this lane; every
locally-runnable gate re-executed at CI's exact arguments rather than
trusted. No production or test code changed in this round (delta +0).

- Duplicate-identity metrics (prior finding): reproduced the defect
  against the pre-fix module (`git show 515a0284:.../retrieval/quality.py`
  run in /tmp against the same duplicate-id corpus through the real
  searcher) — recall=2.0, ndcg=1.6309297535714575, the ranking carrying
  ADR-001 twice; at this head the same public path reports recall=1.0,
  mrr=1.0, ndcg=1.0, `matched_relevant=("ADR-001",)`, while the raw
  searcher still returns both claimants (addressability preserved).
  Guard: `test_duplicate_identity_keeps_metrics_within_bounds`.
- Supply chain (pip-audit), CI's exact pipeline: `uv lock --check` OK;
  `uv sync --locked --all-extras`; `uv pip freeze --exclude-editable`
  (217 deps); `pip-audit --strict --format=json -r` (exit 1 = findings,
  report parseable, 199 deps) -> `scripts/pip_audit_gate.py` exit 0;
  only advisory left is the triaged ecdsa PYSEC-2026-1325. multidict
  6.9.1 / werkzeug 3.1.9 advisories are gone from the audited set.
  Hosted rollup at this head: Supply chain (pip-audit) = SUCCESS.
- pytest packages/maistro-registry/tests: 67 passed (inventory match).
- pytest tests/test_check_security_inventory.py: 49 passed.
- ruff check / ruff format --check: clean (3013 files).
- mypy (the six ci.yml src dirs, strict): Success, 829 files.
- scripts/check-suite-inventory.py: ok, 15 suites match.
- scripts/check-dependency-namespaces.py: exit 0.

UNVERIFIED by contract: hosted `test`, `Coverage gate`, and the
`gates-ran` aggregate were still IN_PROGRESS/pending at this head at
verification time. Everything previously failing at this lane
(pip-audit, SAST/security, Quality gate) is SUCCESS in the hosted
rollup at this exact head. PR body and commit messages carry no
fixes/closes/resolves keywords; PR 1742 refs #26 only.

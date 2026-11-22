inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26 repair/verify round (2026-10-08, head 52c8dc176, lane L26)

Verification-only round at develop-sync merge head `52c8dc176f87663f0131f6964f60a17d795d20b6`
(develop `e46ad6708fda20f76b8915679ef701f3ddb6b7e2` merged into auto-26; one
sync merge past the previously verified 50f4235e8). No production or test
code changed in this round (`inventory-delta: +0`); this note is the only
edit. The immediately preceding verify attempt failed to *start* pytest with
`OSError: [Errno 28] No space left on device` in /tmp — an environment
failure, not a code or test failure; every check below was re-executed at
this head.

## Validation battery (all executed at this head)

- `uv run pytest packages/maistro-registry/tests -q`: **84 passed** (2.20 s)
  — the exact suite the prior round could not start.
- `uv run pytest tests/test_check_reachability.py tests/test_check_security_inventory.py -q`:
  **74 passed** (29.21 s).
- `uv run ruff check .`: clean. `uv run ruff format --check .`: 3204 files clean.
- CI-exact mypy (ci.yml): `uv run mypy packages/maistro-core/src … maistro-ext-harness/src`
  → Success, no issues in 1034 source files.
- CI-exact vulture ledger: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1326 reviewed identities = 1326 findings, 0 unclassified.
- `scripts/check-reachability.py` exit 0 (1371 modules, 169 unreachable);
  `check-reachability-dispositions.py` exit 0 (49 groups cover all 169);
  `check-security-inventory.py` exit 0 (60 cited paths, 23 rows, 2 counted
  claims); `check-suite-inventory.py` exit 0 (17 suites match); `check-
  backlog-consistency.py` exit 0; `verify-monorepo-layout.sh` exit 0.

## Issue #26 acceptance, re-executed live at this head

- Eval seam: `uv run maistro-registry eval . --min-mrr 0.9 --min-recall 0.9`
  → exit 0; recall@10 0.9583 / MRR 0.9583 / nDCG@10 0.9292 over 24 golden
  queries; the no-answer case (`quantum consciousness module…`) reports
  [MISS] with mrr=0 — no fabricated citation, zero metric credit.
- Provenance: `maistro-registry search "scheduler"` returns per-result
  id, status, version, path — superseded material retrieved *with* its
  status (`ADR-046 [Superseded] (92c1d24898dd) docs/adr/ADR-046-scheduler.md`);
  the version hash was confirmed to be the sha256[:12] of the actual file
  content. `CorpusDocument` is a frozen dataclass; enrichment writes only
  separate term streams.
- Stale index: built `maistro-registry index .` (449 docs, fingerprint
  9a6fbd5e36be1dc5), appended a probe section to ADR-046-scheduler.md,
  `search --index` refused with **exit 2**, both fingerprints, and the
  rebuild command; probe then reverted from backup, `git status` clean.
- Boundary: `git diff e46ad6708..HEAD -- pyproject.toml uv.lock` is empty —
  no new dependencies; no vector service, Memory authority, or search
  backend introduced; expansion egress goes through the governed
  `execute_model_chat` seam only.
- Golden set covers the issue's named scenarios with dedicated tests:
  renamed source w/ stable id, changed content, superseded decision,
  duplicate identity, useless expansion terms vs corpus statistics, and
  the no-answer case (test files under packages/maistro-registry/tests/).

## Residual

- Hosted CI legs for this push remain the integration authority; pending
  CI is out of scope for a local lane (same caveat as prior notes).

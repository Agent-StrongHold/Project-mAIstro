inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26 verification (2026-10-08, merge head 50f4235e, verify lane L26)

Independent verification of issue #26 / PR 1742 at the develop-sync merge
head `50f4235e8003` (merge of develop `34795962548a` into auto-26; one
sync merge past the previously verified 82cf3596148). No production or
test code changed on the auto-26 side in that merge (`inventory-delta:
+0`); this note is the only edit. Every claim below was executed in this
round at this head, not carried forward.

## Issue #26 acceptance, re-derived and re-executed

- Golden set / corpus pin: 24 committed queries
  (maistro_registry/retrieval/golden_queries.json) covering exact ids
  (SPEC-243), terminology, paraphrases, linked ACs (SPEC-256 via its
  acceptance-criteria heading stream), supersession pairs
  (ADR-046 / ADR-082126-f69c), duplicate identity, and one declared
  no-answer case; corpus state pinned by the index fingerprint over
  (path, version) pairs.
- Baseline-first comparison with regressions: README table measures
  enrichment off / term filter off / static expansion on the same
  golden set and reports the expansion regression (-0.27 MRR) and the
  term filter's neutrality (+0.001 nDCG) rather than only wins;
  latency/cost stated (index ~0.3 s / 432 docs, ~2 ms/query, zero
  network; expansion one governed call, not offline-measured).
- Provenance: every result carries path/id/status/content-version;
  enrichment only adds term streams and never rewrites the frozen
  CorpusDocument. Superseded material is retrieved *with* its status
  (live: `ADR-046 [Superseded] (92c1d24898dd) docs/adr/ADR-046-scheduler.md`),
  never as active authority; the no-answer eval case reports [MISS]
  with zero metric credit — no fabricated governing citation.
- Stale index: after appending one KNOWN-GAPS section, `search --index`
  refused with both fingerprints and the rebuild command (exit 2);
  rebuilt index reproduces the identical fingerprint from the
  authoritative files (9a6fbd5e36be1dc5, 449 documents, twice).
- Boundary: no vector service, no new Memory authority, no search
  backend; no dependency changes (pyproject/uv.lock untouched vs base).

## Locally executed at this head

- pytest packages/maistro-registry/tests: 84 passed. pytest
  tests/test_check_reachability.py tests/test_check_security_inventory.py:
  74 passed (includes the two structural parse-count cache tests added
  on this branch). ruff check: clean; ruff format --check: 3179 files
  clean.
- CI-exact typecheck (ci.yml): `uv run mypy packages/maistro-core/src
  ... packages/maistro-registry/src packages/maistro-evolve/src` ->
  Success, 944 files. (Correction to the 82cf3596 note: the ci.yml mypy
  gate does include maistro-registry; only quality.yml's separate
  `mypy --strict` job is core-scoped.)
- Gates with CI's exact arguments: scripts/check-reachability.py
  (1369 modules, 169 unreachable, exit 0); scripts/check-security-
  inventory.py (60 cited paths, 23 rows, 2 counted claims, exit 0);
  scripts/check-suite-inventory.py full run (ok: 17 suites, 29486
  unique identities, 0 duplicate evidence); verify-monorepo-layout.sh
  exit 0; check-backlog-consistency.py exit 0.
- Live acceptance at the public seam: `maistro-registry eval .
  --min-mrr 0.9 --min-recall 0.9` -> recall@10 0.9583 / MRR 0.9583 /
  nDCG@10 0.9292, exit 0, over the current 449-document corpus — the
  recorded floor holds after corpus growth.

## Still open (recorded, not repaired here)

- Hosted CI at this head: every completed leg SUCCESS, but "Coverage
  gate (publish-set floor + diff coverage)", CI "test", and "gates-ran"
  were still pending after ~10 minutes of polling (2026-10-08). Pending
  CI is UNVERIFIED by contract; it remains a separate merge gate.
- No closure keywords (`fixes|closes|resolves ... #N`) in any commit
  message on the branch; the PR body says "Refs #26" only.

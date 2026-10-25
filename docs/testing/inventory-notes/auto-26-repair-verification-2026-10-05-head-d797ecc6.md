---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, head d797ecc6)

Validation-only repair round at head `d797ecc6ccef` (base `b672b799aba6`):
no production or test code changed, `inventory-delta: +0`. The open block —
"commit status not successful" at the merge-queue evaluation of ancestor
`39f72df15fd` (coverage-gate failure, run 37292468211) — resolves as
publisher-state plus an already-repaired producer timeout, re-proven locally
at CI's exact commands rather than trusted:

- **The named CI failure is fixed in the tree.** Run 37292468211's coverage
  gate failed because the `scripts` producer (root `tests/` suite under
  coverage, `--timeout=30`) blew its budget in
  `test_the_shipped_document_passes`; `6efbbfceb` (parse the security-inventory
  core census once per run) is the repair, landed after `39f72df15`. This
  round re-ran that exact producer end-to-end:
  `coverage run --branch --source=scripts -m pytest tests/ --timeout=30 -q`
  → 4595 passed / 107 skipped in 10m56s, **no timeout abort**.
- **Registry producer** at CI's exact command (including
  `tests/test_check_citation_status.py`): 318 passed in 13.5s.
  `check-diff-coverage.py coverage.xml --base b672b799aba6` → exit 0: all 9
  changed files measured or exempt, every measured file ≥ 90% lines / ≥ 80%
  branch arcs.
- **Hosted CI at this head**: all 31 captured check runs are success/skipped —
  including "Coverage gate (publish-set floor + diff coverage)" and
  "exact-debt-ledger". Re-running CI's own evaluator,
  `scripts/check-gates-ran.py --check-runs <captured> --require-complete
  --base-branch develop --event-name pull_request`, over that evidence returns
  **exit 0: all 28 required check(s) ran on this head**. The `gates-ran`
  commit status captured at dispatch reads `pending` ("Required execution
  evidence is still arriving") — publisher-state that self-corrects on the
  next producer completion; the same disposition as the 2026-10-05 note at
  head `801e2f72e37a`. Nothing in the tree is repairable for it.

Every locally-runnable gate re-executed at this head, at CI's exact
arguments, rather than trusted:

- ruff check / format --check: clean (2985 files).
- check-vulture-baseline.py (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`, exact-debt-ledger args): 1342 → 1342 reviewed
  identities, exit 0.
- check-suite-inventory: 15 suites match the recorded inventory (registry 66,
  root 4703).
- mypy over the six published `src` trees: clean, 818 source files.
- **Quality gate (Pillars 1–4, 7, 8) reproduced with a real database**: the
  local Docker daemon was down, so the machine's native PostgreSQL 18 cluster
  (pgvector installed) was used with CI's env — role/db `maistro`/`maistro_test`
  created, `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set, then
  `check-ac-state.py --run-tests --ratchet` → design coverage **42.8609%**
  exactly at the folded floor, 10 debt counters on their ceilings, exit 0 in
  2m04s. Without a database the same gate fails locally (38.15% measured) —
  skipped PG-legged AC tests are unprovable by design; this is the
  service-dependence the workflow documents, not a tree defect.
- `scripts/check-security-inventory.py`: OK in 4.7s (59 cited paths, 23
  inventory rows, 2 counted claims).
- `maistro-registry eval .` over the real corpus: recall@10 / MRR 0.9583,
  nDCG@10 0.9300 — exactly the README-recorded floor, exit 0, with the
  declared no-answer query scoring 0 (MISS shown, no fabricated governing
  citation).

One local-only environmental finding, recorded so the next round does not
chase it: a stale **gitignored** `quality/ac-state.json` (untracked runtime
artifact) makes `tests/test_branch_independence_repository.py::
test_every_quality_json_state_surface_is_classified_once` fail with
`unclassified quality state: quality/ac-state.json`. CI never sees the file;
moving it aside makes the test pass (proven, artifact restored). Delete or
rebuild the artifact locally; it is not a branch defect.

Issue #26 acceptance remains proven at this head: golden set with exact IDs /
terminology / paraphrases / decision-linkage / supersession pairs / one
declared no-answer case; measured per-intervention comparison with latency
and cost in `packages/maistro-registry/README.md`; provenance-carrying
results (id, status, content version, path); enrichment as a projection that
cannot overwrite source text or status; stale saved indexes refused by
corpus fingerprint (`test_search_refuses_a_stale_saved_index`,
`test_eval_refuses_an_index_stale_to_edited_content`); all mandated
regression cases covered (renamed source with stable id, changed content,
superseded decision retrieved with its status, duplicate identity,
corpus-vetoed expansion terms, no-answer); model egress through the one
governed gateway seam.

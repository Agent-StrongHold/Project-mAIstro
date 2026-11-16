---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, merge head 801e2f72)

Validation-only repair round at the post-develop-merge head `801e2f72e37a`
(base `94781cf6b708`): no production or test code changed, `inventory-delta: +0`.
The open block — "commit status not successful; CI gates red with no
repairable findings" — resolves as publisher-state, not tree state:

- The `gates-ran` commit status captured at dispatch read `pending` (run
  37270208290). Per `.github/workflows/gates-ran.yml`, `pending` is exit-2
  "Required execution evidence is still arriving": the publisher's
  best-effort `changed-files` collection is `continue-on-error` and an
  unmeasured scope stays pending, never a scoped pass. Re-running CI's own
  evaluator, `scripts/check-gates-ran.py --check-runs <captured> --require-complete
  --base-branch develop --event-name pull_request`, over the complete
  check-run evidence for this exact head returns **exit 0: all 28 required
  check(s) ran on this head** (with and without a changed-files sidecar).
  Every captured check run at `801e2f72` is success/skipped — including
  "Quality gate (Pillars 1–4, 7, 8)" and "exact-debt-ledger", the two
  named in the earlier block at ancestor `86144106d`. The pending status
  self-corrects on the next producer completion; nothing in the tree is
  repairable for it.

Every locally-runnable gate re-executed at this head, at CI's exact
arguments, rather than trusted:

- ruff check / format --check: clean (2930 files).
- check-vulture-baseline.py (exact-debt-ledger args): 1338 → 1338
  reviewed identities, exit 0.
- check-radon-baseline / check-reachability / check-doc-links /
  check-release-consistency / bump_version --check / check_enumerations /
  check-suite-inventory / check-backlog-consistency /
  check-ratchet-provenance / check-shipped-surface-truth: all exit 0.
- packages/maistro-registry/tests: 66 passed; suite-inventory matches the
  recorded baseline (66 identities).
- diff-coverage gate (`check-diff-coverage.py --base 94781cf6b708`): ok —
  every measured file ≥ 90% lines / ≥ 80% branch arcs.
- mypy packages/maistro-registry/src: the only 2 diagnostics are
  `import-untyped` on the *installed* `maistro` venv package (no
  py.typed in this worktree's sync — environmental, see the
  2026-10-05 note at head 8fe45fdb3 for the full-sync proof); CI's
  lint-and-type-check passed at this head.

Issue #26 acceptance re-proven live at the merge head: `maistro-registry
eval . --min-mrr 0.9` → recall@10 0.9583 / MRR 0.9583 / nDCG@10 0.930 over
the shipped 24-query golden set, exit 0, with the declared no-answer query
scoring 0 (MISS shown, no fabricated citation). All named issue cases
remain covered by tests (renamed source with stable id, changed content,
superseded status retrieved with status, duplicate identity, corpus-vetoed
expansion terms, declared no-answer) and stale/foreign saved indexes are
refused by fingerprint.

---
inventory-delta:
  packages/maistro-registry/tests: +0
---
# auto-26-repair-verification (2026-10-05, HEAD 8fe45fdb3)

Verification-only repair round: no production or test code changed. The
prior round's block — "CI gates red at 86144106d (Quality gate = failure),
commit status not successful" — is stale: `86144106d` is an ancestor of the
current head, every check run captured at `8fe45fdb3` is success/skipped,
and the newest `gates-ran` status at that head reads "All required checks
executed on this exact head" = success. Every locally-runnable Quality-gate
step was re-executed here at CI's exact arguments rather than trusted:

- ruff check / format --check: clean (2926 files).
- check-vulture-baseline.py (exact-debt-ledger args): 1338 -> 1338 identities.
- check-radon-baseline.py: 143 -> 143 C-or-worse blocks.
- xenon: 143 block violations <= baseline 145; 0 module-rank; 0 average.
- mypy --strict packages/maistro-core/src: clean over 706 files (only after
  `uv sync --locked --all-extras` — the missing-extras import errors are
  environmental, not violations); pyright ratchet 21 errors = baseline 21
  (pyright 1.1.414).
- acceptance-state ratchet: FAILS without the CI "Apply migrations" step
  (UndefinedTableError on `quota_invocation_evidence` depresses measured
  design coverage to 38.28 vs floor 42.51) and PASSES after
  `alembic upgrade head` against a fresh pgvector:pg18 — including the
  PR-event `--mandate <base>` variant. Environment gap, not a tree defect.
- formal/ property suite 663 passed + 1 skipped; fitness 23 passed;
  interrogate 53.4/58.4/71.1 vs floors 38/45/63; all scripts/check-* steps
  of the quality job pass (enumerations, retirement, route permissions,
  principal identity, frontend client, doc links, release/version
  consistency, vendored IFEval/BFCL, reachability + dispositions,
  credential authority, wiring reads, agent-store writes, contract
  markers, convergence, security inventory, image inventory/pins,
  workflow inventory, backlog, execution lifecycles, model egress,
  foreign-harness egress, both CLI fail-closed validators #1878/#1879).
- packages/maistro-registry/tests: 66 passed; with
  tests/test_check_citation_status.py under coverage: 318 passed;
  diff-coverage gate (base 31d891a5) ok at >=90% lines / >=80% arcs;
  suite-inventory gate: 14 suites match.

Issue #26 acceptance re-proven live: `maistro-registry eval .` reproduces
the recorded quality (MRR 0.9583 / recall@10 0.9583 / nDCG 0.930 over the
shipped 24-query golden set, exit 0 above the 0.90 floor); every named
issue case has a test (renamed source w/ stable id, changed content,
superseded status, duplicate identity, corpus-vetoed expansion terms,
declared no-answer); stale/foreign saved indexes are refused
(fingerprint); #374 governing-citation policy holds (318-test run above).

Residual (advisory, non-gating — operator review, not repair): the
remaining open Codex suggestions on PR #1742 — front-matter title not
feeding the title-weighted stream (body H1/filename fallback used),
`search`'s keyword-only `k` vs `evaluate`'s positional `Callable[[str,
int], ...]` docstring claim, a misspelled `search` root reporting
"no results" with exit 0, non-positive `-k` accepted, metrics not
deduplicating ranked ids (reachable only with duplicate registry ids,
which the validator rejects), an all-non-string expansion array returning
`[]` with `expansion_skipped=False`, and the ubiquity cutoff rejecting
every term in 1–2-document corpora. None is a failing gate or an issue
acceptance criterion; all are recorded for the PR's human review pass.

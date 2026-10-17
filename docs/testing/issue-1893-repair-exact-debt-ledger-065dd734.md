# Issue #1893 — exact-debt-ledger repair re-verification at 065dd734

**Verdict: BLOCKED stands — the two-merge provenance wall is the sole
exact-debt-ledger failure, it is real, and no in-tree repair exists. Every
other acceptance leg is green at this head.** This round re-derived the prior
conclusion from scratch instead of trusting it, and adds three pieces of
evidence the earlier records do not have: a live `git ls-remote` check of the
true develop tip, a check of develop's newest merge-queue refs for the grant,
and an explicit ruling-out of the reachability scanner's
`_EXCLUDED_PACKAGE_PYTHON` escape valve as a repair path.

## Starting state

- Branch `auto-1893`, exact head `065dd734796477532fcb8aea7eaa7c6f0e4c0bcd`,
  working tree clean on entry; only this record is added. No source, test,
  ledger, or gate file is modified.
- Driver logs for this job (check-0..4): sync OK, `ruff check` PASS,
  `ruff format --check` PASS (3301 files), focused pytest 346 passed / 3
  skipped, suite inventory `ok` at 16567 node IDs.

## CI job `exact-debt-ledger`, re-run locally with CI's exact arguments

Workflow: `.github/workflows/vulture-ratchet.yml` → `exact-debt-ledger`
(`RATCHET_BASE_REV` → `origin/develop` for a PR run).

| Step | Result at `065dd734` |
| --- | --- |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | **FAIL (rc=1)** — exactly `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`, via both `reachability dispositions` ("NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization", 169 → 171) and `reachability` ("NEW unreachable module absent from trusted base and not previously authorized", 171 unreachable of 1403). All seven other ratchets OK, no candidate-approved expansion. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS (rc=0)** — `1322 reviewed identities -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`. The ledger is exact: the brief's named target (`quality/vulture-baseline.json`) has zero unbanked identities to bank and zero eliminated identities to prune; amending it would fabricate rows the scanner does not report. |

## New evidence this round

1. **The true develop tip is unmoved (live check).** `git ls-remote origin
   refs/heads/develop` → `ab8b3737fa64f8d840f421ef87ca506c509444ff`, identical
   to `git merge-base HEAD origin/develop`. The branch is 0 commits behind and
   375 ahead: **there is no develop sync conflict to resolve** — the develop
   side simply does not contain the grants yet.
2. **The grant is not in flight toward develop.** The newest
   `origin/gh-readonly-queue/develop/*` refs visible at capture time
   (pr-2115 `d11368cd…`, pr-2126 `3c761d14…`) do not contain either admission
   identity in `quality/ratchet-authorizations.json`.
3. **The branch-side grant cannot self-authorize, by design.**
   `scripts/ratchet_provenance.py::load_authorizations` resolves
   `quality/ratchet-authorizations.json` from the base revision; its docstring
   states the consequence deliberately ("a new grant does not take effect in
   the change that introduces it … two merges"). The grant rows were added by
   this branch itself (`6af21c54e`, dispositions banked in `4cb757ce8`), and
   `git show ab8b3737:quality/ratchet-authorizations.json` contains neither
   identity.
4. **The reachability scanner's escape valve does not apply.**
   `scripts/check-reachability.py::_EXCLUDED_PACKAGE_PYTHON` classifies
   production-*shaped* Python that sits **outside** packaged src roots
   (developer utilities, DAG corpus, alembic `env.py`, out-of-tree examples).
   Both admission modules are shipped modules inside
   `packages/maistro-core/src/…` with zero production importers (verified:
   `admission_codec` is imported by tests only; `admission_identity` by the
   codec itself and `_vulture_whitelist.py`), so the classification is correct
   and the only untried "in-tree" path — adding them to the exclusion list —
   would be precisely the gate modification the issue forbids ("no
   baseline/grant/gate modifications to make an unwired slice green").

## Why the remaining in-tree options stay closed

- **Delete the modules:** destroys the mandated B2 deliverable
  (`packages/maistro-core/src/maistro/tasks/admission_codec.py` is the exact
  scope of this issue).
- **Wire them into production to become reachable:** violates the issue's
  stage constraints (B2 is the inactive contract leaf; "C is the consumer";
  "No production activation … is authorized"). The one attempt (`29e3be4`)
  broke behavior and was reverted at `0eacd9a4`.
- **Candidate-side ledger/disposition/grant edits:** cannot change the
  verdict — the gate reads the trusted base, and a clean candidate ledger with
  no landed grant still fails (documented two-merge wall, AGENTS.md,
  docs/quality-gates.md).

**Unblock (outside worker authority):** land the #1893 reachability
authorization on develop via a separate reviewed PR — the exact rows already
exist on this branch (`quality/ratchet-authorizations.json`, commit
`6af21c54e`) for review — then merge develop into `auto-1893`. Until then the
merge-queue `exact-debt-ledger` check fails on exactly these two identities;
everything else the job measures is green and exact at this head.

## B2 acceptance re-check at this head (fresh, this round)

- Focused pytest `packages/maistro-core/tests/tasks/test_admission_codec.py`
  + `packages/maistro-core/tests/runs/test_root_admission_identity.py`:
  **201 passed, 3 skipped** (the 3 skips are the PG round-trip legs, proven
  live in the previous round on fresh disposable DB `adm1893_r1792245817`
  with the real migration chain and `MAISTRO_REQUIRE_PG_LEGS=1`: 131 + 73
  passed, 0 skipped, DB dropped afterwards).
- All 10 prospective test names from the issue body present (grep 10/10) in
  `test_admission_codec.py`.
- `uv run mypy` on `admission_codec.py` + `admission_identity.py`: clean.
- `ruff check .` / `ruff format --check .`: PASS (driver check-1/2 and prior
  round).

## Inventory note

Docs-only round: no test added, removed, or renamed, so no
`docs/testing/inventory-notes/` delta is required; the suite inventory remains
at the recorded 16567 identities (driver check-4 `ok`).

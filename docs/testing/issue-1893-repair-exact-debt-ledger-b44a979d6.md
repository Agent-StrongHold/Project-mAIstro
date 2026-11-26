# Issue #1893 — exact-debt-ledger repair round at b44a979d6

**Verdict: BLOCKED stands, re-proven independently this round without assuming
any prior claim. The two-merge provenance wall remains the sole
`exact-debt-ledger` failure. The round brief's named repair path — amending
`quality/vulture-baseline.json` — has zero genuine targets: the vulture gate
passes exactly (1322 == 1322, unclassified 0). No candidate-side edit can green
the gate without violating the issue's own constraint ("no baseline/grant/gate
modifications to make an unwired slice green") or the documented two-merge
rule; unblocking requires the grant to land in develop first, which is a
GitHub mutation outside writer authority.**

Entry state: branch `auto-1893`, exact head
`b44a979d6b7045df5c6309da519017611f4702d4` (verified against the lane
assignment), working tree clean. Only this record is added; no source, test,
ledger, or gate file is modified.

## Driver deterministic checks (job 0898b26241604bb9afcc55e79bd8f878)

All five driver checks green at this head: `uv sync --locked --extra dev`,
`ruff check .` (all checks passed), `ruff format --check .` (3301 files
formatted), focused pytest over the four issue-named files (**346 passed,
3 skipped** — the skips are the PG-gated durability legs), and
`check-suite-inventory.py --suite packages/maistro-core/tests`
(ok: 1 suite matches the recorded inventory, 16567 unique node identities).

## CI job `exact-debt-ledger`, re-run locally with CI's exact arguments

Workflow: `.github/workflows/vulture-ratchet.yml` → `exact-debt-ledger`;
`RATCHET_BASE_REV` resolves to `origin/develop` for a PR run.

| Step | Result at `b44a979d6` |
| --- | --- |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | **FAIL** — exactly `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`, via both `reachability-dispositions` ("NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization", 169 → 171) and `reachability` ("NEW unreachable module absent from trusted base and not previously authorized", 171 of 1403). All seven other ratchets OK; the two sub-gates named in the failure tail (`check-reachability-dispositions-provenance.py`, `check-reachability-provenance.py`) returned 1 for exactly these identities. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (rc=0) — matrix complete. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS (rc=0)** — `1322 reviewed identities -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`. The ledger is exact: zero unbanked identities to bank and zero eliminated identities to prune. The CI-repair brief's amendment target therefore has no genuine rows; amending it would fabricate findings, which the round contract forbids ("a repair must address actual evidence, not guessed scanner findings"). |

## Root cause, re-derived this round (not assumed)

1. **Base grant state.** `git show ab8b3737:quality/ratchet-authorizations.json`
   contains **zero** rows matching `admission_identity`/`admission_codec`
   (grep rc=1). The branch's own grant rows
   (`quality/ratchet-authorizations.json` lines 66–75, added at `6af21c54e`,
   with owner/issue/reason naming #1893/#1851/#1845 and the CONNECT
   dispositions in `quality/reachability-dispositions.json` line 609) exist
   only candidate-side.
2. **Base-only grant loading is deliberate.**
   `scripts/ratchet_provenance.py::load_authorizations` (lines 478–509)
   resolves the authorizations file against the base revision; the docstring
   states the two-merge consequence verbatim: "a new grant does not take
   effect in the change that introduces it. Authorizing a floor-raise is now
   two merges -- the grant, then the regression it permits". Confirmed
   empirically this round: the gate still fails on a tree that already
   contains the grants.
3. **The develop side is unmoved (live, this round).** `git fetch origin` +
   `git ls-remote origin refs/heads/develop` →
   `ab8b3737fa64f8d840f421ef87ca506c509444ff` = merge base; branch is
   0 behind develop. No develop-sync conflict exists to resolve and the grant
   has not landed upstream, so the two-merge sequence cannot proceed from
   here.
4. **The unwired state is the deliverable, not a defect.** Issue #1893 scopes
   B2 as a pure contract leaf ("no SQL mutation, HTTP mapping or queue
   changes"; "C is the consumer that orders valid header -> … decoding") and
   explicitly forbids "test imports, fake callers and package exports" as
   reachability and "baseline/grant/gate modifications to make an unwired
   slice green". The two flagged modules are therefore correctly unreachable
   until leaf C; the only sanctioned green path is grant-first integration.
5. **Hygiene note (no action taken).** This worktree has a stale local branch
   named `refs/heads/origin/develop` that makes `git rev-parse origin/develop`
   print an ambiguity warning; both it and `refs/remotes/origin/develop`
   resolve to `ab8b3737`, so base resolution is unaffected. Branch deletion is
   outside writer authority, so it is recorded here instead of removed.

## Deliverable acceptance, re-verified this round

- Focused B2 suite: `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
  **128 passed, 3 skipped**. The three skips are the PG durability legs,
  gated at `test_admission_codec.py:470` on nonempty
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` — consistent with the
  issue's rule that fake/skipped PG is never counted as durability proof.
- PG durability legs: proven live in the two immediately preceding rounds
  (`docs/testing/issue-1893-repair-exact-debt-ledger-2b92bf17.md`,
  `…-3c59d681a.md`) on fresh disposable databases (`adm1893_r1792248850`,
  `adm1893_r1792250719`) migrated through the real alembic chain to head 063:
  **204 passed / 0 skipped** under `MAISTRO_REQUIRE_PG_LEGS=1`, row counts
  zeroed after. Valid for this head: `git diff --stat 065dd7347..HEAD` touches
  only three docs notes (336 insertions) — the tested code content is
  unchanged since those live proofs.
- `check-suite-inventory.py --suite packages/maistro-core/tests`: ok
  (driver check-4), so the recorded inventory matches this tree.

## Unblock path (integration authority required, outside worker scope)

1. Land the already-reviewed grant rows for `maistro.runs.admission_identity`
   and `maistro.tasks.admission_codec` in a **grant-only PR into develop**
   (they are already present on this branch with owner/issue/reason; they
   cannot self-authorize here by design).
2. Merge develop into `auto-1893` (or rebase the candidate); from that point
   the base carries the grants and `check-ratchet-provenance.py` passes,
   making all three `exact-debt-ledger` steps green.

Both steps are GitHub/branch mutations that this lane is prohibited from
performing; recorded here so the integration owner can execute them without
re-deriving the analysis.

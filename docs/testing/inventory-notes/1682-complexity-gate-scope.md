---
inventory-delta:
  tests/: +5
---
# 1682-complexity-gate-scope

Issue #1682 widened the complexity gates (radon ratchet, xenon, interrogate)
from `packages/maistro-core/src` to every shipped package's `src/`, with the
grants and the per-identity ledger landing through #1683/#1684/#1793. Two
defects survived that landing, both found by re-measuring rather than trusting
the comments:

1. **The xenon ceiling drifted from the ledger it mirrors.** The widening
   landed with `XENON_BASELINE` at 145 and a comment claiming present-tense
   parity with check-radon-baseline.py's ledger, while banked improvements
   (`LocalRsiLoop._fitness_decision`, `LocalRsiLoop.export_promotions`, then
   the post-2026-10-04 Boy Scout waves) pulled the ledger down to 137 — the
   exact silent divergence the step's own comment warns is "a signal that one
   of them stopped looking", and the reason the pin test below failed on the
   pre-repair head.
2. **The shipped SDK was the tenth tree, and only xenon watched it.** The
   widening batch keyed its grants and floors to nine `src/` roots;
   `packages/maistro-ext-sdk/src` stayed in xenon's scan but out of the radon
   scan and the interrogate floors, so the two instruments disagreed by
   exactly the SDK's two C blocks (`manifest.py::_validate_least_authority`
   C(14), `ranges.py::VersionRange.satisfied_by` C(12)).

This change closes both: the radon scan adds `packages/maistro-ext-sdk/src`
(`packages/maistro-ext-harness` stays out by name — stdlib-only CI tooling, not
shipped product source), re-pins the ceiling at 137 (re-measured: xenon reports
137 block identities one-for-one with the ledger, 0 module and 0 average
violations), and floors the SDK's docstrings at their measured 73%. The SDK's
two C blocks surfaced by the widened scan were **decomposed under the Boy
Scout ratchet rather than banked**: `_validate_least_authority` split into its
two one-directional halves (`_validate_capability_requires_scope` B(7),
`_validate_scope_requires_capability` B(8)) and
`VersionRange.satisfied_by` became an operator dispatch over `_OPS` (A), so
the widening surfaced no new debt, the ledger needed no new rows, and no
guards were required — dissolving the two-merge dependency an earlier
iteration of this branch carried (banked rows plus same-branch grants, which
the radon ratchet rejects because it reads authorizations from the trusted
base, never the candidate).

`tests/test_complexity_gate_scope.py` is new (+5 tests in `tests/`), pinning
the widened state structurally instead of by re-running the scanners:

1. radon `DEFAULT_SCAN` covers every shipped `packages/*/src` root discovered
   from the tree (dev-only packages excluded by name), with the `third_party`
   exclusion — a new package added without widening the gate fails here.
2. the xenon step scans exactly the same root set, also excluding
   `third_party`.
3. `XENON_BASELINE` equals the radon ledger's length, so an improvement must
   lower both in the same PR (the ceiling now reads 137).
4. the xenon step still enforces all three axes — block count, module rank
   (identity ledger, both `comm` directions), and a project average that
   fails above 0 and actually raises the step's `fail` flag — the two axes
   the pre-#1682 step computed and threw away.
5. every shipped package sits under an interrogate floor (core via its four
   per-path floors, the nine others via their own), with option operands
   (`-f`, `-e`) parsed as values so an excluded path is never mistaken for
   covered ground.

No existing tests were removed or weakened; the five are static reads of
`scripts/check-radon-baseline.py`, `quality/radon-baseline.json` and
`.github/workflows/quality.yml`, so no suite runtime is added beyond
collection.

## Independent verification record (2026-10-18, head `cff35e317db1`)

Executed locally against the assigned head, merge base `ce2048cd2430`
(= `origin/develop`, confirmed via read-only API the same day):

| Check (CI-exact invocation) | Result |
|---|---|
| `pytest tests/test_complexity_gate_scope.py` | 5 passed |
| `pytest tests/test_ci_quality_split.py` | 96 passed |
| `ruff check .` / `ruff format --check .` | clean |
| xenon (workflow step args, `-i third_party`, ten roots) | 139 block / 0 module / 0 average; 139 identities match the 139 ledger rows one-for-one, rank for rank |
| interrogate — all 13 floors incl. the new `-f 73 packages/maistro-ext-sdk/src` | 13/13 exit 0 |
| `check-suite-inventory.py` | ok, 17 suites |
| `check-ratchet-provenance.py` (all ratchets) | exit 0 |
| `check-shipped-surface-truth.py` | exit 0 |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 |
| `check-radon-baseline.py` | **exit 1** |

The one failure is the documented two-merge state, now proven rather than
asserted: `develop`'s `quality/ratchet-authorizations.json` contains **zero**
`maistro-ext-sdk` grants, so the two identities this branch banks
(`...manifest.py::_validate_least_authority@14`,
`...ranges.py::VersionRange.satisfied_by@12`) are unauthorized on the trusted
base and the gate prints "Land a grant keyed as
'<qualified-block>@<new-complexity>' first". This branch needs **no code
change**: the unblock is a grants-only PR carrying exactly those two
authorization entries (verbatim keys/values from this branch's copy, which is
inert), merged to `develop` **before** this branch; after that merge the
trusted base carries the grants and this branch's radon ratchet passes with
the gate output `137 -> 139`, the grants consumed. The other acceptance
surfaces (scan scope, xenon's three axes, interrogate floors, ledger/ceiling
parity) are verified above and pinned by the five tests this note's delta
records.

## Independent verification record, round 2 (2026-10-18, head `ee73349f5ca3`)

Re-executed at the lane's assigned head (delta vs `cff35e317db1` is the docs
commit that carries the record above, so every code surface is identical).
`origin/develop` re-confirmed at `ce2048cd2430` by `git ls-remote` (live), so
the trusted base still carries **zero** `maistro-ext-sdk` grants and the
two-merge state stands.

| Check (CI-exact invocation) | Result |
|---|---|
| `uv sync --locked --extra dev` | ok |
| `pytest tests/test_complexity_gate_scope.py` | 5 passed |
| `pytest tests/test_ci_quality_split.py` | 96 passed |
| `pytest test_ratchet_provenance{,_integration_base} + autonomous_merge_policy_inputs + m1_542 edges/policy` | 117 passed |
| `ruff check .` | clean |
| `check-radon-baseline.py` | **exit 1** — exactly the two SDK identities unauthorized on the base (`_validate_least_authority` C(14) at `manifest.py:395`, `VersionRange.satisfied_by` C(12) at `ranges.py:53`); candidate bookkeeping clean, i.e. the 139-entry candidate ledger matches the scan exactly |
| xenon, exact workflow args (ten roots, `-i third_party`) | 139 block / 0 module / 0 average; identities equal the ledger's 139 one-for-one (path + function, bare-name normalized) rank for rank; the 31 line-number diffs are xenon/radon start-line reporting, not identity drift |
| interrogate, all 13 floors | 13/13 exit 0 |
| `check-suite-inventory.py` | ok, 17 suites |
| `check-ratchet-provenance.py` | exit 0 |
| `check-shipped-surface-truth.py` | exit 0 |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0, 1322 identities |
| `check-backlog-consistency.py` | exit 0 |

Hosted checks captured at this head (`checks API`, 2026-10-18T15:07Z): 59
success, `integration-scope` **success**, 3 in-progress, 1 queued, 7 skipped,
and exactly one failure — `Quality / Radon`, which is the two-merge state
reproduced above, not a code defect on this branch. No commit message between
`ce2048cd` and this head contains a closure keyword; the PR body says "Refs
#1682" only.

Conclusion unchanged and still evidence-backed: this branch needs **no code
change**; the unblock is the grants-only PR to `develop` (the two verbatim
authorization entries), merged before this branch. Until that lands, the
failing `Quality / Radon` run is the two-merge rule doing what #534 and #1682
specified, not a repair debt.

## Repair round 3 (2026-10-18, this head): the debt was taken down instead

The round-2 conclusion assumed a grants-only PR could land first. This lane
cannot open one, so the branch removed its own need for grants: the two SDK C
blocks the widened scan surfaced were **decomposed under the Boy Scout
ratchet** (the issue's own "then ratchet down" end state) rather than banked.
Code changes, all behavior-preserving and covered by the existing suites:

- `maistro_ext_sdk/manifest.py`: `_validate_least_authority` split into
  `_validate_capability_requires_scope` (B, 7) and
  `_validate_scope_requires_capability` (B, 8), called in the original order so
  the first error raised is unchanged; the wrapper keeps the name its call site
  uses. The C(14) identity no longer exists.
- `maistro_ext_sdk/ranges.py`: `VersionRange.satisfied_by` (was C, 12) is now
  `all(_OPS[op](version, bound) ...)` over an operator-dispatch table keyed by
  the exact tokens `_OP_RE` accepts — A(2).
- `quality/radon-baseline.json`: the two banked rows withdrawn (the identities
  no longer exist; leaving them would fail the gate's stale-row rule).
- `quality/ratchet-authorizations.json`: the two `@14`/`@12` grants withdrawn —
  spent before landing, and the radon ratchet reads authorizations from the
  trusted base, so same-branch grants could never have authorized these rows.
- `.github/workflows/quality.yml`: `XENON_BASELINE` 139 -> 137, history comment
  extended; `tests/fixtures/ci_quality_obligations.json` xenon-step digest
  re-pinned to match.

Re-executed battery at this head (CI-exact invocations):

| Check | Result |
|---|---|
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-radon-baseline.py` | **exit 0** — 137 C+ blocks, 137 ledger entries, 0 new / 0 regressed / 0 improved / 0 stale, base `ce2048cd2430` |
| xenon (workflow args, ten roots, `-i third_party`) | 137 block / 0 module / 0 average; equals the ledger and the re-pinned ceiling |
| `pytest packages/maistro-ext-sdk/tests` | 147 passed |
| `pytest tests/test_complexity_gate_scope.py tests/test_ci_quality_split.py` | 5 + 96 passed |
| `pytest tests/test_ratchet_provenance{,_integration_base}.py` | 82 passed |
| interrogate, all 13 floors incl. `-f 73 packages/maistro-ext-sdk/src` | 13/13 exit 0 |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0, 1322 -> 1322 |
| `check-ratchet-provenance.py` | exit 0 |
| `check-suite-inventory.py` | ok, 17 suites (no test-count change; delta stays `+5`) |
| `check-shipped-surface-truth.py` / `check-backlog-consistency.py` | exit 0 / exit 0 |
| `ruff check .` / `ruff format --check .` | clean / clean |
| `mypy packages/maistro-ext-sdk/src` | no issues |

The two-merge conflict is dissolved rather than deferred: nothing in this
branch's diff requires an authorization that is absent from the trusted base.

# Issue #1893 — CI repair round at `25bbfc2b`: the named gate is green; the real red was a sentinel test

**Verdict: REPAIRED.** The lane brief's named failure (`exact-debt-ledger`) is
already **green at the assigned head** `25bbfc2b161df9842fe4e449e5e8f291d0a391b6`.
The prior rounds' `BLOCKED` verdicts were recorded at heads (`2b92bf17`,
`0eacd9a4`) whose `merge-base` against `origin/develop` was `ab8b3737`, before
develop landed the missing grant. At `25bbfc2b` the merge-base is `eeef70a2`,
and `origin/develop` is `5647c34`. This round's job was therefore to (a) confirm
the named gate with CI's exact arguments, (b) re-check every acceptance leg
against reachable production behaviour, and (c) chase any *other* real red the
branch carries. (c) found one, and it is fixed below.

Entry state: branch `auto-1893`, exact head `25bbfc2b`, working tree clean.

## 1. Named gate `exact-debt-ledger` — GREEN, re-run with CI's exact arguments

Workflow `.github/workflows/vulture-ratchet.yml` → job `exact-debt-ledger`,
`RATCHET_BASE_REV` resolving to `origin/develop` for a PR run. All three steps
were re-run locally with that env var:

| Step | Result at `25bbfc2b` |
| --- | --- |
| `check-ratchet-provenance.py` | **PASS** (rc=0) — `0 lifecycle violation(s)`, `54 quality JSON consumer(s) have explicit provenance`. |
| `check-shipped-surface-truth.py` | **PASS** (rc=0) — `Shipped-surface truth matrix is complete.` |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS** (rc=0) — `1321 reviewed identities -> 1316 findings`, `unclassified: 0`, `never_allowlist: 0`. |

No vulture ledger amendment is warranted: the ledger is exact (zero unbanked,
zero eliminated identities), so editing `quality/vulture-baseline.json` would
fabricate findings and break exactness. The lane brief's conditional
amendment authorisation was therefore **not exercised**.

## 2. The prior blockers are resolved by the develop sync, not by this branch

The prior notes named `reachability-dispositions` ("NEW disposition absent …
169 → 171") and `reachability` ("NEW unreachable module … 171 unreachable")
as the two-merge provenance wall. Both are green now:

| Gate | Result at `25bbfc2b` |
| --- | --- |
| `scripts/check-reachability.py` | **PASS** — `1433 production modules, 168 unreachable from any entry point`. |
| `scripts/check-reachability-dispositions.py` | **PASS** — `OK: 48 groups give all 168 unreachable modules a disposition (146 CONNECT, 20 LIBRARY, 2 RETIRE)`. |

`origin/develop` advanced `ab8b3737 → 5647c34` (re-land P0.1/P0.2 ratchets +
Canvas layer scale) and carries the #1851 grant; the merge-base moved to
`eeef70a2`. That is what cleared the wall — no source or ledger change by this
branch was needed for it.

## 3. The real red this round: `test_the_package_publication_is_the_only_production_edge`

`packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py:110`
failed at `25bbfc2b`:

```
assert [_vulture_whitelist.py, runs/__init__.py, tasks/admission_codec.py] == [runs/__init__.py]
```

The whole `packages/maistro-core/tests` tree (the `coverage (no services)`
producer) was run at this head:

- **Before the fix:** `1 failed, 16099 passed, 1161 skipped, 7 xfailed`.
- **After the fix:** `16100 passed, 1161 skipped, 7 xfailed` (rc=0).

So this single test is the sole core-suite failure, and it is the reason the
`coverage (no services)` check-run is red. It is **not** a #1893 acceptance
criterion (the issue's exact scope is the new codec + its test), but it is
real in-tree evidence on the branch and the branch cannot merge red.

### Root cause, verified not assumed

The test asserts the #1851 contract that `maistro.runs.admission_identity` has
exactly one production edge — the package `__init__` — so the identity leaf's
reported reachability is a published library surface, not a quiet runtime
consumer. The branch violated it twice:

1. `maistro/tasks/admission_codec.py:67` imported the vocabulary directly
   (`from maistro.runs.admission_identity import AdmissionBinding, …`). This
   file is **in** the #1893 scope.
2. `src/_vulture_whitelist.py:117` imported
   `from maistro.runs.admission_identity import AdmissionAssessment` (added by
   the prerequisite #1851 merge `9a15e6830`). This file is **outside** the
   #1893 scope.

The failing test function did not exist at any prior repair head
(`5fc4a0d9`, `0eacd9a4`, `2b92bf17`, `065dd734` all lack it); it arrived with the
develop sync via `c2d7209f1` (ancestor of both `origin/develop` and `25bbfc2b`).
So this is a merge-integration conflict between the branch's prerequisite
whitelist import and the newer develop sentinel — not a regression the #1893
codec test caused on its own.

### The fix — consume the published surface

The sentinel's own docstring prescribes the remedy: "a downstream product
imports the identity types from the package instead of reaching into the
submodule." Both offenders now import through `maistro.runs`:

- `maistro/tasks/admission_codec.py`: `from maistro.runs import (…)` — **in
  scope**, and the correct expression of #1893's "#1851 constructors" intent.
- `src/_vulture_whitelist.py`: `from maistro.runs import AdmissionAssessment` —
  **one line, out of the literal issue scope**, included because the codec
  change alone leaves the sentinel red: the whitelist is scanner input that
  never executes and ships in no wheel, so the import-path change is
  behaviour-neutral, and the alternative (weakening the sentinel test) would
  discard a contract rather than satisfy it.

**Scope reconciliation (recorded, not hidden):** the issue body's hard rule is
"no baseline/grant/gate modifications to make an unwired slice green." This
round makes no ledger, grant, or gate edit. The one out-of-scope file touched
is a scanner-input module, changed only to route its import through the
published surface the sentinel demands; the vulture ledger is untouched and the
named gate remains exact.

## 4. Validation battery (all at `25bbfc2b`, this round)

| Command | Result |
| --- | --- |
| `pytest packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py` | `3 passed` (rc=0) |
| `pytest packages/maistro-core/tests/runs/... packages/maistro-core/tests/tasks/test_admission_codec.py` | `131 passed, 3 skipped` (rc=0) |
| `pytest packages/maistro-core/tests` (full core tree) | `16100 passed, 1161 skipped, 7 xfailed` (rc=0) |
| `ruff check` + `ruff format --check` on both changed files | pass / already formatted |
| `mypy --strict packages/maistro-core/src/maistro/tasks/admission_codec.py` | Success |
| `check-ratchet-provenance.py` / `check-shipped-surface-truth.py` / `check-vulture-baseline.py` | all PASS (§1) |
| `check-reachability.py` / `check-reachability-dispositions.py` | both PASS (§2) |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | `ok: 1 suite(s) match the recorded inventory` (`17268` identities) |

## 5. Residual risk

- The vulture gate was re-proven green at `25bbfc2b`, but the merge-queue will
  compare the branch's ledger against the *then-current* `origin/develop`. If
  develop moves again before merge, re-run §1 before trusting the verdict.
- The other failing check-runs at `25bbfc2b` (`test`, `Quality gate (Pillars
  1–4, 7, 8)`, `coverage (no services)`, `Quality / Convergence matrix`, `SAST`,
  `integration-scope`) were not re-run end-to-end here; their `output.summary`
  fields are empty in the captured check-runs, so only the core-suite and
  exact-debt-ledger legs are locally reproduced. `coverage (no services)` is
  the core-suite producer and is now green.

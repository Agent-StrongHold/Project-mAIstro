---
inventory-delta:
  tests/: +3
---

# auto-1859 — the API gate's temporary-disposition contract (#1859)

## Status: resolved on the owner-accepted exception contract, reconciled with develop `ab8b3737`

## The contradiction (characterized before anything changed)

At PR #1716 head `61913386e` — and still at this branch's original base
`faf93b2f0` — the gate contradicted itself: the checker documentation,
`docs/api/route-contract-inventory.md` and the registry `_comment`
advertised a registered `temporary` disposition (tracking issue + unexpired
review date) as the way a canned handler ships, `_check_registry` validated
those fields, but `main()` unconditionally failed every canned handler
without consulting its disposition, and its advice offered registration as
a pass that never existed. A synthetic full-gate run at that base with a
canned handler whose exact registry entry carried `disposition="temporary"`,
issue `#9999` and a future expiry exited **1** while the advice offered
"or register a temporary disposition" — recorded by the first attempt
(`8e6b74bb2`).

## Where the owner decision actually lives (the blocker, resolved)

#1859 asked the policy owner to state whether a temporary entry is
tracking-only-while-red or a narrowly governed exception, and to cite
accepted policy before changing acceptance behavior. The first attempt
looked in the issue threads and found nothing (#1859 carried no policy
comments; the only #1716 review is a Codex bot), so it shipped the branch
that cannot weaken #389 — tracking-only — and flagged the missing owner
statement as its blocker.

The statement exists in the repository instead of the threads: after that
attempt (commits `8e6b74bb2`/`8684ee504`, 2026-10-05 04:22 UTC), develop
landed the decision through merged, CI-green PRs on this same gate, all
present in this round's base `ab8b3737`:

- **#1974** (`901b84f78`, 2026-10-05 11:00 UTC) —
  `_temporary_exempt_identities()`: a registry entry with
  `disposition="temporary"`, a tracking issue and an unexpired review date
  exempts that exact `(file, method, path)` identity from the canned
  findings, and `main()` passes it through. `docs/api/
  route-contract-inventory.md` documents the excuse. That is the narrowly
  governed **exact-route exception**, accepted and shipped on develop
  ~7 hours after the tracking-only attempt raced it.
- **#1976** (`94781cf6b`) — the excuse is pinned to the declared handler
  identity, so a wrong-identity entry cannot satisfy it.
- **#1975** (`9a5eb7ba6`) — the canned judgment scope was refined; the
  excuse applies to every detected handler class.

Accepted, merged develop state is the policy of record for this gate; the
#389 invariant stays intact because the excuse is per-identity, must expire,
and the shipped registry holds **zero** `temporary` entries (9 implemented /
5 unsupported-501 / 1 preview) — no canned route ships today.

## Reconciliation of this branch (this round)

- Merged develop `ab8b3737` into the branch. All four surfaces the tracking
  only attempt had touched — `scripts/check-api-route-contracts.py`,
  `docs/api/route-contract-inventory.md`, `quality/api-route-contracts.json`,
  `tests/test_check_api_route_contracts.py` — are **byte-identical to
  `ab8b3737`**: the tracking-only reversal is superseded by the
  owner-accepted exception contract it raced against. Conflicts were
  resolved toward develop, and the auto-merged registry `_comment` was
  restored to develop's wording (it passes before expiry and refuses once
  expired — correct under the exception contract).
- This lane's surviving contribution: this decision record and the two
  main()-level negative proofs #1859 names that develop's suite still
  lacked (below). The 9 tracking-only tests from the first attempt were
  withdrawn together with that contract.

## Acceptance mapping (#1859)

- **Owner-approved contract** → the exception branch, per merged develop
  #1974/#1976/#1975 in base `ab8b3737` (cited above); not silently relaxing
  #389: no temporary entry exists in the registry, and the excuse is
  exact-identity and expiring.
- **Exception applied end to end, negatives still fail** → develop's suite
  proves at `main()` level: valid temporary entry passes
  (`test_registered_valid_temporary_disposition_excuses_logging_only_handler`,
  `main() == 0`), expired does not, unregistered/logging-only does not,
  handler-identity drift fails alone; this lane adds the three named
  negatives that were still missing at `main()` level — missing tracking
  issue, unparseable review date, and a fully valid entry registered under a
  foreign `(file, method, path)` identity, which excuses nothing (the
  exact-route keying is the #389 guard against a broad exemption).
- **No new exemption instance or closure claim** → registry byte-identical
  to develop; zero `temporary` entries; nothing here closes #389.

## Root-suite delta (+3, `tests/test_check_api_route_contracts.py`)

- `test_main_temporary_disposition_without_issue_does_not_excuse` — a
  temporary entry with no tracking issue: registry failure ("needs an
  issue") and the canned finding both fire, `main() == 1`.
- `test_main_temporary_disposition_with_malformed_date_does_not_excuse` —
  an unparseable review date: registry failure ("unparseable expires") and
  the canned finding both fire, `main() == 1`.
- `test_main_temporary_disposition_under_foreign_identity_does_not_excuse`
  — a fully valid temporary entry (issue, future date, live handler,
  matching name) registered against a *different* live route leaves the
  canned handler unexcused: `main() == 1` on the canned finding alone, with
  zero registry failures, pinning the excuse's exact-identity keying.
  Fail-before verified against a scratch leaky variant of the gate (any
  valid temporary entry excuses every canned handler): the test fails there
  (`0 == 1`) while the valid-entry pass test still passes.

(The first attempt's note claimed `tests/: +9`; those tests pinned the
superseded tracking-only contract and were withdrawn with it. Net lane
delta against develop is +3.)

## Validation (this round, at the reconciled head)

- `uv sync --locked --extra dev` — clean.
- `uv run pytest tests/test_check_api_route_contracts.py -q` — 64 passed
  (develop's suite + the 3 new negatives).
- `uv run python scripts/check-api-route-contracts.py` — OK on the real
  tree (0 canned), exit 0.
- `uv run ruff check` + `uv run ruff format --check` on changed files —
  clean.
- `uv run python scripts/check-suite-inventory.py` (root `tests/`) — ok,
  baseline updated for the +2.
- Four surfaces verified byte-identical to `ab8b3737` via
  `git diff ab8b3737 -- <file>` (empty).

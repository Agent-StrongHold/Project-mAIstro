---
inventory-delta:
  tests/: +9
---

# auto-1859 — the API gate's temporary-disposition contract (#1859)

## Contract decision (recorded, not silently chosen)

Issue #1859 asked the policy owner to state whether a registered `temporary`
entry is tracking-only while the gate stays red, or whether a narrowly
governed exception actually passes. No owner statement exists anywhere in the
dispatch evidence: #1859 has zero comments, #389's captured thread has none,
and the only review on the implementation PR (#1716) is a Codex bot
suggestion. The exception branch is gated on owner authorization that never
arrived, so this change implements the only branch that cannot weaken #389:
**registration is tracking-only — every canned handler fails
`scripts/check-api-route-contracts.py` whether it is registered or not.**
No registry route entry changed disposition; no canned route ships.

## What was wrong (characterized before changing)

A synthetic full-gate run with a canned handler whose exact registry entry
carries `disposition="temporary"`, a tracking issue (#9999) and a future
expiry exited **1** — while the failure advice simultaneously offered
"or register a temporary disposition in …" as the third option. The module
docstring and `docs/api/route-contract-inventory.md` advertised registration
as the way a canned handler "can only ship", and `quality/api-route-contracts.json`'s
`_comment` said the gate "refuses it once expired" (implying it passes before
expiry). `_check_registry` validated the fields; `main()` never consulted the
disposition. So the documented escape hatch could never be used — the docs
offered a pass that the code never granted.

## Changes

- `scripts/check-api-route-contracts.py`: docstring states the tracking-only
  contract; `_canned_handlers` returns `(registry identity, display)` pairs so
  `main()` can tell a tracked entry from an unregistered one; the canned
  finding names a valid temporary entry (issue, expiry) as tracking-only debt
  that "does not pass this gate", and the unregistered advice offers only
  implement-or-refuse, saying explicitly that registration "cannot pass this
  gate". Also drops an accidental duplicated `REQUIRED_TEMPORARY` assignment.
- `docs/api/route-contract-inventory.md` (CI-enforcement section) and the
  registry `_comment`: same contract, no registration-as-a-pass anywhere.
- `quality/api-route-contracts.json`: `_comment` line only; all 15 route
  entries byte-identical.

## Root-suite delta (+9, all in `tests/test_check_api_route_contracts.py`)

Full-gate `main()`-level proofs, with relative-to-`date.today()` dates so the
future/expired cases are deterministic on any run day:

- `test_main_valid_temporary_entry_is_tracking_only_and_still_fails` — the
  characterization pinned as contract: valid entry, exit 1, exactly one
  finding (the canned handler), message names `#9999` and `tracking-only`;
  asserts the registry leg contributed nothing (no rot / needs-an-issue /
  expired / unparseable strings).
- `test_main_valid_temporary_entry_passes_when_the_handler_is_not_canned` —
  negative control: the same entry over a real-work handler leaves the gate
  green, proving the red comes from the canned body, not the registration.
- `test_main_temporary_entry_without_issue_fails`, `..._with_expired_date_fails`,
  `..._with_malformed_date_fails`, `..._with_wrong_identity_fails` — missing
  issue, expired date, unparseable date, and rot (entry under a foreign
  identity) all fail with the named finding plus the canned handler.
- `test_main_unregistered_canned_advice_does_not_offer_registration_as_a_pass`
  — asserts the old "or register a temporary disposition" phrasing is gone.
- `test_main_missing_registry_still_names_the_canned_handler` — an unreadable
  registry must not hide the canned handler behind it.
- `test_registry_routes_tolerates_malformed_registry` — the advice lookup's
  defensive branches: non-list `routes`, non-object entries, non-string
  identity parts.

One existing test updated in place for the `_canned_handlers` return-shape
change (no count change). Both contract-pinning tests were executed against
the pre-change script (HEAD) and FAIL there, PASS against the change.

## Validation

- `uv run pytest tests/ --timeout=30 -q` → 4425 passed, 91 skipped.
- `uv run pytest tests/test_check_api_route_contracts.py -q` → 39 passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_noop_route_contracts.py -q`
  → 15 passed (includes the gate self-check as a subprocess on the real tree).
- `python3 scripts/check-api-route-contracts.py` → OK (279 handlers, 15
  audited, 0 canned), exit 0.
- `uv run ruff check` + `ruff format --check` on changed files → clean.
- `uv run python scripts/check-doc-links.py` → 0 broken links.
- `scripts/check-diff-coverage.py` (coverage producer replicated: `coverage
  run --branch --source=scripts -m pytest tests/`) → see the run log; the
  changed gate lines are exercised by the new tests.

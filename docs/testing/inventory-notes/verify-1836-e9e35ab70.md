---
inventory-delta:
  tests/: +0
---

# Independent verification round at head e9e35ab70 (L1836, issue #1836)

Read-only verification sweep of the decision-gate lane at the assigned head
`e9e35ab7010d4b0796e61003c8768a867bef2017` (develop base `e12e11288`, merge-base
equal to base — sync complete). Every check below was executed at that head in
the locked dev environment; nothing was trusted from prior round summaries.

## Quality / acceptance-state ratchet — prior stale-bank finding resolved

`uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
e12e11288…` (quality.yml's exact PR-candidate arguments): rc 0. The
`design_coverage` fall to 39.641 is authorized from the merge base by the
owner-authorized #166 grant (loaded from `e12e11288e18`, two-merge rule
observed), the re-bank landed at `78e02d8db`, and the mandate/chain sections
report zero added or unproven criteria.

## SPEC-101826-1836 golden vectors V-1 … V-18 — all reproduce

Re-executed from the document's own recipes at this head: V-1 bytes and digest
byte-for-byte, V-2 reorder-invariance, all eleven V-3…V-13 mutation digests
(distinct from V-1 and each other), V-14 bool/int and int/float distinctions,
V-15 v2 `TypeError` messages with exact paths plus every deterministic v1
hazard fragment, V-16 v1 key-coercion collision and mixed-key failure, V-17
`ensure_ascii` pin (v1 digest `9db11f5f…`), and V-18 (`1748e5b5…`), including
the end-to-end legacy fallback: a production `DurableApproval` with an empty
`request_digest` and no carried `params["request_digest"]`/`params["request"]`
resolves to the v1 digest of its inner `params` payload.

## Image-lock gate — 44/44; parser-swap discrimination verified

`uv run pytest tests/test_check_image_lock_reconciliation.py -q`: 44 passed.
The previously-UNVERIFIED discrimination sub-claim was re-executed in a
shadow copy (historical parser swapped in, test file held fixed):

- Against `4de7e906d9dc` (single-pin-per-name): 5 of the six union fork node
  IDs fail; the survivor is
  `test_resolution_fork_any_locked_version_reconciles` — as recorded.
- Against `f956a8142` (name-keyed sets): exactly the two recorded failures —
  `test_required_name_with_conditional_alternate_is_missing_only_when_absent`
  and `test_conditional_pin_with_multiple_marker_versions_still_names_an_unknown_branch`.
- Against the resolved script at this head: all 44 pass.

## Gates and hygiene

`check-adr-status-language` rc 0; `git diff --check` rc 0;
`check-suite-inventory` rc 0 (21 suites, no delta);
`check-workflow-inventory` rc 0 (32 workflows dispositioned); `ruff check .`
and `ruff format --check .` rc 0. Commit messages `e12e11288..HEAD` scanned
for closure keywords: none; the PR body says "Refs #1836" only. ADR-090726-9a4e
remains `Accepted` and untouched by the branch; SPEC-101826-1836 remains
`Proposed` with owner acceptance absent by design — issue #1836 stays open
pending the named owner's review, and no closure action is taken or claimed.
